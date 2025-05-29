import json
from collections.abc import Mapping
from os import PathLike
from pathlib import Path
from pprint import pformat

from loguru import logger
from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_message_tool_call import (
    Function as OpenaiFunction,
)


class FunctionCallIntent:
    """An intent to call a tool function.

    This object created from OpenAI API response.
    """

    def __init__(
        self,
        func_name: str,
        arguments: Mapping[str, str],
        openai_func: OpenaiFunction | None,
    ):
        self.func_name = func_name
        self.arg_values = dict()
        self.arg_values.update(arguments)
        # record the original openai function object,
        # which is used when we want tell the model that it has
        # previously called this function/tool
        self.openai_func = openai_func or OpenaiFunction(
            arguments=json.dumps(arguments), name=func_name
        )

    def __str__(self):
        return f"Call function `{self.func_name}` with arguments {self.arg_values}."

    def to_dict(self):
        return {"func_name": self.func_name, "arguments": self.arg_values}

    def to_dict_with_result(self, call_ok: bool):
        return {
            "func_name": self.func_name,
            "arguments": self.arg_values,
            "call_ok": call_ok,
        }


class MessageThread:
    """
    Represents a thread of conversation with the model.
    Abstrated into a class so that we can dump this to a file at any point.
    """

    def __init__(self, caching=True, cache_window=2, messages=None):
        self.messages: list[dict] = messages or []
        self.caching: bool = caching
        self.cache_window: int = cache_window
        self.last_cached_round: int = 0

    def should_cache(self, to_cache: bool) -> bool:
        if not self.caching:
            return False
        elif to_cache:
            return True
        elif self.get_round_number() >= self.last_cached_round + self.cache_window:
            self.cache_window *= 2  # Exponential decay of caching rate
            return True
        else:
            return False

    def enable_caching(self, content: dict, params: dict):
        return content, params

    def _clear_cache_control(self, msg: dict):
        assert msg["role"] != "system", "System message cache should not be cleared"

        if isinstance(msg["content"], list):
            assert len(msg["content"]) == 1, "Expected single message in content"
            msg["content"][0].pop("cache_control", None)
        msg.pop("cache_control", None)

    def _set_cache_control(self, msg: dict):

        if msg["role"] == "tool":
            # Workaround for weird bug
            msg["cache_control"] = {"type": "ephemeral"}
        else:
            msg["content"][0]["cache_control"] = {"type": "ephemeral"}

    def add(
        self,
        role: str,
        content: dict,
        params: dict = {},
        to_cache: bool = False,
        clear_pre_cache_role: list = ["user", "tool", "assistant"],
    ):  # clear_pre_cache_role is used to clear the cache of previous messages, ONLY work when THIS MESSAGE IS CACHED !
        msg_object = {"role": role, "content": [content]}
        msg_object = msg_object | params

        if self.should_cache(to_cache):
            logger.debug(
                f'Caching message for role "{role}" and clearing previous messages with cache_control for roles "{clear_pre_cache_role}"'
            )
            self.last_cached_round = self.get_round_number()
            # delete previous messages with cache_control
            if len(clear_pre_cache_role) > 0:
                for prev_msg in self.messages:
                    if prev_msg["role"] in clear_pre_cache_role:
                        self._clear_cache_control(prev_msg)
            self._set_cache_control(msg_object)

        self.messages.append(msg_object)

    def add_message(
        self,
        role: str,
        message: str,
        params: dict = {},
        to_cache: bool = False,
        clear_pre_cache_role: list = ["user", "tool", "assistant"],
    ):
        """
        Add a new message to the thread.
        Args:
            message (str): The content of the new message.
            role (str): The role of the new message.
        """
        content = {"type": "text", "text": message}
        self.add(
            role,
            content,
            params=params,
            to_cache=to_cache,
            clear_pre_cache_role=clear_pre_cache_role,
        )

    def add_system(self, message: str, to_cache=True, clear_pre_cache_role=[]):
        self.add_message(
            "system",
            message,
            to_cache=to_cache,
            clear_pre_cache_role=clear_pre_cache_role,
        )

    def add_user(
        self,
        message: str,
        to_cache=True,
        clear_pre_cache_role=["user", "tool", "assistant"],
    ):
        self.add_message(
            "user",
            message,
            to_cache=to_cache,
            clear_pre_cache_role=clear_pre_cache_role,
        )

    def add_tool(
        self,
        message: str,
        name: str = None,
        tool_call_id: str = None,
        to_cache=True,
        clear_pre_cache_role: list = ["user", "tool", "assistant"],
    ):
        m = {}
        if tool_call_id:
            m["tool_call_id"] = tool_call_id
        if name:
            m["name"] = name
        self.add_message(
            "tool",
            message,
            params=m,
            to_cache=to_cache,
            clear_pre_cache_role=clear_pre_cache_role,
        )

    def add_model(
        self, message: str | None, tools: list[ChatCompletionMessageToolCall] = []
    ):
        if tools is None or len(tools) == 0:
            self.add_message("assistant", message)
            return

        # let's serialize tools into json first
        json_tools = []
        for tool in tools:
            this_tool_dict = {}
            this_tool_dict["id"] = tool.id
            this_tool_dict["type"] = tool.type
            # now serialize function as well
            func_obj: OpenaiFunction = tool.function
            func_args: str = func_obj.arguments
            func_name: str = func_obj.name
            this_tool_dict["function"] = {"name": func_name, "arguments": func_args}
            json_tools.append(this_tool_dict)

        if json_tools == []:
            # there is no tool calls from the model last time,
            # the best we could do is to return the generated text
            self.add_message("assistant", message)
        else:
            self.add_message("assistant", message, params={"tool_calls": json_tools})

    def to_msg(self) -> list[dict]:
        """
        Convert to the format to be consumed by the model.
        Returns:
            List[Dict]: The message thread.
        """
        return self.messages

    def __str__(self):
        return pformat(self.messages, width=160, sort_dicts=False)

    def save_to_file(self, file_path: str | PathLike):
        """
        Save the current state of the message thread to a file.
        Args:
            file_path (str): The path to the file.
        """
        Path(file_path).write_text(json.dumps(self.messages, indent=4))

    def get_round_number(self) -> int:
        """
        From the current message history, decide how many rounds have been completed.
        """
        completed_rounds = 0
        for message in self.messages:
            if message["role"] == "assistant":
                completed_rounds += 1
        return completed_rounds

    @classmethod
    def load_from_file(cls, file_path: str):
        """
        Load the message thread from a file.
        Args:
            file_path (str): The path to the file.
        Returns:
            MessageThread: The message thread.
        """
        with open(file_path) as f:
            messages = json.load(f)
        return cls(messages)

    def copy(self):
        """
        Copy the current message thread.
        """
        return self.__class__(messages=self.messages)

    def remove_tool_messages(self, tool_name: str) -> int:
        """
        Remove all messages related to a specific tool from the message thread.
        This includes both the assistant's tool calls and the tool responses.

        Args:
            tool_name (str): The name of the tool to remove messages for.

        Returns:
            int: Number of messages removed.
        """
        # Keep track of messages to remove
        indices_to_remove = []
        tool_call_ids_to_remove = set()

        # First pass: identify assistant messages with tool calls to the specified tool
        # and collect their tool_call_ids
        for i, message in enumerate(self.messages):
            if message["role"] == "assistant" and "tool_calls" in message:
                # Check each tool call in this message
                has_target_tool = False
                for tool_call in message["tool_calls"]:
                    if isinstance(tool_call, dict) and "function" in tool_call:
                        if tool_call["function"]["name"] == tool_name:
                            has_target_tool = True
                            tool_call_ids_to_remove.add(tool_call["id"])

                # If this message contains the target tool, mark it for removal
                if has_target_tool:
                    indices_to_remove.append(i)

            # Check tool responses
            elif message["role"] == "tool":
                # If this is a response to a tool call we're removing
                if message.get("tool_call_id") in tool_call_ids_to_remove:
                    indices_to_remove.append(i)
                # Or if this is directly from the tool we're removing
                elif message.get("name") == tool_name:
                    indices_to_remove.append(i)

        # Remove messages in reverse order to avoid index issues
        removed_count = 0
        for index in sorted(indices_to_remove, reverse=True):
            del self.messages[index]
            removed_count += 1

        return removed_count
