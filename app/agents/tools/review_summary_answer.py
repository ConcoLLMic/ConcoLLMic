"""
Tool for reviewing the summarizer's output in concolic execution.
"""

from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
from loguru import logger

_REVIEW_SUMMARY_DESCRIPTION = """Use this tool to provide your REVIEW ANSWER to the previous path constraint for the selected target branch.

Your review should:
1. Indicate whether the previous path constraint needs adjustment.
2. When adjustment is NEEDED, provide a complete corrected path constraints for the selected target branch:
    - Create symbolic constraints required to reach the selected target branches
    - Express constraints at the **program input and environment levels**. Avoid intermediate program states
    - Each constraint can be expressed in one of **natural language**, **code snippets**, or **SMT formulas**
    - Ensure constraints are complete - any satisfying input-environment pairs will witness the same concrete execution path
    - Present constraints in chronological execution order
"""


# Define the review summary tool
ReviewSummaryAnswerTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="review_answer",
        description=_REVIEW_SUMMARY_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "need_adjust": {
                    "type": "boolean",
                    "description": "Whether the previous path constraint needs adjustment",
                },
                "corrected_path_constraint": {
                    "type": "string",
                    "description": "If the path constraint generation NEEDS adjustment, provide the corrected complete path constraints. Only required if need_adjust is TRUE.",
                },
            },
            "required": ["need_adjust"],
        },
    ),
)


def process_review_summary_answer(
    need_adjust: bool | None, corrected_path_constraint: str | None = None
) -> tuple[str, bool, bool, str | None]:
    """
    Process the review of the previous path constraint.

    Args:
        need_adjust: Whether the previous path constraint needs adjustment
        corrected_path_constraint: The corrected path constraints if adjustment is needed

    Returns:
        Tuple of (result message, is_valid, need_adjust, corrected_path_constraint or None)
    """
    if not isinstance(need_adjust, bool):
        error_msg = "Error: `need_adjust` is not a boolean. Please provide a valid `need_adjust`."
        logger.warning(error_msg)
        return (
            error_msg,
            False,
            True,
            None,
        )

    if not need_adjust:
        logger.info("Previous path constraint reviewed: NO ADJUSTMENT NEEDED")
        return (
            "NO ADJUSTMENT NEEDED for previous path constraint acknowledged.",
            True,
            False,
            None,
        )

    else:
        if not corrected_path_constraint:
            error_msg = "Error: Corrected path constraint is required when previous path constraint needs adjustment."
            logger.info(
                "LLM returned tool argument error: corrected_path_constraint is required when need_adjust is TRUE"
            )
            return error_msg, False, True, None

        else:
            logger.info(
                "Previous path constraint reviewed: NEEDS ADJUSTMENT, corrected path constraint provided:\n{}",
                corrected_path_constraint,
            )
            return (
                "Path constraint adjustment acknowledged. We will use the corrected path constraint from now on.",
                True,
                True,
                corrected_path_constraint,
            )
