"""
This agent first selects an unexecuted target branch, then summarizes the constraints needed to reach it
"""

from collections.abc import Callable, Generator
from xml.sax.saxutils import unescape

from loguru import logger

from app.agents.common import (
    MAX_CODE_REQUEST_ATTEMPTS,
    AlreadySelectedBranchButNotReached,
    ExampleUserInput,
    ExecutionInformation,
    ExecutionTrace,
    FunctionCallChain,
    Instructions,
    NewExecutionInformation,
    NewExecutionTrace,
    parse_tool_arguments,
    wrap_between_tags,
)
from app.agents.tools import (
    BatchTool,
    CodeRequestTool,
    GeneratePathConstraintTool,
    ReviewSummaryAnswerTool,
    SelectTargetBranchTool,
    SummarizeFinishTool,
    ThinkingTool,
    process_code_request,
    process_path_constraint_generation,
    process_review_summary_answer,
    process_summarize_finish,
    process_target_branch_selection,
    process_thinking_tool,
)
from app.data_structures import MessageThread
from app.log import print_ace, print_summarize
from app.model import common
from app.model.common import (
    Usage,
    get_usage_input_part,
    get_usage_output_part,
    init_agent_usage_details,
    update_usage_details,
)
from app.utils.utils import estimate_text_token

SYSTEM_PROMPT = f"""
You are an expert in concolic execution tasked with analyzing program execution path and generating symbolic constraints. You will receive:

1. Execution Information: Provided in <{ExecutionInformation.__xml_tag__}> tag - Contains details about how the program was executed
2. Execution Trace: Provided in <{ExecutionTrace.__xml_tag__}> tag - Shows the program's execution flow with the following components:
   A. Function Call Chain: Provided in <{FunctionCallChain.__xml_tag__}> tag - Shows the sequence of function calls during execution
      - Format: [file_name](function_name) => [file_name](function_name) => ...
      - This helps you understand the execution flow and dependencies between functions
   B. Source Code Execution:
      - Only actually executed code is shown in the trace
      - Unexecuted code blocks are removed and replaced with comments like "Unexecuted code (lines BEGIN-END) is removed"
      - Executed conditional statements remain visible, even if their corresponding blocks weren't executed. This helps you identify (1) the valuable target branch to explore next, and (2) the corresponding path constraints to reach it
   C. Coverage Information: Provided within above Source Code Execution as comments - Shows coverage information for the code protected by the unexecuted branches
      - Format: "line cov: X/Y (Z%)" means, for that deleted code block (not executed in this execution trace), the test suite has executed X lines out of the total Y lines (excluding blank lines), achieving a coverage ratio of Z%
    - No or low execution counts indicate potential targets for new test cases
4. Already Selected Branch But Not Reached [OPTIONAL]: Provided in <{AlreadySelectedBranchButNotReached.__xml_tag__}> tag - Contains a list of branches previously selected but failed to reach during exploration attempts, which may due to errors in constraint summarization/solving, or the branch is indeed unreachable based on current execution trace. When this information is provided, avoid re-selecting these branches unless you are quite confident that the branch can be reached and you can provide correct and complete constraints to reach it. If all high-priority branches appear here, select the next best alternative instead.

Your task is to analyze the execution flow and generate constraints that lead to multiple new execution paths. You are expected to select several target branches in sequence, generating path constraints for each. Follow this workflow:

1. Target Branch Selection: select a branch, which are not executed in this execution trace, to explore next
    - Your primary goal is to improve the overall test coverage of the project
    - Choose branches that would lead to alternative execution paths and trigger new program behaviors
    - Prioritize important branches: select the most promising branches first
    - Clearly justify your selection with reference to the coverage information
    - Submit your answer with the final `{SelectTargetBranchTool['function']['name']}` tool.

2. Path Constraint Generation: create symbolic constraints required to reach the previously selected target branch
    - Express constraints at the **program input and environment levels**. Avoid intermediate program states
    - Each constraint can be expressed in one of **natural language**, **code snippets**, or **SMT formulas**
    - Ensure constraints are complete - any satisfying input-environment pairs will witness the same concrete execution path
    - Present constraints in chronological execution order
    - The constraints would be passed to another colleague who HAS NEVER SEEN THE CODE. Ensure that:
      * All constraints are SELF-CONTAINED and DO NOT reference internal variables without explanation
      * File format requirements are EXPLICITLY described (exact byte positions, values, and their meanings)
      * Avoid jargon or function names without providing context about what they validate
    - Submit your answer with the final `{GeneratePathConstraintTool['function']['name']}` tool.

3. Repeat or Finish:
   - Return to step 1-2 to select another branch and generate its path constraints if there are more valuable branches to explore
   - Always generate path constraints for your current selected target branch BEFORE selecting a new branch. Only skip this rule if you need to replace/correct your previous branch selection. Basic workflow: select one branch → generate its path constraints → then select another branch
   - Use the `{SummarizeFinishTool['function']['name']}` tool when you've explored all worthwhile branches based on current provided information

Optionally, if you need help, you may invoke the following tools wisely anytime:
   - The `{ThinkingTool['function']['name']}` tool allows you to reason step-by-step about complex problems
   - The `{CodeRequestTool['function']['name']}` tool allows you to see the code protected by branches to better assess their importance if necessary

Important Guidelines:
- You MUST select at least one target branch and generate path constraints for it before finishing
- Maintain a diverse set of target branches to maximize code coverage
- Focus on symbolic analysis rather than concrete execution
- Be precise and unambiguous in constraint specifications
- Keep explanations clear and concise
"""

EXECUTION_INFORMATION_EXAMPLE = """
```python
def execute_program(timeout: int) -> tuple[str, int]:
    import os
    import subprocess
    import tempfile

    # Create a temporary file
    with tempfile.NamedTemporaryFile(mode='w') as temp_file:
        temp_file.write('3 0.5\\n1.1 2.2 3.3')
        temp_file_path = temp_file.name
    
        try:
            result = subprocess.run(['./program', temp_file_path], 
                                    capture_output=True, 
                                    text=True,
                                    timeout=timeout)
            return result.stderr, result.returncode
        except Exception as e:
            raise e
```
"""

EXECUTION_TRACE_EXAMPLE = """
```c
// has_close_elements.c (47 lines total)
bool has_close_elements(vector<float> numbers, float threshold) {
    for (size_t i = 0; i < numbers.size(); i++) {
        for (size_t j = i + 1; j < numbers.size(); j++) {
            if (fabs(numbers[i] - numbers[j]) < threshold) {
                // Unexecuted code (line 5) is removed. Its line cov: 0/1 (0.0%)
            }
        }
    }
    return false;
}

int main(int argc, char *argv[]) {
    if (argc != 2) {
        // Unexecuted code (lines 14-15) is removed. Its line cov: 0/2 (0.0%)
    }

    FILE *file = fopen(argv[1], "r");
    if (!file) {
        // Unexecuted code (lines 20-21) is removed. Its line cov: 0/2 (0.0%)
    }

    int num;
    float threshold;

    if (fscanf(file, "%d %f", &num, &threshold) != 2) {
        // Unexecuted code (lines 28-30) is removed. Its line cov: 0/3 (0.0%)
    }

    vector<float> numbers(num);

    for (int i = 0; i < num; i++) {
        if (fscanf(file, "%f", &numbers[i]) != 1) {
            // Unexecuted code (lines 37-39) is removed. Its line cov: 0/3 (0.0%)
        }
    }
    fclose(file);

    printf(has_close_elements(numbers, threshold) 
           ? "Close elements found.\n" 
           : "No close elements.\n");
}
```
"""

FUNCTION_CALL_CHAIN_EXAMPLE = "[has_close_elements.c](main) => [has_close_elements.c](has_close_elements) => [has_close_elements.c](main)"

EXAMPLE_TARGET_BRANCH = """## Select Target Branch:

Target Branch: `if (fabs(numbers[i] - numbers[j]) < threshold)` -> true in function `has_close_elements()`

Justification: This branch has 0.0% coverage. Although there are multiple uncovered branches, this branch is the core functionality of the program and would significantly improve code coverage when explored.

Expected Covered Lines:
- Filepath: has_close_elements.c
- Lines: 5-5
"""

EXAMPLE_OUTPUT_PATH_CONSTRAINT = """## Path Constraint to reach the target branch:

1. Command-Line Arguments: `argc == 2`
2. File Validity: argv[1] must refer to a valid file that can be successfully opened for reading: `fopen(argv[1], \"r\") != NULL`
3. File Format and Content:
    a. First line must contain valid integer `num` and float `threshold`: `fscanf(file, \"%d %f\", &num, &threshold) == 2`
    b. File must then contain at least `num` valid floats, each successfully parsed into the `numbers` vector: `fscanf(file, \"%f\", &numbers[i]) == 1 for each i in [0, num)`
4. Array Elements Constraint: Must exist two elements in the `numbers` vector that have an absolute difference less than `threshold`: `∃ i, j ∈ [0, num), i < j: fabs(numbers[i] - numbers[j]) < threshold`
"""


# Define review summary user prompt
REVIEW_SUMMARY_USER_PROMPT = f"""
Based on your provided path constraint, another colleague has implemented a solution that correctly satisfies all constraints. However, the target branch still wasn't covered, despite confirming the solver's solution is correct. This indicates the path constraints may not accurately represent the conditions needed to reach the target branch.

To help you analyze this issue, we provide:
1. New execution information: Provided in <{NewExecutionInformation.__xml_tag__}> tag - This is the solution result generated by another colleague based on your provided path constraint
2. New execution trace: Provided in <{NewExecutionTrace.__xml_tag__}> tag - Shows the program's execution flow using the new solution, with the same format as the previous trace (only executed code is shown)

Please carefully analyze the new execution trace and compare it with the previous execution trace to identify where the discrepancy might be:

1. Are there missing constraints that should have been included?
2. Are there incorrect or overly restrictive constraints?
3. Are there constraints that contradict the program's actual behavior?
4. Is there a misunderstanding of the program's control flow?

Your task is to either:
1. Confirm that the path constraints do not need adjustment
2. Indicate that the path constraints need adjustment and provide corrected path constraints that more accurately represent the conditions needed to reach the target branch

Use the `{ReviewSummaryAnswerTool["function"]["name"]}` tool to provide your assessment and any necessary corrections.
"""


CONSTRAINT_SUMMARY_TEMPERATURE = 0.0


def _process_single_tool_call_for_summary(
    function_name: str,
    args: dict,
    state: dict,
) -> str:
    """Processes a single tool call within the summarize function.

    Args:
        function_name: The name of the tool function called.
        args: The parsed arguments for the tool call.
        state: A dictionary holding mutable state like target branches etc.

    Returns:
        The result message from the tool processing.
    """
    observation = f"Error: Unknown tool function {function_name}"

    if function_name == CodeRequestTool["function"]["name"]:
        state["code_request_attempts"] += 1
        # Note: code_request_attempts counter is managed outside this helper
        observation = process_code_request(
            args.get("file_requests"),
            MAX_CODE_REQUEST_ATTEMPTS - state["code_request_attempts"],
        )

    elif function_name == ThinkingTool["function"]["name"]:
        observation = process_thinking_tool(args.get("reasoning"))

    elif function_name == SelectTargetBranchTool["function"]["name"]:
        target_branch = args.get("target_branch")
        justification = args.get("justification")
        expected_cov = args.get("expected_covered_lines")

        if not isinstance(expected_cov, dict):
            logger.warning(
                f"expected_covered_lines is not a dictionary: {expected_cov}"
            )
            observation = "Error: expected_covered_lines should be an object with filepath and lines properties."
        else:
            expected_filepath = expected_cov.get("filepath")
            expected_lines = expected_cov.get("lines")
            observation, is_valid, (filepath, (start, end)) = (
                process_target_branch_selection(
                    target_branch,
                    justification,
                    (expected_filepath, expected_lines),
                )
            )

            if is_valid:
                if (
                    len(state["selected_branches"]) > 0
                    and state["selected_branches"][-1]["path_constraint"] is None
                ):
                    # multiple consecutive branch selection (Just assume LLM wants to correct the previous branch selection)

                    previous_branch = state["selected_branches"][-1]["target_branch"]

                    assert (
                        previous_branch is not None
                    ), "Previous branch should be selected"

                    observation = (
                        f'You have previously selected a target branch ("{previous_branch}") but have not generated path constraints for it yet. You have two options:\n1. If you want to REPLACE your previous branch selection, please continue with this new selection and generate its path constraints.\n2. If you intended to select a DIFFERENT NEW branch, please remember that the expected workflow is: select a branch → generate its path constraints → then select another branch. Now please generate path constraints for your CURRENT selection ("{target_branch}"). Later, you can select branch "{previous_branch}" again if you still think it is valuable.\n\n'
                    ) + observation
                    logger.info(
                        f'Replacing selected branch "{previous_branch}" with "{target_branch}"'
                    )
                else:
                    logger.info(f'Adding an new target branch "{target_branch}"')
                    state["selected_branches"].append(
                        {
                            "target_branch": target_branch,
                            "justification": justification,
                            "expected_covered_filepath": filepath,
                            "expected_covered_lines": (start, end),
                            "path_constraint": None,  # Will be filled later
                        }
                    )

    elif function_name == GeneratePathConstraintTool["function"]["name"]:
        path_constraint = args.get("path_constraint")
        selected_branch = None
        if (
            len(state["selected_branches"]) > 0
            and state["selected_branches"][-1]["target_branch"] is not None
        ):
            selected_branch = state["selected_branches"][-1]["target_branch"]
        observation, is_valid = process_path_constraint_generation(
            path_constraint, selected_branch
        )
        if is_valid:
            if (
                state["selected_branches"][-1]["path_constraint"] is None
            ):  # avoid consecutive path constraint generation (LLM might want to correct the previous path constraint)
                state["finished_branches"] += 1
                logger.info(
                    f'Generated path constraint for branch "{selected_branch}".'
                )
            else:
                logger.info(
                    f'Replacing previous path constraint for branch "{selected_branch}" with a new one.'
                )
                observation = (
                    f'You have already generated path constraints for current target branch ("{selected_branch}"). I\'ll use your newly generated path constraints to replace the previous ones.\n\n'
                ) + observation

            observation += f"Now, you can (1) explore another branch further using the `{SelectTargetBranchTool['function']['name']}` tool, or (2) finish the exploration process using the `{SummarizeFinishTool['function']['name']}` tool if you believe no further branches need exploration."
            state["selected_branches"][-1]["path_constraint"] = path_constraint

    elif function_name == SummarizeFinishTool["function"]["name"]:
        if len(state["selected_branches"]) == 0:
            observation = f"You haven't selected any target branches yet and cannot finish the exploration process. Please select a target branch first using the `{SelectTargetBranchTool['function']['name']}` tool and generate path constraints for it."
        elif state["selected_branches"][-1]["target_branch"] is None:
            assert (
                False
            ), "This should not happen since state['selected_branches'] is not empty"
        elif state["selected_branches"][-1]["path_constraint"] is None:
            observation = f"You haven't generated path constraints for the most recently selected target branch ({state['selected_branches'][-1]['target_branch']}) yet and cannot finish the exploration process. Please generate path constraints for it using the `{GeneratePathConstraintTool['function']['name']}` tool."
        else:
            task_completed = args.get("task_completed")
            observation, is_valid, task_completed = process_summarize_finish(
                task_completed
            )
            if is_valid:
                state["task_completed"] = task_completed
    else:
        observation = f"Error: Unknown tool `{function_name}`"

    return observation


def _process_tool_call(
    response_tool_calls: list[dict],
    state: dict,
    process_single_tool_call_func: Callable,
) -> tuple[list[tuple[str, str, str]], list[str]]:

    batched_observations = []
    called_tools = []

    for tool_call in response_tool_calls:
        function_name = tool_call.get("function").get("name")
        tool_call_id = tool_call.get("id")
        called_tools.append(function_name)

        logger.info(f"Summarizer agent calling tool `{function_name}`")

        # Parse arguments
        args = parse_tool_arguments(tool_call)
        if args is None:
            observation = "Failed to parse tool call arguments."
            batched_observations.append((function_name, tool_call_id, observation))
            continue

        # Handle BatchTool or single tool calls
        if function_name == BatchTool["function"]["name"]:
            invocations = args.get("invocations", [])
            logger.info(f"Processing batch tool with {len(invocations)} invocations.")
            if len(invocations) == 0:
                observation = f'Error: Empty invocations provided in `{BatchTool["function"]["name"]}`.'
            else:
                invocation_observations = []
                for cnt, invocation in enumerate(invocations):
                    inv_func_name = invocation.get("tool_name")
                    if not inv_func_name:
                        logger.warning(f"Missing tool_name in invocation: {invocation}")
                        observation = "Invalid invocation: missing tool_name"
                    else:
                        parsed_args = parse_tool_arguments({"function": invocation})
                        if parsed_args is None:
                            observation = (
                                f"Failed to parse arguments for tool `{inv_func_name}`"
                            )
                        else:
                            observation = process_single_tool_call_func(
                                inv_func_name,
                                parsed_args,
                                state,  # Pass the mutable state
                            )
                    invocation_observations.append((cnt, inv_func_name, observation))

                # Use batch_tool's id and function_name, and join all observations
                observation = (
                    "\n\n".join(
                        f"{cnt+1}. Tool `{inv_func_name}` result:\n{observation}"
                        for cnt, inv_func_name, observation in invocation_observations
                    )
                    if len(invocation_observations) > 0
                    else invocation_observations[0][2]
                )
        else:

            observation = process_single_tool_call_func(
                function_name,
                args,
                state,  # Pass the mutable state
            )

        batched_observations.append((function_name, tool_call_id, observation))

    return batched_observations, called_tools


def summarize(
    execution_information: str,
    execution_trace: str,
    function_call_chain: str,
    already_selected_branch_but_not_reached: list[str] = [],
    parallel_num: int | None = None,
) -> Generator[
    tuple[
        str,
        str,
        tuple[str, tuple[int, int]],
        str,
        dict[str, tuple[int, Usage]],
        MessageThread,
    ]
]:
    """
    Args:
        - execution_information: information about the execution
        - execution_trace: the execution trace
        - function_call_chain: the call chain of functions during execution
        - already_selected_branch_but_not_reached: a list of branches previously selected but failed to reach during exploration attempts
    Yields:
        - target_branch: selected unexecuted branch
        - justification: justification for the target branch selection
        - expected_covered_lines: the lines that are expected to be covered by the target branch
            - filepath: the file path of the expected covered lines
            - lines: the line range of the expected covered lines
        - path_constraint: constraints needed to reach the target branch
        - usage_details: usage details accumulated since last yield
        - msg_thread: current message thread
    """

    msg_thread: MessageThread = MessageThread()
    system_prompt = (
        Instructions(instructions=SYSTEM_PROMPT).to_xml()
        + b"\n"
        + ExampleUserInput(
            example_user_input=wrap_between_tags(
                ExecutionInformation.__xml_tag__, EXECUTION_INFORMATION_EXAMPLE
            )
            + "\n"
            + wrap_between_tags(
                ExecutionTrace.__xml_tag__,
                wrap_between_tags(
                    FunctionCallChain.__xml_tag__, FUNCTION_CALL_CHAIN_EXAMPLE
                )
                + "\n\n"
                + EXECUTION_TRACE_EXAMPLE,
            )
            + "\n"
        ).to_xml()
        + b"\n"
        + f"""# Example of Target Branch Selection and Path Constraint Generation:\n{EXAMPLE_TARGET_BRANCH}\n{EXAMPLE_OUTPUT_PATH_CONSTRAINT}""".encode()
    ).decode()
    system_prompt = unescape(system_prompt)
    msg_thread.add_system(system_prompt)

    avoid_branches_str = ""
    if already_selected_branch_but_not_reached:
        for cnt, branch in enumerate(already_selected_branch_but_not_reached):
            avoid_branches_str += f"Branch {cnt+1}: {branch}\n"

    user_prompt = unescape(
        (
            ExecutionInformation(execution_information=execution_information).to_xml()
            + b"\n"
            + ExecutionTrace(
                execution_trace=wrap_between_tags(
                    FunctionCallChain.__xml_tag__, function_call_chain
                )
                + "\n\n"
                + execution_trace
            ).to_xml()
            + b"\n"
            + (
                (
                    b"\n"
                    + AlreadySelectedBranchButNotReached(
                        already_selected_branch_but_not_reached=avoid_branches_str
                    ).to_xml()
                )
                if avoid_branches_str != ""
                else b""
            )
        ).decode()
    )

    msg_thread.add_user(user_prompt)

    print_ace(user_prompt, "Target Branch Selection and Path Constraint Summarization")

    finished = False

    # State dictionary to pass mutable state to the helper function
    state = {
        "code_request_attempts": 0,  # int
        "selected_branches": [],  # List of selected branches, containing target_branch, justification, expected_covered_filepath, expected_covered_lines, path_constraint
        "finished_branches": 0,  # int
        "task_completed": None,  # Whether the task is completed
        "last_yielded_index": -1,  # Index of the last yielded branch
    }

    usage_details = init_agent_usage_details()

    last_call: list[str] = ["INITIAL"]

    initial_prompt_caching_tokens = None

    input_tokens = 0
    newly_added_tokens = 0

    # Main loop - process tool calls until the finish tool is called
    while not finished:

        available_tools = [
            BatchTool,
            ThinkingTool,
            SelectTargetBranchTool,
            GeneratePathConstraintTool,
            SummarizeFinishTool,
            CodeRequestTool,  # DO NOT use remove way when over-limit due to caching strategy (tool messages are cached before system prompt. Hence, if deleting one tool definition afterwards, it will waste much cached message sections. ref: https://github.com/vercel/ai/issues/3820#issuecomment-2823026455). This can be observed via the HTTP request messages when setting litellm._turn_on_debug()
        ]

        es_tokens = input_tokens + newly_added_tokens
        logger.debug(
            "Estimated tokens: {}, input tokens: {}, newly added tokens: {}",
            es_tokens,
            input_tokens,
            newly_added_tokens,
        )

        if len(state["selected_branches"]) > 0 and (
            es_tokens
            > 188000  # delete code request tool messages after selecting target branch
            # Note: 200k context window includes 8k for output tokens
        ):  # TODO: improve this
            logger.debug(
                "Removing code request tool messages due to token limit, msg_thread before removal: {}",
                msg_thread,
            )
            remove_cnt = msg_thread.remove_tool_messages(
                tool_name=CodeRequestTool["function"]["name"],
            )
            logger.debug(
                "Removed {} code request tool messages",
                remove_cnt,
            )

        if es_tokens > 188000:
            logger.error(
                "Reached the maximum number of tokens, finishing summarization..."
            )
            finished = True
            break

        # Call model with tools support
        response_content, response_tool_calls, usage = common.SELECTED_MODEL.call(
            msg_thread.to_msg(),
            temperature=CONSTRAINT_SUMMARY_TEMPERATURE,
            tools=available_tools,
            tool_choice="any" if available_tools else "auto",
            parallel_tool_calls=True,
        )

        newly_added_tokens = 0
        input_tokens = (
            usage.input_tokens + usage.cache_write_tokens + usage.output_tokens
        )

        if initial_prompt_caching_tokens is None:
            initial_prompt_caching_tokens = usage.cache_write_tokens
        else:
            if usage.cache_read_tokens < initial_prompt_caching_tokens:
                logger.error(
                    "The cache read tokens are less than the initial prompt caching tokens. This should not happen."
                )

        logger.info(
            "Summarizer agent response content (being empty is normal when the model calls tools): \n{}",
            response_content,
        )

        update_usage_details(usage_details, last_call, get_usage_input_part(usage))
        last_call = []

        # Add model's response to the message thread
        msg_thread.add_model(response_content, response_tool_calls)

        # Process response
        if response_tool_calls:

            # Process tool calls
            batched_observations, last_call = _process_tool_call(
                response_tool_calls, state, _process_single_tool_call_for_summary
            )

            # Add all observations to the message thread
            for i, (func_name, call_id, obs) in enumerate(batched_observations):
                msg_thread.add_tool(
                    obs,
                    name=func_name,  # Use the actual tool name here
                    tool_call_id=call_id,
                )

                newly_added_tokens += estimate_text_token(obs)

            if state["task_completed"]:
                assert len(state["selected_branches"]) > 0
                finished = True

        else:
            # No tool calls - prompt model to use tools
            _msg = "Please use the provided tools to achieve the goal."
            msg_thread.add_user(_msg)
            newly_added_tokens += estimate_text_token(_msg)
            last_call = ["non_tool"]

        update_usage_details(usage_details, last_call, get_usage_output_part(usage))

        # Check if we have new complete branches to yield
        for i in range(state["last_yielded_index"] + 1, state["finished_branches"]):
            logger.info(f"Yielding branch {i+1}")
            branch = state["selected_branches"][i]

            assert (
                branch["path_constraint"] is not None
                and branch["target_branch"] is not None
            ), "Finished branch should have a path constraint and target branch"

            # Create a copy of the current usage_details to yield
            yield_usage_details = {k: v for k, v in usage_details.items()}

            # Reset accumulated usage for next yield
            usage_details = init_agent_usage_details()

            state["last_yielded_index"] = i

            yield (
                branch["target_branch"],
                branch["justification"],
                (
                    branch["expected_covered_filepath"],
                    branch["expected_covered_lines"],
                ),
                branch["path_constraint"],
                yield_usage_details,
                msg_thread.copy(),
            )

        if parallel_num is not None:
            if state["last_yielded_index"] + 1 >= parallel_num:
                logger.info(
                    f"Reached the maximum number ({parallel_num}) of branches to explore, finishing summarization..."
                )
                finished = True

    # Create a summary of all branches explored
    final_output = "\nEXPLORATION SUMMARY:\n"
    for i, branch in enumerate(state["selected_branches"]):
        final_output += f"\n--- Branch {i+1} ---\n"
        final_output += f"TARGET BRANCH:\n{branch['target_branch']}\n\n"
        final_output += f"JUSTIFICATION:\n{branch['justification']}\n\n"
        final_output += f"EXPECTED COVERED LINES:\n{branch['expected_covered_filepath']}:{branch['expected_covered_lines'][0]}-{branch['expected_covered_lines'][1]}\n\n"
        final_output += f"PATH CONSTRAINT:\n{branch['path_constraint']}\n"

    print_summarize(final_output, "Target Branch Selection and Path Constraint Results")

    logger.debug(
        "Calling model for target branch selection and path constraint summarization. Completed message thread: {}",
        msg_thread,
    )

    logger.debug(
        "Target branch selection and path constraint summary completed. Result: \n{}",
        final_output,
    )


# Define helper for review_summary tool processing
def _process_single_tool_call_for_review(
    function_name: str,
    args: dict,
    state: dict,
) -> str:
    """Processes a single tool call within the review_summary function.

    Args:
        function_name: The name of the tool function called.
        args: The parsed arguments for the tool call.
        state: A dictionary holding mutable state like need_adjust, corrected_path_constraint, code_request_attempts.

    Returns:
        The result message from the tool processing.
    """
    observation = f"Error: Unknown tool function {function_name}"

    if function_name == CodeRequestTool["function"]["name"]:
        state["code_request_attempts"] += 1
        # Note: code_request_attempts counter is managed outside this helper
        observation = process_code_request(
            args.get("file_requests"),
            MAX_CODE_REQUEST_ATTEMPTS - state["code_request_attempts"],
        )

    elif function_name == ThinkingTool["function"]["name"]:
        observation = process_thinking_tool(args.get("reasoning"))

    elif function_name == ReviewSummaryAnswerTool["function"]["name"]:
        current_need_adjust = args.get("need_adjust")
        current_corrected_path = (
            args.get("corrected_path_constraint") if current_need_adjust else None
        )

        (
            observation,
            is_valid,
            need_adjust,
            corrected_path_constraint,
        ) = process_review_summary_answer(
            current_need_adjust,
            current_corrected_path,
        )
        assert need_adjust == (
            current_need_adjust if current_need_adjust is not None else True
        )
        if is_valid:
            state["need_adjust"] = need_adjust
            state["corrected_path_constraint"] = corrected_path_constraint
    else:
        observation = f"Error: Unknown tool `{function_name}`"

    return observation


def review_summary(
    msg_thread: MessageThread, new_execution_information: str, new_execution_trace: str
) -> tuple[bool, str | None, dict[str, tuple[int, Usage]], MessageThread]:
    """
    Review the summary (target branch selection and path constraint generation)

    Args:
        msg_thread: Message thread for the conversation
        new_execution_information: New execution information after solving
        new_execution_trace: New execution trace after solving
    Returns:
        need_adjust: whether the path constraint needs adjustment
        corrected_path_constraint: corrected path constraint if adjustment is needed
        usage_details: usage details for each tool
        msg_thread: message thread for debugging
    """

    user_prompt = unescape(
        (
            Instructions(instructions=REVIEW_SUMMARY_USER_PROMPT).to_xml()
            + b"\n"
            + NewExecutionInformation(
                new_execution_information=new_execution_information
            ).to_xml()
            + b"\n"
            + NewExecutionTrace(new_execution_trace=new_execution_trace).to_xml()
        ).decode()
    )

    msg_thread.add_user(user_prompt)

    print_ace(user_prompt, "Review Summary")

    finished = False
    # State dictionary with initial values
    state = {
        "need_adjust": None,  # bool | None
        "corrected_path_constraint": None,  # str | None
        "code_request_attempts": 0,  # int
    }

    usage_details = init_agent_usage_details()

    last_call: list[str] = ["INITIAL"]

    while not finished:
        available_tools = [
            BatchTool,
            ThinkingTool,
            ReviewSummaryAnswerTool,
            CodeRequestTool,  # DO NOT use remove way when over-limit due to caching strategy
        ]

        # Call model with tools support
        response_content, response_tool_calls, usage = common.SELECTED_MODEL.call(
            msg_thread.to_msg(),
            temperature=CONSTRAINT_SUMMARY_TEMPERATURE,
            tools=available_tools,
            tool_choice="any" if available_tools else "auto",
            parallel_tool_calls=True,
        )
        update_usage_details(usage_details, last_call, get_usage_input_part(usage))
        last_call = []

        logger.debug("Review summary call response: \n{}", response_content)

        # Add model's response to the message thread
        msg_thread.add_model(response_content, response_tool_calls)

        # Check if we have tool calls to process
        if response_tool_calls:
            # Process tool calls
            batched_observations, last_call = _process_tool_call(
                response_tool_calls, state, _process_single_tool_call_for_review
            )

            # Add all observations to the message thread
            for i, (func_name, call_id, obs) in enumerate(batched_observations):
                msg_thread.add_tool(
                    obs,
                    name=func_name,
                    tool_call_id=call_id,
                )

            if state["need_adjust"] is not None:
                finished = True
        else:
            msg_thread.add_user("Please use the provided tools to achieve the goal.")
            last_call = ["non_tool"]

        update_usage_details(usage_details, last_call, get_usage_output_part(usage))

    logger.debug("Review summary message thread: {}", msg_thread)
    print_summarize(
        f"Previous path constraint needs adjustment: {state['need_adjust']}\n\n"
        + (
            f"Corrected path constraint: ```\n{state['corrected_path_constraint']}\n```\n\n"
            if state["need_adjust"]
            else ""
        ),
        "Review Summary Result",
    )

    # Return the results
    assert state["need_adjust"] is not None
    return (
        state["need_adjust"],
        state["corrected_path_constraint"],
        usage_details,
        msg_thread,
    )
