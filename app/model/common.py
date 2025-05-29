import os
import sys
from abc import ABC, abstractmethod
from typing import Any, Literal

import litellm
from litellm import cost_per_token
from litellm.exceptions import APIConnectionError as LiteLLMAPICError
from litellm.exceptions import RateLimitError as LiteLLMRateLimitError
from litellm.exceptions import ServiceUnavailableError as LiteLLMServiceUnavailableError
from litellm.exceptions import Timeout as LiteLLMTimeout
from litellm.utils import Choices, Message, ModelResponse
from openai import APIConnectionError as OpenAPICError
from openai import APITimeoutError as OpenAITimeoutError
from openai import BadRequestError
from openai import InternalServerError as OpenAIInternalServerError
from openai import RateLimitError as OpenAIRateLimitError
from pydantic import BaseModel, Field
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.log import log_and_cprint, log_and_print

# Retry parameters (adjust as needed)
NUM_RETRIES = 3
RETRY_MIN_WAIT = 5  # seconds
RETRY_MAX_WAIT = 300  # seconds
RETRY_MULTIPLIER = 2

# Global counter for total retry attempts
TOTAL_RETRY_ATTEMPTS = 0


def get_total_retry_attempts():
    global TOTAL_RETRY_ATTEMPTS
    return TOTAL_RETRY_ATTEMPTS


def increment_total_retry_attempts():
    global TOTAL_RETRY_ATTEMPTS
    TOTAL_RETRY_ATTEMPTS += 1


# Variables for each process. Since models are singleton objects, their references are copied
# to each process, but they all point to the same objects. For safe updating costs per process,
# we define the accumulators here.


class ClaudeContentPolicyViolation(RuntimeError):
    pass


class ModelNoResponseError(RuntimeError):
    """Raised when the model API returns a successful status but no valid response content."""

    pass


class Usage(BaseModel):
    """Metric tracking detailed usage per completion call."""

    model: str = Field(description="The model name", default="")
    input_tokens: int = Field(description="The number of input tokens", default=0)
    output_tokens: int = Field(description="The number of output tokens", default=0)
    cache_read_tokens: int = Field(
        description="The number of cache read tokens", default=0
    )
    cache_write_tokens: int = Field(
        description="The number of cache write tokens", default=0
    )
    cost: float = Field(description="The cost of the request", default=0.0)
    latency: float = Field(description="The latency of the request", default=0.0)
    call_cnt: int = Field(description="The number of calls", default=0)

    @classmethod
    def model_validate(cls, usage_dict: dict) -> "Usage":
        """
        Create a Usage object from a dictionary (Pydantic v2 compatible).
        Handles special string formats like "$0.01" for cost and "1.5s" for latency.

        Args:
            usage_dict: Dictionary containing Usage data, possibly with formatted strings

        Returns:
            Usage: A new Usage object
        """
        if not usage_dict:
            return Usage()

        # Extract numeric values, handling formatted strings
        cost_str = usage_dict.get("cost", "$0.000000")
        if cost_str.startswith("$"):
            cost = float(cost_str[1:])
        else:
            cost = float(cost_str)

        latency_str = usage_dict.get("latency", "0.00s")
        if latency_str.endswith("s"):
            latency = float(latency_str[:-1])
        else:
            latency = float(latency_str)

        # Create and return Usage object
        return Usage(
            model=usage_dict.get("model"),
            input_tokens=int(usage_dict.get("input_tokens")),
            output_tokens=int(usage_dict.get("output_tokens")),
            cache_read_tokens=int(usage_dict.get("cache_read_tokens")),
            cache_write_tokens=int(usage_dict.get("cache_write_tokens")),
            cost=cost,
            latency=latency,
            call_cnt=int(usage_dict.get("call_cnt")),
        )

    def model_dump(self, print_tokens: bool = True, **kwargs):
        """Override model_dump to ensure proper serialization."""
        if (
            self.call_cnt == 0
            and self.cost == 0.0
            and self.latency == 0.0
            and self.input_tokens == 0
            and self.output_tokens == 0
        ):
            return {}
        if print_tokens:
            return {
                "model": self.model,
                "cost": f"${self.cost:.8f}",
                "call_cnt": self.call_cnt,
                "latency": f"{self.latency:.2f}s",
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cache_read_tokens": self.cache_read_tokens,
                "cache_write_tokens": self.cache_write_tokens,
            }
        else:
            return {
                "cost": f"${self.cost:.6f}",
                "call_cnt": self.call_cnt,
                "latency": f"{self.latency:.2f}s",
            }

    def __add__(self, other):
        """
        Define addition operator for Usage objects.

        Args:
            other (Usage): Another Usage object to add

        Returns:
            Usage: A new Usage object with combined metrics
        """
        if not isinstance(other, Usage):
            return NotImplemented

        modelname = ""
        if self.model == "":
            modelname = other.model
        elif other.model == "":
            modelname = self.model
        else:
            if self.model != other.model:
                modelname = f"{self.model}+{other.model}"
            else:
                modelname = self.model

        return Usage(
            model=modelname,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cost=self.cost + other.cost,
            call_cnt=self.call_cnt + other.call_cnt,
            latency=self.latency + other.latency,
        )


def get_usage_input_part(usage: Usage) -> Usage:
    input_cost, _ = cost_per_token(
        model=usage.model,
        prompt_tokens=usage.input_tokens,
        completion_tokens=usage.output_tokens,
        cache_read_input_tokens=usage.cache_read_tokens,
        cache_creation_input_tokens=usage.cache_write_tokens,
    )
    assert usage.call_cnt == 1
    return Usage(
        model=usage.model,
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost=input_cost,
        latency=0,
        call_cnt=0,
    )


def get_usage_output_part(usage: Usage) -> Usage:
    _, output_cost = cost_per_token(
        model=usage.model,
        prompt_tokens=usage.input_tokens,
        completion_tokens=usage.output_tokens,
        cache_read_input_tokens=usage.cache_read_tokens,
        cache_creation_input_tokens=usage.cache_write_tokens,
    )
    assert usage.call_cnt == 1
    return Usage(
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cost=output_cost,
        latency=usage.latency,
        call_cnt=usage.call_cnt,
    )


def init_agent_usage_details() -> dict[str, Usage]:
    usage_details: dict[str, Usage] = {
        "TOTAL": Usage(),
    }
    return usage_details


def update_usage_details(
    usage_details: dict[str, Usage],
    last_call: list[str],
    usage: Usage,
) -> None:
    """Update usage details for the current call.

    Args:
        usage_details: Dictionary containing usage details for each tool
        last_call: List of tool names that were called in the last iteration
        usage: Usage object containing the current call's usage information
    """
    usage_details["TOTAL"] += usage

    for _call in last_call:
        if _call not in usage_details:
            usage_details[_call] = Usage()
        usage_details[_call] += usage  # maybe multiple tool calls share the same usage


# Define exceptions to retry on for the base Model class
RETRYABLE_EXCEPTIONS = (
    LiteLLMRateLimitError,
    LiteLLMTimeout,
    LiteLLMAPICError,
    LiteLLMServiceUnavailableError,
    OpenAIRateLimitError,
    OpenAITimeoutError,
    OpenAPICError,
    OpenAIInternalServerError,
    ModelNoResponseError,
    # Add other transient errors if observed
)


def _log_retry_attempt(retry_state: RetryCallState) -> None:
    """Logs a retry attempt, including the wait time before the next attempt."""
    increment_total_retry_attempts()

    exception = retry_state.outcome.exception()
    wait_time = retry_state.next_action.sleep
    log_and_cprint(
        f"LLM call failed with {type(exception).__name__}: {exception}. "
        f"Waiting {wait_time:.2f} seconds before retrying attempt {retry_state.attempt_number + 1}/{NUM_RETRIES}...",
        style="yellow",
    )


class Model(ABC):
    def __init__(
        self,
        name: str,
        cost_per_input: float,
        cost_per_output: float,
        parallel_tool_call: bool = False,
    ):
        self.name: str = name
        # cost stats - zero for local models
        self.cost_per_input: float = cost_per_input
        self.cost_per_output: float = cost_per_output
        # whether the model supports parallel tool call
        self.parallel_tool_call: bool = parallel_tool_call

    @abstractmethod
    def check_api_key(self) -> str:
        raise NotImplementedError("abstract base class")

    @abstractmethod
    def setup(self) -> None:
        raise NotImplementedError("abstract base class")

    @abstractmethod
    def _perform_call(self, messages: list[dict], **kwargs) -> Any:
        """
        Actual implementation of the model call, to be implemented by subclasses.
        This method will be wrapped by the retry logic in the public `call` method.
        """
        raise NotImplementedError("abstract base class")

    # Apply the retry decorator to the public call method
    @retry(
        stop=stop_after_attempt(NUM_RETRIES),
        # Use randomized exponential backoff with the defined multiplier
        wait=wait_random_exponential(
            multiplier=RETRY_MULTIPLIER, min=RETRY_MIN_WAIT, max=RETRY_MAX_WAIT
        ),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        before_sleep=_log_retry_attempt,
        reraise=True,  # Reraise the exception if all retries fail
    )
    def call(self, messages: list[dict], **kwargs) -> Any:
        """
        Public method to call the LLM. Includes retry logic.
        Delegates the actual API call to _perform_call.
        """
        # Assuming setup is called elsewhere appropriately before the first call
        try:
            return self._perform_call(messages=messages, **kwargs)
        except Exception as e:
            # Log message thread before reraising the exception
            log_and_print(f"Exception in model call: {type(e).__name__}: {str(e)}")
            log_and_print(f"Message thread: {messages}")
            raise

    def calc_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Calculates the cost of a request based on the number of input/output tokens.
        """
        input_cost = self.cost_per_input * input_tokens
        output_cost = self.cost_per_output * output_tokens
        cost = input_cost + output_cost
        log_and_cprint(
            f"Model ({self.name}) API request cost info: "
            f"input_tokens={input_tokens}, output_tokens={output_tokens}, cost={cost:.6f}",
            style="yellow",
        )
        return cost

    def get_overall_exec_stats(self):
        return {
            "model": self.name,
            "input_cost_per_token": self.cost_per_input,
            "output_cost_per_token": self.cost_per_output,
        }


class LiteLLMGeneric(Model):
    """
    Base class for creating instances of LiteLLM-supported models.
    """

    _instances = {}

    def __new__(cls, model_name: str, cost_per_input: float, cost_per_output: float):
        if model_name not in cls._instances:
            cls._instances[model_name] = super().__new__(cls)
            cls._instances[model_name]._initialized = False
        return cls._instances[model_name]

    def __init__(
        self,
        name: str,
        cost_per_input: float,
        cost_per_output: float,
        parallel_tool_call: bool = False,
    ):
        if self._initialized:
            return
        super().__init__(name, cost_per_input, cost_per_output, parallel_tool_call)
        self._initialized = True

    def setup(self) -> None:
        """
        Check API key.
        """
        pass

    def check_api_key(self) -> str:
        return ""

    def extract_resp_content(self, chat_message: Message) -> str:
        """
        Given a chat completion message, extract the content from it.
        """
        content = chat_message.content
        if content is None:
            return ""
        else:
            return content

    def _perform_call(
        self,
        messages: list[dict],
        top_p=1,
        tools=None,
        response_format: Literal["text", "json_object"] = "text",
        **kwargs,
    ):
        # FIXME: ignore tools field since we don't use tools now
        try:
            prefill_content = "{"
            if response_format == "json_object":  # prefill
                messages.append({"role": "assistant", "content": prefill_content})

            response = litellm.completion(
                model=self.name,
                messages=messages,
                temperature=MODEL_TEMP,
                max_tokens=os.getenv("ACR_TOKEN_LIMIT", 1024),
                response_format=(
                    {"type": response_format} if "gpt" in self.name else None
                ),
                top_p=top_p,
                stream=False,
            )
            assert isinstance(response, ModelResponse)

            # Check if the response has valid choices before proceeding
            if not response.choices or len(response.choices) == 0:
                raise ModelNoResponseError(
                    f"Model {self.name} returned a response with no choices. Response: {response}"
                )

            resp_usage = response.usage
            assert resp_usage is not None
            input_tokens = int(resp_usage.prompt_tokens)
            output_tokens = int(resp_usage.completion_tokens)
            cost = self.calc_cost(input_tokens, output_tokens)

            first_resp_choice = response.choices[0]
            assert isinstance(first_resp_choice, Choices)
            resp_msg: Message = first_resp_choice.message
            content = self.extract_resp_content(resp_msg)
            if response_format == "json_object":
                # prepend the prefilled character
                if not content.startswith(prefill_content):
                    content = prefill_content + content

            return content, cost, input_tokens, output_tokens

        except BadRequestError as e:
            if e.code == "context_length_exceeded":
                log_and_print("Context length exceeded")
            raise e


MODEL_HUB = {}


def register_model(model: Model):
    global MODEL_HUB
    MODEL_HUB[model.name] = model


def get_all_model_names():
    return list(MODEL_HUB.keys())


# To be set at runtime - the selected model for a run
SELECTED_MODEL: Model


def set_model(model_name: str):
    global SELECTED_MODEL
    if model_name not in MODEL_HUB and not model_name.startswith("litellm-generic-"):
        print(f"Invalid model name: {model_name}")
        sys.exit(1)
    if model_name.startswith("litellm-generic-"):
        real_model_name = model_name.removeprefix("litellm-generic-")
        prompt_tokens = 5
        completion_tokens = 10
        prompt_tokens_cost_usd_dollar, completion_tokens_cost_usd_dollar = (
            cost_per_token(
                model=real_model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )
        # litellm.set_verbose = True
        SELECTED_MODEL = LiteLLMGeneric(
            real_model_name,
            prompt_tokens_cost_usd_dollar,
            completion_tokens_cost_usd_dollar,
        )
    else:
        SELECTED_MODEL = MODEL_HUB[model_name]
    SELECTED_MODEL.setup()


# the model temperature to use
# For OpenAI models: this value should be from 0 to 2
MODEL_TEMP: float = 0.0
