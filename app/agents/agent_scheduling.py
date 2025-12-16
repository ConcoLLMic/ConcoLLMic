"""
This agent solves path constraints using tools (if necessary) and executes the solution
"""

from copy import deepcopy
from xml.sax.saxutils import unescape

from loguru import logger

from app.agents.common import (
    SCHEDULING_FORMAT_REMINDER,
    ExecutionInformation,
    FunctionCallChain,
    HistoricalInformation,
    Instructions,
    PathConstraint,
    SrcTestCaseId,
    TestCaseId,
    parse_tool_arguments,
)
from app.agents.tools import (
    SelectionTool,
    ThinkingTool,
    process_selection,
    process_thinking_tool,
)
from app.data_structures import MessageThread
from app.model import common
from app.model.common import (
    Usage,
    get_usage_input_part,
    get_usage_output_part,
    init_agent_usage_details,
    update_usage_details,
)

SYSTEM_PROMPT = f"""
You are an expert in concolic execution, a technique that combines concrete execution with symbolic analysis to systematically explore new program paths. Your specific role is to select the most promising test case from a pool of existing test cases to serve as the basis for generating the next test case.

You will be provided with the following information for EACH test case:

1. **Test Case ID**: Enclosed within `<{TestCaseId.__xml_tag__}>` tags, representing the unique identifier for each test case. Higher IDs indicate more recently generated test cases, with the highest ID representing the test case created in the previous round. The test case with ID 0 is the initial test case.

2. **Source Test Case ID (src_id)**: Enclosed within `<{SrcTestCaseId.__xml_tag__}>` tags, representing the ID of the test case that was used as the basis to generate this test case. This shows the lineage of test cases.

3. **Path Constraint**: Enclosed within `<{PathConstraint.__xml_tag__}>` tags, representing the path constraint satisfied by the test case. This constraint was derived through this process: executing the src_id test case, tracing its execution, selecting a interesting branch (along the execution) to explore, and summarizing the constraints needed to reach this branch. This forms the basis for generating this test case.

4. **Execution Information**: Enclosed within `<{ExecutionInformation.__xml_tag__}>` tags, showing how the test case was executed, including program inputs and environment settings. This represents the concrete values obtained by solving the above path constraint.

5. **Function Call Chain**: Enclosed within `<{FunctionCallChain.__xml_tag__}>` tags, representing the function call chain during test execution. Each node follows this format: "{{filename}}[function name (overall line coverage until now)][line coverage by this execution]". The first part shows the source file name, the second part shows the function name with the overall line coverage achieved within that function by ALL existing test cases until now, and the third part shows the line coverage achieved within that function by THIS specific test case's execution.

6. **Historical Information**: Enclosed within `<{HistoricalInformation.__xml_tag__}>` tags, showing how many times this test case has been selected as a basis for generating new test cases and its failure ratio (the percentage of attempts that failed to generate new test cases to explore new program behaviors). This is given using format: "[failed times]/[total selection times](ratio)". A high failure ratio often indicates that the branches selected from this test case tend to be unreachable due to conflicting constraints, path condition limitations, or structural constraints in the code that cannot be satisfied. Test cases with consistently failed attempts may follow execution paths that have few remaining viable unexplored branches.

**Background on Traditional Selection Strategies (ONLY FOR REFERENCE, DO NOT HAVE TO FOLLOW):**
Traditional concolic execution typically selects the most recently generated test case (highest ID) for the next iteration. This depth-first strategy focuses on exploring deeper paths quickly. However, this approach may lead to getting stuck in certain code regions while neglecting others.

**Your Task**: Select the most promising test case as the basis for generating the next test case, using the following selection criteria in order of priority:

1. **Coverage Potential**: Examine the function call chain to identify test cases that executed functions with low overall line coverage. Prioritize test cases that traversed through code regions where significant portions remain unexplored. These test cases are more likely to contain branches that, when negated, will lead to the discovery of new execution paths.

2. **Constraint Analysis**: The union of all path constraints represents the boundaries of explored input space. Analyze these constraints to identify test cases positioned at the edge of unexplored territories. Select test cases whose constraints, when negated or modified, are likely to direct execution into entirely new regions of the input space, potentially revealing new program behaviors.

3. **Historical Information**: Consider the historical failure ratio - test cases with extremely high failure ratios when previously selected are generally less reliable bases for new test generation.

4. **Exploration Balance**: Maintain balance by occasionally selecting less-frequently chosen test cases to prevent excessive focus on a single execution path.

Evaluate each test case against the above criteria before making your final selection. Remember that the goal is to maximize code coverage and explore diverse program behaviors by systematically generating test cases that follow different execution paths.
"""

SCHEDULING_TEMPERATURE = 0.5


class TestCaseScheduler:
    """Test case scheduler for concolic execution"""

    def __init__(self):
        self.already_cached_tc_ids: set[int] = set()

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the scheduler"""
        return unescape(Instructions(instructions=SYSTEM_PROMPT).to_xml().decode())

    def _build_user_prompt(self, provided_tc_info: dict[int, str]) -> str:
        """Build the user prompt for the scheduler"""

        # first, check if we can reuse the cached message thread
        if len(self.already_cached_tc_ids) > 0 and all(
            tc_id in provided_tc_info.keys() for tc_id in self.already_cached_tc_ids
        ):
            logger.debug(
                "Reusing cached message thread for test cases: {}",
                self.already_cached_tc_ids,
            )
            new_tc_info = ""
            new_tc_ids = []
            for tc_id in provided_tc_info:
                if tc_id not in self.already_cached_tc_ids:
                    new_tc_info += provided_tc_info[tc_id] + "\n\n"
                    new_tc_ids.append(tc_id)
            if len(new_tc_ids) > 0:
                logger.debug(
                    f"Adding new test cases ({new_tc_ids}) information for scheduling cache"
                )
                self.already_cached_tc_ids.update(new_tc_ids)
                self.cached_msg_thread.add_user(new_tc_info)
            else:
                logger.debug("No new test cases to add to scheduling cache")
        else:
            logger.debug(
                "Clearing/Initializing scheduling cache, adding test cases: {}",
                provided_tc_info.keys(),
            )
            self.already_cached_tc_ids.clear()
            self.already_cached_tc_ids.update(provided_tc_info.keys())
            self.cached_msg_thread = MessageThread()
            self.cached_msg_thread.add_system(self._build_system_prompt())
            self.cached_msg_thread.add_user(
                unescape(
                    SCHEDULING_FORMAT_REMINDER
                    + "\n\n"
                    + "\n\n".join(provided_tc_info.values())
                )
            )

    def schedule(
        self,
        provided_tc_info: dict[int, str],
    ) -> tuple[int, dict[str, tuple[int, Usage]], MessageThread]:
        """
        Args:
            - provided_tc_info: test case ID -> test case information
        Returns:
            - selected_test_case_id: the ID of the selected test case
            - usage_details: usage details for each tool
            - msg_thread: message thread for debugging
        """
        self._build_user_prompt(provided_tc_info)

        msg_thread = deepcopy(self.cached_msg_thread)

        # print_selection(user_prompt, "Test Case Scheduling")

        selected_test_case_id = None

        # Define available tools
        available_tools = [SelectionTool, ThinkingTool]

        usage_details: dict[str, tuple[int, Usage]] = init_agent_usage_details()
        last_call: list[str] = ["INITIAL"]

        while selected_test_case_id is None:
            # Call model with tools support
            response_content, response_tool_calls, usage = common.SELECTED_MODEL.call(
                msg_thread.to_msg(),
                temperature=SCHEDULING_TEMPERATURE,
                tools=available_tools,
            )

            update_usage_details(usage_details, last_call, get_usage_input_part(usage))
            last_call = []

            logger.info(
                "Scheduling agent response content (being empty is normal when the model calls tools): \n{}",
                response_content,
            )

            # Add model's response to the message thread
            msg_thread.add_model(response_content, response_tool_calls)

            # Check if we have tool calls to process
            if response_tool_calls:

                # Process each tool call
                for tool_call in response_tool_calls:
                    function_name = tool_call.get("function").get("name")
                    tool_call_id = tool_call.get("id")
                    last_call.append(function_name)

                    logger.info(f"Scheduling agent calling tool `{function_name}`")
                    observation = None

                    # Parse arguments
                    args = parse_tool_arguments(tool_call)

                    if args is None:
                        observation = "Failed to parse tool call arguments."
                    else:
                        # Process each type of tool call
                        if function_name == ThinkingTool["function"]["name"]:
                            observation = process_thinking_tool(args.get("reasoning"))

                        elif function_name == SelectionTool["function"]["name"]:
                            observation, test_case_id = process_selection(
                                args.get("test_case_id"),
                                list(provided_tc_info.keys()),
                            )
                            if test_case_id is not None:
                                selected_test_case_id = test_case_id

                    msg_thread.add_tool(
                        observation,
                        name=function_name,
                        tool_call_id=tool_call_id,
                        to_cache=True,
                        clear_pre_cache_role=["tool", "assistant"],
                    )
            else:
                msg_thread.add_user(
                    "Please use the provided tools to achieve the goal.", to_cache=False
                )
                last_call.append("non_tool")

            update_usage_details(usage_details, last_call, get_usage_output_part(usage))

        logger.debug("Scheduling process message thread: {}", msg_thread)

        # Return the solution
        return selected_test_case_id, usage_details, msg_thread
