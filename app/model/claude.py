"""
For models other than those from OpenAI, use LiteLLM if possible.
"""

import os
import sys
import time
from typing import Literal

import litellm
from litellm import completion_cost
from litellm.exceptions import BadRequestError as LiteLLMBadRequestError
from litellm.exceptions import (
    ContentPolicyViolationError as LiteLLMContentPolicyViolationError,
)
from litellm.utils import Choices, Message, ModelResponse

from app.log import log_and_cprint, log_and_print
from app.model import common
from app.model.common import (
    ClaudeContentPolicyViolation,
    Model,
    ModelNoResponseError,
    Usage,
)


class AnthropicModel(Model):
    """
    Base class for creating Singleton instances of Antropic models.
    """

    _instances = {}

    def __new__(cls):
        if cls not in cls._instances:
            cls._instances[cls] = super().__new__(cls)
            cls._instances[cls]._initialized = False
        return cls._instances[cls]

    def __init__(
        self,
        name: str,
        cost_per_input: float,
        cost_per_output: float,
        max_output_token: int = 4096,
        parallel_tool_call: bool = False,
    ):
        if self._initialized:
            return
        super().__init__(name, cost_per_input, cost_per_output, parallel_tool_call)
        self.max_output_token = max_output_token
        self._initialized = True

    def setup(self) -> None:
        """
        Check API key.
        """
        self.check_api_key()

    def check_api_key(self) -> str:
        key_name = "ANTHROPIC_API_KEY"
        key = os.getenv(key_name)
        if not key:
            print(f"Please set the {key_name} env var")
            sys.exit(1)
        return key

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
        temperature: float | None = None,
        **kwargs,
    ):
        if temperature is None:
            temperature = common.MODEL_TEMP

        try:

            if response_format == "json_object":
                last_content = messages[-1]["content"]
                last_content += "\nYour response should start with { and end with }. DO NOT write anything else other than the json."
                messages[-1]["content"] = last_content

            start_time = time.time()
            if self.name == "claude-3-7-sonnet-20250219-128k":
                response = litellm.completion(
                    model=self.name.replace("-128k", ""),
                    messages=messages,
                    temperature=temperature,
                    max_tokens=self.max_output_token,
                    top_p=top_p,
                    stream=False,  # TODO: use stream message according to docs: https://docs.anthropic.com/en/docs/about-claude/models/all-models
                    extra_headers={
                        "anthropic-beta": "output-128k-2025-02-19",
                    },  # https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking#extended-output-capabilities-beta
                    tools=tools,
                    **kwargs,
                )

            else:
                response = litellm.completion(
                    model=self.name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=self.max_output_token,
                    top_p=top_p,
                    stream=False,
                    tools=tools,
                    **kwargs,
                )

            latency = time.time() - start_time
            cost = completion_cost(model=self.name, completion_response=response)

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

            cache_creation_tokens = int(
                resp_usage.get("cache_creation_input_tokens", 0)
            )
            cache_read_tokens = int(resp_usage.get("cache_read_input_tokens", 0))

            first_resp_choice = response.choices[0]
            assert isinstance(first_resp_choice, Choices)
            resp_msg: Message = first_resp_choice.message

            # Extract content from the message
            content = self.extract_resp_content(resp_msg)

            # Extract tool calls from the message
            tool_calls = (
                resp_msg.tool_calls if hasattr(resp_msg, "tool_calls") else None
            )

            log_and_cprint(
                f"Model ({self.name}) API request usage info: "
                f"{{input_tokens={input_tokens}, output_tokens={output_tokens}, cache_read_tokens={cache_read_tokens}, cache_write_tokens={cache_creation_tokens}}}, cost={cost:.6f} USD, latency={latency:.6f} seconds",
                style="yellow",
            )
            # total prompt tokens = input_tokens (already includes cache_read_tokens) + cache_write_tokens
            # so the price should be (input_tokens - cache_read_tokens) * input_cost + cache_write_tokens * cache_write_cost + cache_read_tokens * cache_read_cost + output_tokens * output_cost

            # Return content, tool_calls, and stats
            return (
                content,
                tool_calls,
                Usage(
                    model=self.name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_creation_tokens,
                    cost=cost,
                    latency=latency,
                    call_cnt=1,
                ),
            )

        except LiteLLMContentPolicyViolationError:
            # claude sometimes send this error when writing patch
            log_and_print("Encountered claude content policy violation.")
            raise ClaudeContentPolicyViolation

        except LiteLLMBadRequestError as e:
            if e.code == "context_length_exceeded":
                log_and_print("Context length exceeded")
            raise e


class Claude3Opus(AnthropicModel):
    def __init__(self):
        super().__init__(
            "claude-3-opus-20240229", 0.000015, 0.000075, parallel_tool_call=True
        )
        self.note = "Most powerful model among Claude 3"


class Claude3Sonnet(AnthropicModel):
    def __init__(self):
        super().__init__(
            "claude-3-sonnet-20240229", 0.000003, 0.000015, parallel_tool_call=True
        )
        self.note = "Most balanced (intelligence and speed) model from Antropic"


class Claude3Haiku(AnthropicModel):
    def __init__(self):
        super().__init__(
            "claude-3-haiku-20240307", 0.00000025, 0.00000125, parallel_tool_call=True
        )
        self.note = "Fastest model from Antropic"


class Claude3_5Sonnet(AnthropicModel):
    def __init__(self):
        super().__init__(
            "claude-3-5-sonnet-20241022",
            0.000003,
            0.000015,
            parallel_tool_call=True,
            max_output_token=8192,
        )
        self.note = "Previous most intelligent model from Antropic"


class Claude3_7Sonnet(AnthropicModel):
    def __init__(self):
        super().__init__(
            "claude-3-7-sonnet-20250219",
            0.000003,
            0.000015,
            parallel_tool_call=True,
            max_output_token=8192,
        )
        self.note = (
            "Most intelligent model from Antropic with default 8k output token limit"
        )


class Claude3_7Sonnet_128k(AnthropicModel):
    def __init__(self):
        super().__init__(
            "claude-3-7-sonnet-20250219-128k",
            0.000003,
            0.000015,
            parallel_tool_call=True,
            max_output_token=128000,
        )
        self.note = "Most intelligent model from Antropic with 128k output token limit"
