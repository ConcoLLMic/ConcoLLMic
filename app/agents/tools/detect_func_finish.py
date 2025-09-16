"""
Tool for finalizing the function detection process.
"""

from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

_DETECT_FINISH_DESCRIPTION = """Use this tool to indicate you have COMPLETED the function detection process.

You should use this tool:
1. After you have successfully reported ALL function implementations
2. When you are confident you have not missed any function implementations
3. When the file has NO function implementations (e.g., in header files with ONLY declarations)

This tool signals that you have finished the function detection phase.
"""

# Define the finish detection tool
ReportFuncFinishTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="finish_detection",
        description=_DETECT_FINISH_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["complete", "no_functions_found"],
                    "description": "Status of the function detection process - 'complete' if ALL functions were detected and reported, 'no_functions_found' if the file has no function implementations",
                },
            },
            "required": ["status"],
        },
    ),
)


def process_report_func_finish(status: str | None) -> tuple[str, bool, bool]:
    """
    Process the finish detection tool response.

    Args:
        status: Status of the function detection - 'complete' or 'no_functions_found'

    Returns:
        observation message
        is_valid: True if the status is valid, False otherwise
        is_complete: True if the status is 'complete', False if the status is 'no_functions_found'
    """
    if status not in ["complete", "no_functions_found"]:
        return (
            "Error: Invalid `status` provided",
            False,
            False,
        )
    else:
        return (
            "Function detection completion acknowledged",
            True,
            status == "complete",
        )
