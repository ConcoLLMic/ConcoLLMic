"""
Tool for providing the final solution in concolic execution.
"""

from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
from loguru import logger

from app.utils.utils import run_target

_SOLUTION_DESCRIPTION = """Use this tool to provide your FINAL solution to the path constraint. AVOID using other tools to provide the final solution.

Your solution should:
1. Indicate whether the constraints are satisfiable
2. When satisfiable, provide a complete Python function that executes the program with the concrete values

The Python function must:
- Use the signature `execute_program(timeout: int) -> tuple[str, int]`, which takes a timeout to execute the program and returns its [stderr, return_code] (even after the timeout):
  - stderr: The standard error output of the program under test
  - return_code: The return code of the program under test
  Note: Even if the target program crashes, it is still considered a successful execution and you should return this tuple
- Use the concrete values you've generated that satisfy all constraints to execute the program
- Include all necessary imports and setup and handle all required environment setup and cleanup
- Follow the same basic structure as the original execution, but substitute with your newly derived concrete values. The test harness from the original execution must remain unchanged. Your modifications should be strictly limited to program inputs only, which may include command-line arguments, input files, environment variables, network inputs, or any other external data sources consumed by the test harness.
- Handle execution failures appropriately: raise exceptions for any execution issues (e.g., file access, subprocess setup, resource cleanup)
"""

# Define the solution tool
SolutionTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="provide_solution",
        description=_SOLUTION_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "is_satisfiable": {
                    "type": "boolean",
                    "description": "Whether the path constraints are satisfiable",
                },
                "python_execution": {
                    "type": "string",
                    "description": "The complete Python function (`def execute_program(timeout: int) -> tuple[str, int]`) that uses the concrete values to execute the program. It takes a timeout to execute the program and returns a tuple with the program's [stderr, return code] (even after the timeout). Only required if is_satisfiable is true.",
                },
            },
            "required": ["is_satisfiable"],
        },
    ),
)


def process_solution(
    is_satisfiable: bool | None, python_execution: str | None = None
) -> tuple[str, bool, str | None]:
    """
    Process the final solution.

    Args:
        is_satisfiable: Whether the constraints are satisfiable
        python_execution: The Python function to execute the program, which should return (stderr, return_code) tuple

    Returns:
        Tuple of (result message, is_satisfiable, python_execution or None)

        A valid tuple of (is_satisfiable, python_execution) can only be (1) (False, None) or (2) (True, <python_execution>).
    """
    if not isinstance(is_satisfiable, bool):
        error_msg = "Error: `is_satisfiable` is not a boolean. Please provide a valid `is_satisfiable`."
        logger.warning(error_msg)
        return (
            error_msg,
            True,
            None,
        )  # we return True for is_satisfiable but no python_execution, the upper layer will handle this and retry

    if not is_satisfiable:
        logger.info("Solution provided: UNSATISFIABLE")
        return "UNSATISFIABLE constraints acknowledged.", False, None

    if not python_execution:
        error_msg = "Error: Python execution function is required when constraints are satisfiable."
        logger.warning(error_msg)
        return error_msg, True, None

    # Basic validation of the python execution
    if "def execute_program" not in python_execution:
        error_msg = "Error: Python execution must contain a 'def execute_program(timeout: int) -> tuple[str, int]' function."
        logger.warning(error_msg)
        return error_msg, True, None

    # Verify if the Python execution runs successfully using run_target
    result = run_target(
        python_execution, timeout=2
    )  # we don't need to wait for the program to finish, just check if the Python execution is successful
    if not result["exec_success"]:
        error_msg = f"Running the given solution failed, error: {result['exec_error']}"
        logger.warning(error_msg)
        return error_msg, True, None

    logger.info("Solution provided with `execute_program` function")
    return "Solution accepted.", True, python_execution
