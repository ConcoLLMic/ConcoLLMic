"""
Tool for providing the final solution in concolic execution.
"""

from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
from loguru import logger

from app.utils.utils import run_target

_SOLUTION_DESCRIPTION = """Use this tool to provide your REVIEW ANSWER to the previous solution.

Your review should:
1. Indicate whether the previous solution needs adjustment
2. When adjustment is NEEDED, provide a new complete Python function that executes the program with the correct concrete values SATISFYING the constraints.

The Python function must:
- Use the signature `execute_program(timeout: int) -> tuple[str, int]`, which takes a timeout to execute the program and returns its [stderr, return_code] (even after the timeout):
  - stderr: The standard error output of the program under test
  - return_code: The return code of the program under test
- Use the concrete values you've generated that satisfy all constraints to execute the program
- Include all necessary imports and setup and handle all required environment setup and cleanup
- Follow the same basic structure as the original execution, but with your solution values
- Handle execution failures appropriately: raise exceptions for any execution issues.
"""

# Define the solution tool
ReviewSolveAnswerTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="review_answer",
        description=_SOLUTION_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "need_adjust": {
                    "type": "boolean",
                    "description": "Whether the previous solution needs adjustment",
                },
                "new_python_execution": {
                    "type": "string",
                    "description": "If the previous solution NEEDS adjustment, provide a new complete Python function (def execute_program(timeout: int) -> tuple[str, int]) that executes the program with the concrete values. It takes a timeout to execute the program and returns its [stderr, return_code] (even after the timeout). Only required if need_adjust is TRUE.",
                },
            },
            "required": ["need_adjust"],
        },
    ),
)


def process_review_solve_answer(
    need_adjust: bool | None, new_python_execution: str | None = None
) -> tuple[str, bool, str | None]:
    """
    Process the final solution.

    Args:
        need_adjust: Whether the previous solution needs adjustment
        new_python_execution: The new Python function to execute the program

    Returns:
        Tuple of (result message, need_adjust, new_python_execution or None)
    """
    if not isinstance(need_adjust, bool):
        error_msg = "Error: `need_adjust` is not a boolean. Please provide a valid `need_adjust`."
        logger.warning(error_msg)
        return (
            error_msg,
            True,
            None,
        )  # need_adjust set to True but no new solution provided, so we will try again (guaranteed by upper layer)

    if not need_adjust:
        logger.info("Previous solution: NO ADJUSTMENT NEEDED")
        return "NO ADJUSTMENT NEEDED acknowledged.", need_adjust, new_python_execution
    else:
        if not new_python_execution:
            error_msg = "Error: New python execution function is required when previous solution needs adjustment."
            logger.warning(error_msg)
            return error_msg, need_adjust, None

        # Basic validation of the python execution
        if "def execute_program" not in new_python_execution:
            error_msg = "Error: Python execution must contain a 'def execute_program(timeout: int) -> tuple[str, int]' function."
            logger.warning(error_msg)
            return error_msg, need_adjust, None

        # Verify if the Python execution runs successfully using run_target
        result = run_target(
            new_python_execution, timeout=2
        )  # we don't need to wait for the program to finish, just check if the Python execution is successful
        if not result["exec_success"]:
            assert result["exec_error"] is not None
            error_msg = (
                f"Running the given new solution failed, error: {result['exec_error']}"
            )
            logger.warning(error_msg)
            return error_msg, need_adjust, None

        else:
            logger.info("New solution accepted.")
            return "New solution accepted.", need_adjust, new_python_execution
