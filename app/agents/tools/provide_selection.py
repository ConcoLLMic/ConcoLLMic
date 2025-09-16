"""
Tool for providing the final selection in test case scheduling.
"""

from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
from loguru import logger

_SELECTION_DESCRIPTION = """Use this tool to provide your FINAL selection of a test case for further exploration.

You should select the most promising test case based on:
1. Coverage potential - test cases that executed functions with low overall line coverage
2. Constraint analysis - test cases positioned at the edge of unexplored input space
3. Historical information - prefer test cases with lower failure ratios
4. Exploration balance - occasionally select less-frequently chosen test cases

Your selection must specify the ID of the test case you believe will be most effective for generating the next test case.
"""

# Define the selection tool
SelectionTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="provide_selection",
        description=_SELECTION_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "test_case_id": {
                    "type": "integer",
                    "description": "The ID of the test case to select",
                },
            },
            "required": ["test_case_id"],
        },
    ),
)


def process_selection(
    test_case_id: int | None,
    provided_tc_ids: list[int],
) -> tuple[str, int | None]:
    """
    Process the final test case selection.

    Args:
        test_case_id: The ID of the test case to select

    Returns:
        Tuple of (result message, test_case_id)
    """
    if not isinstance(test_case_id, int):
        logger.warning("`test_case_id` is not an integer.")
        return (
            "Error: `test_case_id` is not an integer. Please provide a valid `test_case_id`.",
            None,
        )

    if test_case_id not in provided_tc_ids:
        return (
            f"Error: Test case ID is not in the list of provided test cases. We have provided test case ids: {provided_tc_ids}",
            None,
        )

    logger.info("Test case ID selected: {}", test_case_id)
    return (
        f"Test case ID {test_case_id} selected for further exploration.",
        test_case_id,
    )
