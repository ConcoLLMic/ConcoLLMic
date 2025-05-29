"""
Tool for intermediate reasoning and thinking through complex problems.
"""

from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
from loguru import logger

_THINK_DESCRIPTION = """Use the tool to think through complex problems step by step. This allows you to organize your thoughts before making a decision or getting a final answer. It will not obtain new information or make any changes to the repository, but just log the thought. Use it when complex reasoning or brainstorming is needed.

This is particularly useful for:
1. Analyzing complex execution traces - Organize your thoughts about the program flow and conditions
2. Evaluating multiple potential target branches - Compare different branches and their potential for increasing code coverage
3. Reasoning about symbolic constraints - Work through the logical steps needed to reach a specific branch
4. Breaking down complex path constraints - Decompose constraints into manageable parts

Your reasoning will be recorded but not affect the program state. Think of this as your scratchpad for complex analysis.
"""

ThinkingTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="think",
        description=_THINK_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "reasoning": {
                    "type": "string",
                    "description": "Your step-by-step reasoning process",
                },
            },
            "required": ["reasoning"],
        },
    ),
)


def process_thinking_tool(reasoning: str | None) -> str:
    """
    Process thinking tool by logging the reasoning.

    Args:
        reasoning: The reasoning text from the model

    Returns:
        Confirmation message
    """
    # We do not check for empty reasoning because maybe the reasoning content is in the text part of the response
    # if not reasoning or not reasoning.strip():
    #     logger.warning("`reasoning` is not provided or it is empty.")
    #     return (
    #         "Error: `reasoning` is not provided or it is empty. Please provide a valid `reasoning`.",
    #     )

    logger.info(f"Thinking process: {reasoning}")
    return "I've recorded your reasoning."
