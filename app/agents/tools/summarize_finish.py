from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
from loguru import logger

_FINISH_DESCRIPTION = """Signals the completion of the target branch selection and path constraint generation process.

Use this tool when:
- You have sufficiently explored multiple target branches and generated their path constraints
- You cannot find additional valuable branches to explore based on the current information
- You think the current target branches provide adequate coverage

The task_completed field should be set to True to indicate you've successfully completed the exploration process and are ready to stop.
"""

SummarizeFinishTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="finish",
        description=_FINISH_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "task_completed": {
                    "type": "boolean",
                    "description": "Whether you believe you have successfully completed the branch exploration process",
                },
            },
            "required": ["task_completed"],
        },
    ),
)


def process_summarize_finish(task_completed) -> tuple[str, bool, bool]:
    """
    Process the finish tool call.

    Args:
        task_completed: Whether the task is completed

    Returns:
        Tuple of (observation message, is_valid, task_completed)
    """
    logger.info(f"Finish tool called with task_completed: {task_completed}")

    observation = None
    if task_completed is None:
        logger.warning("`task_completed` is not provided.")
        observation = "Error: `task_completed` is not provided. Please specify whether the task is completed."

    if not isinstance(task_completed, bool):
        logger.warning("`task_completed` is not a boolean.")
        observation = "Error: `task_completed` is not a boolean. Please specify whether the task is completed."

    if observation is not None:
        return observation, False, False

    if not task_completed:
        observation = "Please continue the exploration process."
    else:
        observation = "Finishing the branch exploration process."

    return observation, True, task_completed
