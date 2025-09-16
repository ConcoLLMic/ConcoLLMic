import html
import json
import re

from loguru import logger
from pydantic_xml import BaseXmlModel

from app.agents.states import ConcolicExecutionState

MAX_CODE_REQUEST_ATTEMPTS = (
    10  # Maximum allowed number of CodeRequest attempts in summarizer
)
# pattern for instrumentation in the code
TRACE_PATTERN = r".*?(enter|exit)\s+([^\s]+)\s+(\d+).*?"

FILE_TRACE_PATTERN = r"\[([^\s\]]+)\]\s+(enter|exit)\s+([^\s]+)\s+(\d+)"  # use re.search or re.findall instead of re.match
# "[no_space_characters]" + "space" + "enter/exit" + "space" + "no_space_characters" + "space" + "number"

TOTAL_COST_FORMAT = "Total cost: {:.6f}"
SPLIT_COST_FORMAT_WITH_CHUNKS = "Total split cost: {:.6f}, input tokens: {}, output tokens: {}, cache read tokens: {}, cache write tokens: {}, split chunks: {}"
INSTRUMENTED_COST_FORMAT = "Total instrumented cost: {:.6f}, input tokens: {}, output tokens: {}, cache read tokens: {}, cache write tokens: {}"

TOTAL_COST_PATTERN = r".*Total cost: ([\d.]+)"
SPLIT_COST_PATTERN = r"(?i).*Total split cost: ([\d.]+), input tokens: (\d+), output tokens: (\d+)(?:, cache read tokens: (\d+), cache write tokens: (\d+))?.? Split chunks:[\s]*(.+)"
INSTRUMENTED_COST_PATTERN = r"(?i).*Total instrumented cost: ([\d.]+), input tokens: (\d+), output tokens: (\d+)(?:, cache read tokens: (\d+), cache write tokens: (\d+))?"


CONCOLIC_EXECUTION_STATE = None


def set_concolic_execution_state(state: ConcolicExecutionState):
    global CONCOLIC_EXECUTION_STATE
    CONCOLIC_EXECUTION_STATE = state


def get_concolic_execution_state() -> ConcolicExecutionState:
    global CONCOLIC_EXECUTION_STATE
    return CONCOLIC_EXECUTION_STATE


class Instructions(BaseXmlModel, tag="instructions"):
    instructions: str


class ExecutionInformation(BaseXmlModel, tag="execution_information"):
    execution_information: str


class SourceCode(BaseXmlModel, tag="source_code"):
    source_code: str


class FilePath(BaseXmlModel, tag="file_path"):
    file_path: str


class NewExecutionInformation(BaseXmlModel, tag="new_execution_information"):
    new_execution_information: str


class NewExecutionTrace(BaseXmlModel, tag="new_execution_trace"):
    new_execution_trace: str


class ExecutionTrace(BaseXmlModel, tag="execution_trace"):
    execution_trace: str


class TargetPathConstraint(BaseXmlModel, tag="target_path_constraint"):
    target_path_constraint: str


class TestCaseInformation(BaseXmlModel, tag="test_case_information"):
    test_case_information: str


class PathConstraint(BaseXmlModel, tag="path_constraint"):
    path_constraint: str


class TestCaseId(BaseXmlModel, tag="test_case_id"):
    test_case_id: str


class SrcTestCaseId(BaseXmlModel, tag="src_test_case_id"):
    src_test_case_id: str


class FunctionCallChain(BaseXmlModel, tag="function_call_chain"):
    function_call_chain: str


class HistoricalInformation(BaseXmlModel, tag="historical_information"):
    historical_information: str


class ExampleUserInput(BaseXmlModel, tag="example_user_input"):
    example_user_input: str


class ExampleInstrumentedCode(BaseXmlModel, tag="example_instrumented_code"):
    example_instrumented_code: str


class InstrumentedCode(BaseXmlModel, tag="instrumented_code"):
    instrumented_code: str


class FunctionInfo(BaseXmlModel, tag="function_info"):
    function_info: str


class ExampleAssistantOutput(BaseXmlModel, tag="example_assistant_output"):
    example_assistant_output: str


class SourceCodeToInstrument(BaseXmlModel, tag="source_code_to_instrument"):
    source_code_to_instrument: str


class UpdatedCode(BaseXmlModel, tag="updated_code"):
    updated_code: str


class TargetBranch(BaseXmlModel, tag="target_branch"):
    target_branch: str


class AlreadySelectedBranchButNotReached(
    BaseXmlModel, tag="already_selected_branch_but_not_reached"
):
    already_selected_branch_but_not_reached: str


class ResponseParseException(Exception):
    pass


def extract_between_tags(
    tag: str, string: str, strip: bool = False, use_unescape: bool = True
) -> list[str]:
    """
    https://github.com/anthropics/anthropic-cookbook/blob/main/misc/how_to_enable_json_mode.ipynb
    """
    if use_unescape:
        string = html.unescape(string)

    ext_list = re.findall(f"<{tag}>(.+?)</{tag}>", string, re.DOTALL)
    if strip:
        ext_list = [e.strip() for e in ext_list]
    if len(ext_list) == 0:
        raise ResponseParseException(f"Failed to extract from tag <{tag}>")
    return ext_list


def filter_instr_print(stderr_str: str) -> str:
    filtered_stderr = ""
    for line in stderr_str.split("\n"):
        # replace FILE_TRACE_PATTERN with ""
        line = re.sub(FILE_TRACE_PATTERN, "", line.strip())
        if line.strip():
            filtered_stderr += line + "\n"
    return filtered_stderr


def wrap_between_tags(tag: str, string: str) -> str:
    return f"<{tag}>{string}</{tag}>"


def parse_tool_arguments(tool_call: dict) -> dict:
    """Parse tool call arguments to extract JSON data."""
    args = tool_call.get("function", {}).get("arguments", {})
    if isinstance(args, str):

        try:
            return json.loads(args)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse tool call arguments: {args}")
            # Raise the exception instead of continuing
            raise RuntimeError(f"Failed to parse tool call arguments: {args}")
    return args


def delete_instrumentation_comments(
    source_code: dict[int, str], comment_token: str
) -> dict[int, str]:
    lines = [source_code[i] for i in range(1, len(source_code) + 1)]

    while lines and lines[-1].strip() == "":
        lines.pop()

    while (
        lines
        and lines[-1].strip().startswith(comment_token)
        and (
            "Total cost" in lines[-1]
            or "Total split cost" in lines[-1]
            or "Total instrumented cost" in lines[-1]
        )
    ):
        lines.pop()

    return {i + 1: lines[i] for i in range(len(lines))}


def delete_instrumentation_from_code(
    instrumented_code: dict[int, str], comment_token: str
) -> dict[int, str]:
    """
    Delete instrumentation logging statements from the code.
    """
    instrumented_code = delete_instrumentation_comments(
        instrumented_code, comment_token
    )
    original_code = {}
    original_code_lines = 1
    for _, line in instrumented_code.items():
        if not re.match(TRACE_PATTERN, line.strip()):
            original_code[original_code_lines] = line
            original_code_lines += 1
    return original_code


SCHEDULING_FORMAT_REMINDER = (
    "Format Remind: "
    + wrap_between_tags(
        FunctionCallChain.__xml_tag__,
        "{filename}[func_name (overall line coverage until now)][line coverage achieved by this execution]",
    )
    + "\n"
    + wrap_between_tags(
        HistoricalInformation.__xml_tag__,
        "[failed times]/[total selected times](ratio)",
    )
    + "\n\n This following is the information of each test case: "
)
