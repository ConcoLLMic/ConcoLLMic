"""
Tool for selecting target branches in concolic execution.
"""

import os

from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
from loguru import logger

from app.agents.common import ExecutionInformation
from app.agents.coverage import Coverage
from app.utils.utils import get_project_dir

_SELECT_TARGET_BRANCH_DESCRIPTION = f"""Use this tool to select a target branch for further exploration in concolic execution. Your primary goal is to improve the overall test coverage of the project. Therefore, you should select branches that are likely to lead to code coverage contribution or complex program behaviors HAVE NOT been covered by existing test cases.


## Core Selection Principle

MOST IMPORTANT: Your goal is to maximize OVERALL code coverage of the project, not just to explore different paths in the current execution. Consider both historical coverage data AND current execution trace as EQUALLY important information sources. A branch not executed in the current trace but with 100% historical coverage is NOT a good target branch.

## Selection Priority

a. Your selection should ensure that the selected target branch can be reached using the existing test harness shown in the <{ExecutionInformation.__xml_tag__}> tags. In this context, "test harness" refers specifically to the target program itself (e.g., `target_program` in a command like `subprocess.run(["target_program", "arg1", "input_file"])`), which is fixed and cannot be modified in subsequent steps. However, you CAN consider branches that can be theoretically reached by manipulating command-line arguments, input files, environment variables, or any other external inputs. Avoid selecting branches that would require modifying internal code of the harness or that are fundamentally unreachable given the current harness.

b. Select branches that would guide program execution along paths different from existing tests. A good target branch selection should consider the following priority order:

    1. Uncovered branches - Prioritize branches with zero historical coverage in the test suite (look for "line cov: 0/X (0%)").

    2. Low coverage branches - If all unexecuted branches have some coverage, focus on branches with low historical coverage ratios, especially those that protect complex logic that may not have been thoroughly tested yet. When selecting such branches, examine:
        - The complexity of logic protected by the branch 
        - The potential for revealing bugs or edge cases
        - The opportunity to exercise unseen program behaviors
    Prioritize the branches that have complex logic and low historical coverage.
You can request to see the code protected by potential target branches to better assess their logic complexity, code coverage, and potential for revealing bugs or edge cases.

c. Prioritize important branches: branches should be selected in order of their potential contribution to code coverage or complex program behaviors, as they are more likely to be processed in the next stage.

### Selection Examples

BAD selection: "This branch, which already has 100% historical coverage, wasn't executed in the current trace, so I'll select it."
GOOD selection: "This branch has 30% historical coverage and contains complex logic, so it has priority over a branch that has 20% historical coverage but simple logic."

## Selection Specification
When specifying your selection: clearly identify the branch condition, including its desired outcome (true/false) and its location (e.g., `if (x > 0)` -> true in `file_name:func_name`)

Your selection should:
- Provide a concise justification for why this branch is important
- Reference HISTORICAL coverage information that informed your decision
- Specify expected_covered_lines as a conservative estimate of guaranteed-to-execute lines. Keep expected_covered_lines as minimal as possible - we ONLY need 2-3 lines that will DEFINITELY execute when the branch is taken. These lines serve as verification markers to confirm the branch was reached during execution.

### Expected Covered_Lines Example
For code like:
```
10| if (target_condition) {{
11|   foo();
12|   if (another_check) {{
13|     bar();
14|   }}
15|   baz();
16| }}
```
Only include line 11-12 in expected_covered_lines, as line 13 depends on another condition and line 15 isn't guaranteed if `bar()` contains an early `exit()`. Do NOT include the branch condition itself (line 10), only include lines WITHIN the branch body.

This expected_covered_lines will be used to verify whether the target branch is successfully reached during subsequent execution, ensuring the system can accurately assess if the generated constraints effectively guide execution flow to reach the specified branch.

## Final Verification
Before finalizing your selection, verify that:
1. There are no LOW/ZERO coverage branches that you've overlooked. If there are, you MUST select one of those instead.
2. You are NOT selecting any branch that is already comprehensively covered by other test cases, even if it wasn't executed in the current trace.
3. You are NOT selecting any branch that is already selected in the current session.

This tool doesn't execute code but records your selection for the constraint generation in the next step.
"""

# Define the target branch selection tool
SelectTargetBranchTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="select_target_branch",
        description=_SELECT_TARGET_BRANCH_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "target_branch": {
                    "type": "string",
                    "description": "The selected branch condition, including its desired outcome (true/false) and its location in the code",
                },
                "justification": {
                    "type": "string",
                    "description": "Detailed explanation of why this branch was selected, including coverage information and potential behaviors",
                },
                "expected_covered_lines": {
                    "type": "object",
                    "description": "A conservative estimate of code lines that are GUARANTEED to execute when the branch is reached. These serve as verification markers.",
                    "properties": {
                        "filepath": {
                            "type": "string",
                            "description": "Relative path to the file",
                        },
                        "lines": {
                            "type": "string",
                            "description": 'Line range in format "start-end" (e.g., "10-11"). Select just 2-3 absolutely guaranteed lines within the branch body. Exclude the branch condition line itself, any conditional/skippable code, and blank lines.',
                        },
                    },
                    "required": ["filepath", "lines"],
                },
            },
            "required": ["target_branch", "justification", "expected_covered_lines"],
        },
    ),
)


def process_target_branch_selection(
    target_branch: str | None,
    justification: str | None,
    expected_covered_lines: tuple[str, str] | None,
) -> tuple[str, bool, tuple[str, tuple[int, int]]]:
    """
    Process target branch selection.

    Args:
        target_branch: The selected target branch
        justification: Justification for the selection
        expected_covered_lines: tuple containing filepath and lines that are expected to be covered

    Returns:
        Tuple of (observation message, is_selected, expected_covered_lines)
    """
    if not target_branch or not target_branch.strip():
        logger.info("`target_branch` is not provided or it is empty.")
        return (
            "Error: `target_branch` is not provided or it is empty. Please provide a valid `target_branch`.",
            False,
            (None, (None, None)),
        )

    if not justification or not justification.strip():
        logger.info("`justification` is not provided or it is empty.")
        return (
            "Error: `justification` is not provided or it is empty. Please provide a valid `justification`.",
            False,
            (None, (None, None)),
        )

    if not expected_covered_lines:
        logger.info("`expected_covered_lines` is not provided or it is empty.")
        return (
            "Error: `expected_covered_lines` is not provided or it is empty. Please provide a valid `expected_covered_lines`.",
            False,
            (None, (None, None)),
        )

    file_path, line_range = expected_covered_lines

    # normally it should be relative to project root
    relative_file_path = os.path.normpath(file_path)

    if get_project_dir() not in relative_file_path:
        file_path_to_check = os.path.normpath(
            os.path.join(get_project_dir(), relative_file_path)
        )
    else:
        # if it already contains project dir, then use it directly but adjust the relative path
        logger.warning(
            f"File path {file_path} already contains project dir {get_project_dir()}, using it directly but adjusting the relative path."
        )  # has potential issue like libsoup/libsoup
        file_path_to_check = relative_file_path
        relative_file_path = os.path.normpath(
            os.path.relpath(file_path_to_check, get_project_dir())
        )

    if not os.path.exists(file_path_to_check):
        logger.info(
            f"LLM Tool Returned Argument Error: File {file_path} ({file_path_to_check}) does not exist."
        )
        return (
            f"Error: File {file_path} does not exist.",
            False,
            (None, (None, None)),
        )
    elif os.path.isdir(file_path_to_check):
        logger.info(
            f"LLM Tool Returned Argument Error: {file_path} ({file_path_to_check}) is a directory."
        )
        return (
            f"Error: {file_path} is a directory.",
            False,
            (None, (None, None)),
        )

    # get line range
    if "-" in line_range:
        if (
            len(line_range.split("-")) != 2
            or not line_range.split("-")[0].isdigit()
            or not line_range.split("-")[1].isdigit()
        ):
            logger.info(
                f"LLM Tool Returned Argument Error: Invalid line range {line_range}."
            )
            return (
                f"Error: Invalid line range {line_range}. Please provide a valid line range in the format of 'start-end', e.g., '10-20'.",
                False,
                (None, (None, None)),
            )

        start, end = line_range.split("-")
        start, end = min(int(start), int(end)), max(int(start), int(end))

    else:
        if not line_range.isdigit():
            logger.info(
                f"LLM Tool Returned Argument Error: Invalid line range {line_range}."
            )
            return (
                f"Error: Invalid line range {line_range}. Please provide a valid line range in the format of 'start-end', e.g., '10-20'.",
                False,
                (None, (None, None)),
            )

        start, end = int(line_range), int(line_range)

    file_line_size = (
        Coverage.get_instance()
        .get_file_coverage(relative_file_path)
        .get_real_line_size()
    )
    if end > file_line_size:
        logger.info(
            f"LLM Tool Returned Argument Error: Line range {line_range} is out of bounds for file {file_path} ({relative_file_path}), which has {file_line_size} lines."
        )
        return (
            f"Error: Line range {line_range} is out of bounds for file {file_path}, which has {file_line_size} lines.",
            False,
            (None, (None, None)),
        )

    logger.info(
        f"Target branch selected: {target_branch}\nJustification: {justification}\nExpected covered lines: {file_path}:{start}-{end}"
    )

    return (
        f'New Target branch successfully selected and recorded. Now please generate path constraints to reach this branch: "{target_branch}".',
        True,
        (relative_file_path, (start, end)),
    )
