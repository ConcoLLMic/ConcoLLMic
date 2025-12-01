"""
Concolic execution command for ACE.
"""

import atexit
import concurrent.futures
import os
import random
import re
import sys
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from enum import Enum

from loguru import logger

from app.agents.agent_scheduling import TestCaseScheduler
from app.agents.agent_solver import review_solve, solve
from app.agents.agent_summarizer import review_summary, summarize
from app.agents.common import (
    FILE_TRACE_PATTERN,
    TRACE_PATTERN,
    filter_instr_print,
    set_concolic_execution_state,
)
from app.agents.coverage import Coverage
from app.agents.states import ConcolicExecutionState, TestcaseState
from app.agents.testcase import TestCase, TestCaseManager
from app.agents.trace import trace_compress
from app.data_structures import MessageThread
from app.model.common import Usage
from app.utils.utils import (
    compress_repeating_sequences,
    format_code,
    run_target,
    update_ce_start_time,
    update_project_dir,
)


def split_trace_by_file(trace_str: str) -> dict[str, str]:
    """Split execution trace by file name.

    Parses the execution trace string, filters out instrumentation output, and groups them by source file.

    Args:
        trace_str (str): Execution trace string

    Returns:
        dict: Dictionary with file names as keys and corresponding trace information as values
    """
    # Regular expression to search "[filename] enter/exit function_name basic_block_id"
    # Note: OTHER content (the content that is not instrumentation output) would be detected

    # Create a default dictionary to store trace information grouped by file name
    file_traces = defaultdict(list)

    # Split trace information by line
    for line in trace_str.strip().split("\n"):
        if not line.strip():
            continue

        matches = re.findall(FILE_TRACE_PATTERN, line.strip())
        if len(matches) == 0:
            continue

        for match in matches:
            file_path, action, func_name, block_id = match
            assert f"[{file_path}] {action} {func_name} {block_id}" in line
            assert (
                re.search(TRACE_PATTERN, f"{action} {func_name} {block_id}") is not None
            )
            file_traces[file_path].append(
                f"[{file_path}] {action} {func_name} {block_id}"
            )

    # Convert lists to strings
    return {
        os.path.normpath(file_path): "\n".join(traces)
        for file_path, traces in file_traces.items()
    }


def _format_exec_code(exec_code: str) -> str:
    """Format execution code.

    Args:
        exec_code (str): Execution code
    """
    exec_code_dict = {
        line_no: code for line_no, code in enumerate(exec_code.split("\n"), start=1)
    }
    return format_code(exec_code_dict, "python", numbered=False, qouted=True)


def _get_file_lines(
    file_path: str | None, line_range: tuple[int, int] | tuple[None, None]
) -> str:
    """Get the content of the file lines.

    Args:
        file_path (str): File path
        line_range (tuple): Line range
    """
    if file_path is None or line_range == (None, None):
        return None

    coverage = Coverage.get_instance()
    _contents = []
    for real_line in range(line_range[0], line_range[1] + 1):
        _contents.append(
            coverage.get_file_coverage(file_path).get_real_line_content(real_line)
        )
    return "\n".join(_contents)


def _collect_trace_and_check_coverage(
    execution_trace: str | None,
    target_file_lines: tuple[str, tuple[int, int]] | tuple[None, tuple[None, None]],
    add_coverage: bool = True,
) -> tuple[int, bool, str]:
    """Collect trace and check coverage.

    Args:
        execution_trace (str): Execution trace
        target_file_lines (tuple): Target file lines
        add_coverage (bool): Whether to add coverage information
    Returns:
        tuple: Tuple of (new_covered_lines, is_target_lines_covered, execution_summary)
    """
    if execution_trace is None or execution_trace == "":
        return 0, False, ""

    coverage = Coverage.get_instance()
    file_traces = split_trace_by_file(execution_trace)
    is_target_lines_covered = False if target_file_lines[0] is not None else True
    new_covered_lines = 0
    execution_summary = ""
    for relative_file_path, trace in file_traces.items():
        relative_file_path = os.path.normpath(relative_file_path)

        # Collect trace and check target coverage
        file_new_covered_lines, file_target_lines_covered, file_execution_summary = (
            coverage.collect_trace(
                relative_file_path,
                trace,
                target_lines=(
                    target_file_lines[1]
                    if target_file_lines[0] is not None
                    and relative_file_path == os.path.normpath(target_file_lines[0])
                    else (None, None)
                ),
                add_coverage=add_coverage,
            )
        )

        if target_file_lines[0] is not None and relative_file_path == os.path.normpath(
            target_file_lines[0]
        ):
            is_target_lines_covered = file_target_lines_covered

        new_covered_lines += file_new_covered_lines
        execution_summary += file_execution_summary + "\n"

    return new_covered_lines, is_target_lines_covered, execution_summary


class TestCaseSelection(Enum):
    LLM = "llm"
    RANDOM = "random"
    DFS = "dfs"


def solve_and_execute(
    tc: TestCase,
    summarize_msg_thread: MessageThread,
    exec_timeout: int,
    disable_review: bool = True,
):
    # process single test case, including solve and execute
    try:
        tc.add_state(TestcaseState.SOLVE)
        tc.save_to_disk()
        solver_msg_thread = None

        while tc.current_state != TestcaseState.FINISHED:

            usage_details = {"TOTAL": Usage()}

            if disable_review:
                assert not str(tc.current_state).startswith("REVIEW")

            if (
                tc.current_state == TestcaseState.SOLVE
                or tc.current_state == TestcaseState.REVIEW_SUMMARY_SOLVE
            ):
                # Solve constraints to generate new inputs
                if tc.current_state == TestcaseState.SOLVE:
                    logger.info(
                        "TestCase #{}: Solving path constraint...",
                        tc.id,
                    )
                else:
                    logger.info(
                        "TestCase #{}: Solving constraints after reviewing summarizer...",
                        tc.id,
                    )

                (
                    tc.is_satisfiable,
                    tc.exec_code,
                    usage_details,
                    msg_thread,
                ) = solve(
                    _format_exec_code(tc.src_exec_code),
                    tc.target_path_constraint,
                )

                solver_msg_thread = msg_thread.copy()

                if tc.is_satisfiable:
                    logger.info("Constraints were satisfiable.")
                    # Constraints were satisfiable, use the new execution
                    if tc.current_state == TestcaseState.SOLVE:
                        next_state = TestcaseState.EXECUTE
                    elif tc.current_state == TestcaseState.REVIEW_SUMMARY_SOLVE:
                        next_state = TestcaseState.REVIEW_SUMMARY_EXECUTE
                else:
                    # Constraints were unsatisfiable, finish the test case
                    next_state = TestcaseState.FINISHED

            elif tc.current_state == TestcaseState.REVIEW_SOLVER:
                # Review solver's solution
                logger.info("TestCase #{}: Reviewing solver's solution...", tc.id)

                need_adjust, corrected_execution, usage_details, msg_thread = (
                    review_solve(solver_msg_thread)
                )

                if need_adjust:
                    assert corrected_execution is not None
                    # Solver solution was incorrect and has been corrected
                    logger.info(
                        "TestCase #{}: Solver solution was incorrect. Will try corrected solution.",
                        tc.id,
                    )
                    tc.exec_code = corrected_execution
                    next_state = TestcaseState.REVIEW_SOLVER_EXECUTE
                else:
                    # Solver was correct, problem must be in summarizer
                    logger.info(
                        "TestCase #{}: Solver solution was correct. Problem is in summarizer's constraints.",
                        tc.id,
                    )
                    next_state = TestcaseState.REVIEW_SUMMARY

            elif tc.current_state == TestcaseState.REVIEW_SUMMARY:
                logger.info(
                    "TestCase #{}: Reviewing previous path constraint...", tc.id
                )

                (
                    is_summarizer_correct,
                    corrected_path_constraint,
                    usage_details,
                    msg_thread,
                ) = review_summary(
                    summarize_msg_thread,
                    _format_exec_code(tc.exec_code),
                    tc.execution_summary,
                )

                if not is_summarizer_correct:
                    # Summarizer was incorrect, apply corrections
                    logger.info(
                        "TestCase #{}: Previous path constraint was incorrect. Will try with corrected information.",
                        tc.id,
                    )
                    tc.target_path_constraint = corrected_path_constraint

                    next_state = TestcaseState.REVIEW_SUMMARY_SOLVE
                else:
                    # Summarizer was correct, but something else is wrong
                    # This is a fallback case - ideally we should never get here
                    logger.warning(
                        "TestCase #{}: Both summarizer and solver were correct, but target is still not covered.",
                        tc.id,
                    )
                    next_state = TestcaseState.FINISHED

            elif (
                tc.current_state == TestcaseState.EXECUTE
                or tc.current_state == TestcaseState.REVIEW_SOLVER_EXECUTE
                or tc.current_state == TestcaseState.REVIEW_SUMMARY_EXECUTE
            ):
                # Execute the test case and collect trace
                result = run_target(tc.exec_code, timeout=exec_timeout)

                if not result["exec_success"]:
                    raise Exception(
                        "TestCase #{}: The python execution should be successful, as guaranteed by previous state. However, the execution failed: {}",
                        tc.id,
                        (result["exec_error"]),
                    )

                tc.execution_trace = result["target_stderr"]
                tc.returncode = result["target_return_code"]

                if result["target_timeout"]:
                    tc.is_hang = True
                    logger.warning(
                        "Test case #{} timed out, exec code:\n{}",
                        tc.id,
                        tc.exec_code,
                    )

                if result["target_crashed"]:
                    tc.is_crash = True
                    tc.crash_info = f"Crash reason: {result['target_crash_reason']}\nStderr:\n{filter_instr_print(result['target_stderr'])}"

                    logger.warning(
                        "Test case #{} crashed, crash info:\n{}",
                        tc.id,
                        tc.crash_info,
                    )
                    logger.debug(
                        "Code of crashed test case #{}:\n{}",
                        tc.id,
                        tc.exec_code,
                    )

                # Process execution trace and check coverage
                assert tc.target_file_lines[0] is not None
                (
                    tc.newly_covered_lines,
                    tc.is_target_covered,
                    tc.execution_summary,
                ) = _collect_trace_and_check_coverage(
                    tc.execution_trace,
                    tc.target_file_lines,
                )
                tc.new_coverage = True if tc.newly_covered_lines > 0 else False

                logger.info(
                    "TestCase #{}: Target lines ({}) covered: {}. Newly covered code lines: {}",
                    tc.id,
                    tc.target_file_lines,
                    tc.is_target_covered,
                    tc.newly_covered_lines,
                )

                # Determine next state
                if tc.is_valuable() or tc.is_crash_or_hang():
                    next_state = TestcaseState.FINISHED
                else:
                    logger.info(
                        "TestCase #{}: Target lines are not covered and code coverage is also not improved.",
                        tc.id,
                    )
                    if tc.current_state == TestcaseState.EXECUTE:
                        if disable_review:
                            next_state = TestcaseState.FINISHED
                        else:
                            logger.info(
                                "TestCase #{}: We need to first review the solver's solution.",
                                tc.id,
                            )
                            next_state = TestcaseState.REVIEW_SOLVER
                    elif tc.current_state == TestcaseState.REVIEW_SOLVER_EXECUTE:
                        logger.info(
                            "TestCase #{}: We need to then review the summarizer's constraints.",
                            tc.id,
                        )
                        next_state = TestcaseState.REVIEW_SUMMARY
                    elif tc.current_state == TestcaseState.REVIEW_SUMMARY_EXECUTE:
                        logger.info(
                            "TestCase #{}: All reviews are done, but still not covered.",
                            tc.id,
                        )
                        next_state = TestcaseState.FINISHED

            tc.add_usage(usage_details)
            tc.add_state(next_state)
            # Explicitly save the test case
            tc.save_to_disk()
    except Exception as e:
        logger.error(f"TestCase #{tc.id}: Exception during solve_and_execute: {e}")
        # Ensure the exception is propagated up
        raise


class TaskExecutor:
    """Class to manage concurrent task execution using a thread pool."""

    def __init__(self, max_workers=10):
        """Initialize the task executor with a thread pool.

        Args:
            max_workers (int): Maximum number of concurrent workers in the thread pool
        """
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.submitted_futures = (
            {}
        )  # Map future to testcase id for better status reporting
        self.futures_lock = threading.Lock()

        # Register cleanup method to be called at program exit
        atexit.register(self.cleanup)

    def cleanup(self):
        """Clean up thread pool resources"""
        logger.debug("Shutting down thread pool executor...")
        self.executor.shutdown(wait=True)
        logger.debug("Thread pool executor has been shut down.")

    def submit_task(self, func: Callable, tc: TestCase, kwargs: dict):
        """Submit a test case to the thread pool for processing

        Args:
            tc (TestCase): The test case to process
            msg_thread (MessageThread): Message thread for the test case
            timeout (int): Execution timeout in seconds

        Returns:
            Future: The future representing the submitted task
        """
        logger.info(f"Submitting TestCase #{tc.id} to thread pool")

        future = self.executor.submit(func, tc, **kwargs)

        with self.futures_lock:
            self.submitted_futures[future] = tc.id

        logger.debug(f"TestCase #{tc.id} successfully submitted")
        return future

    def wait_for_all_tasks(self):
        """Wait for all submitted tasks to complete"""
        with self.futures_lock:
            if not self.submitted_futures:
                logger.info("No tasks to wait for")
                return

            # Create a copy of the mapping to work with
            futures_map = self.submitted_futures.copy()
            self.submitted_futures.clear()

        total_tasks = len(futures_map)
        completed_tasks = 0

        logger.info(
            f"Waiting for {total_tasks} test cases to complete: {list(futures_map.values())}"
        )

        # Process futures as they complete
        for future in concurrent.futures.as_completed(futures_map.keys()):
            tc_id = futures_map[future]
            completed_tasks += 1

            try:
                # Get the result, which will raise any exception that occurred
                future.result()
                logger.info(
                    f"TestCase #{tc_id} completed successfully ({completed_tasks}/{total_tasks})"
                )
            except Exception as e:
                logger.error(f"Exception in TestCase #{tc_id}: {e}")
                # Re-raise the exception
                raise


def run_concolic_execution(
    project_dir,
    out_dir,
    timeout,  # seconds
    test_selection: TestCaseSelection,
    initial_execution_file=None,
    rounds=None,
    resume_in=None,
    plateau_slot=None,
    parallel_num=5,
):
    """Run concolic execution phase using a state machine approach.

    Testcase states:
    - SUMMARIZE: Analyze execution paths and generate constraints
    - SOLVE: Solve constraints to generate new inputs
    - EXECUTE: Execute the NEW test case, collect traces, and check if target lines are covered
    - REVIEW_SOLVER: Review solver solution when target lines aren't covered
    - REVIEW_SOLVER_EXECUTE: Execute corrected solver solution
    - REVIEW_SUMMARY: Problem in summarizer, try a different branch
    - REVIEW_SUMMARY_SOLVE: Solve the new constraints after reviewing summarizer
    - REVIEW_SUMMARY_EXECUTE: Execute after reviewing summarizer and solve the new constraints
    - FINISHED: Finished
    """

    if not initial_execution_file and not resume_in:
        logger.error("Either initial_execution_file or resume_in must be provided")
        sys.exit(1)

    if initial_execution_file and resume_in:
        logger.error(
            "Only one of initial_execution_file or resume_in should be provided"
        )
        sys.exit(1)

    logger.info(
        "Starting concolic execution phase, using testcase selection strategy: {}, parallel_num: {}, plateau_slot: {}, rounds: {}...",
        str(test_selection),
        parallel_num,
        f"{plateau_slot} minutes" if plateau_slot else "None",
        f"{rounds}" if rounds else "None",
    )
    update_project_dir(project_dir)

    # Initialize TestCaseManager
    crash_cnt = 0
    hang_cnt = 0

    testcase_manager: TestCaseManager = TestCaseManager(out_dir)

    # Initialize task executor for concurrent processing
    task_executor = TaskExecutor(max_workers=parallel_num)

    time_bias = 0

    if initial_execution_file:
        # Initialize execution variables
        exec_code = open(initial_execution_file).read()
        result = run_target(exec_code, timeout=timeout)

        if not result["exec_success"]:
            logger.error("Initial test case execution failed: {}", result["exec_error"])
            sys.exit(1)

        if result["target_timeout"]:
            logger.error(
                "Initial test case execution timed out. Please increase the timeout limit (current timeout: {} seconds).".format(
                    timeout
                )
            )
            sys.exit(1)

        # Collect initial execution trace
        execution_trace = result["target_stderr"]

        new_covered_lines, is_target_lines_covered, execution_summary = (
            _collect_trace_and_check_coverage(execution_trace, (None, (None, None)))
        )

        if new_covered_lines == 0:
            logger.error(
                "Initial test case execution did not cover any new lines, please check"
            )
            sys.exit(1)

        assert is_target_lines_covered

        # Create initial test case
        testcase_manager.add_initial_testcase(
            exec_code, execution_trace, execution_summary, new_covered_lines
        )
    else:

        testcase_manager.load_testcases(resume_in)
        testcase_manager.save_all_testcases()  # "crashes_or_hangs" directory will also be synchronized

        # First, ensure the testcase is runable, using the first (initial) testcase as an example
        result = run_target(testcase_manager.get_testcase(0).exec_code, timeout=timeout)

        if not result["exec_success"]:
            logger.error("Initial test case execution failed: {}", result["exec_error"])
            sys.exit(1)

        if result["target_timeout"]:
            logger.error(
                "Initial test case execution timed out. Please increase the timeout limit (current timeout: {} seconds).".format(
                    timeout
                )
            )
            sys.exit(1)

        if result["target_stderr"] != testcase_manager.get_testcase(0).execution_trace:
            logger.error(
                "The execution trace of the initial testcase has changed. There may be some issues with the execution environment. New execution trace:\n{}",
                result["target_stderr"],
            )
            sys.exit(1)

        # Then, using the execution trace of each testcase to replay the "coverage"
        for id, testcase in testcase_manager.test_cases.items():
            if testcase is None:
                logger.warning(
                    f"Test case #{id} not found, skipping coverage replay..."
                )
            elif testcase.execution_trace is not None:
                _collect_trace_and_check_coverage(
                    testcase.execution_trace, (None, (None, None))
                )

        time_bias = testcase_manager.get_max_time_taken()
        crash_cnt, hang_cnt = testcase_manager.get_crash_and_hang_count()

        logger.info(
            "Have loaded {} test cases, with time bias {} seconds, original crashes: {}, hangs: {}.",
            testcase_manager.next_testcase_id,
            time_bias,
            crash_cnt,
            hang_cnt,
        )

    update_ce_start_time(time.time() - time_bias)
    last_new_coverage_time = time.time() - time_bias

    under_gen_tc_msg_thread: dict[int, MessageThread] = (
        {}
    )  # if one testcase is finished, it should be removed

    under_gen_tcs: list[TestCase] = []

    round_cnt = 1
    cur_ce_state = ConcolicExecutionState.SELECT

    if test_selection == TestCaseSelection.DFS:
        priority_queue = deque()
        priority_queue.append(0)
        last_added_max_id = 0
    elif test_selection == TestCaseSelection.LLM:
        scheduler = TestCaseScheduler()

    while round_cnt <= (rounds or float("inf")):
        logger.info(
            "====== Iteration {}: Current state: {} ======",
            round_cnt,
            str(cur_ce_state),
        )
        set_concolic_execution_state(cur_ce_state)
        match cur_ce_state:
            case ConcolicExecutionState.SELECT:
                selection_usage_details = {"TOTAL": Usage()}
                # select a test case
                if test_selection == TestCaseSelection.LLM:
                    provided_tc_info: dict[int, str] = (
                        testcase_manager.get_all_scheduling_information()
                    )
                    logger.info(
                        f"Selecting test case using LLM STRATEGY from list: {list(provided_tc_info.keys())}"
                    )
                    if len(list(provided_tc_info.keys())) == 0:
                        raise Exception("No test cases are available for scheduling.")
                    elif len(list(provided_tc_info.keys())) == 1:
                        selected_testcase_id = list(provided_tc_info.keys())[0]
                        if testcase_manager.next_testcase_id != 1:
                            raise Exception(
                                "Only one test case is selected to be scheduled."
                            )
                    else:
                        selected_testcase_id, selection_usage_details, msg_thread = (
                            scheduler.schedule(provided_tc_info)
                        )

                elif test_selection == TestCaseSelection.RANDOM:
                    valuable_tc_ids = [
                        tc_id
                        for tc_id, tc in testcase_manager.test_cases.items()
                        if tc is not None and tc.is_valuable()
                    ]
                    assert len(valuable_tc_ids) > 0
                    selected_testcase_id = random.choice(valuable_tc_ids)
                    logger.info(
                        f"Selecting test case using RANDOM STRATEGY from list: {valuable_tc_ids}"
                    )

                elif test_selection == TestCaseSelection.DFS:
                    for tc_id in range(
                        last_added_max_id + 1, testcase_manager.next_testcase_id
                    ):
                        tc = testcase_manager.get_testcase(tc_id)
                        if tc is not None and tc.is_valuable():
                            priority_queue.append(tc_id)
                    last_added_max_id = testcase_manager.next_testcase_id - 1

                    logger.info(
                        f"Selecting test case using DFS from list: {priority_queue if len(priority_queue) > 0 else 'empty (will use the first testcase)'}"
                    )
                    if len(priority_queue) > 0:
                        selected_testcase_id = priority_queue.pop()
                    else:
                        # start again?
                        selected_testcase_id = 0

                src_testcase = testcase_manager.get_testcase(selected_testcase_id)

                logger.info(
                    "Using test case #{} as the base test case.", src_testcase.id
                )

                # Refresh execution summary but DO NOT update the original execution summary of the testcase (used as backup)
                _, _, latest_src_exec_summary = _collect_trace_and_check_coverage(
                    src_testcase.execution_trace,
                    (None, (None, None)),
                    add_coverage=False,
                )

                # state transition
                cur_ce_state = ConcolicExecutionState.SUMMARIZE
            case ConcolicExecutionState.SUMMARIZE:
                # summarize the test case
                branches_yielded_cnt = 0

                func_call_chain_list = [
                    (file, func)
                    for file, func, _ in trace_compress(src_testcase.execution_trace)
                ]

                # compress the repeating sequences
                compressed_func_call_chain_list = compress_repeating_sequences(
                    func_call_chain_list
                )

                formatted_func_call_chain_list = []
                for item_count_pair in compressed_func_call_chain_list:
                    item, count = item_count_pair
                    if isinstance(item, tuple):
                        file_name, func_name = item
                        formatted_func_call_chain_list.append(
                            f"[{file_name}]({func_name}){f'*{count}' if count > 1 else ''}"
                        )
                    elif isinstance(item, list):
                        assert len(item) >= 2
                        assert count > 1
                        combined_file_func_list = []
                        for file_name, func_name in item:
                            combined_file_func_list.append(
                                f"[{file_name}]({func_name})"
                            )
                        formatted_func_call_chain_list.append(
                            f"[{'=>'.join(combined_file_func_list)}]*{count}"
                        )
                    else:
                        raise Exception(
                            f"Unexpected item format in compressed_func_call_chain_list: {item}"
                        )

                if len(formatted_func_call_chain_list) > 500:
                    formatted_func_call_chain_list = formatted_func_call_chain_list[
                        :500
                    ] + ["...(truncated)"]

                function_call_chain = " => ".join(formatted_func_call_chain_list)

                # Get generator and process generated branches
                branches_generator = summarize(
                    _format_exec_code(src_testcase.exec_code),
                    latest_src_exec_summary,
                    function_call_chain,
                    testcase_manager.get_already_selected_branch_but_not_reached(
                        src_testcase.id
                    ),
                    parallel_num,
                )

                # Process each generated branch with its usage and message thread
                for branch_data in branches_generator:
                    # Unpack the yielded data
                    (
                        target_branch,
                        justification,
                        target_file_lines,
                        target_path_constraint,
                        usage_details,
                        current_msg_thread,
                    ) = branch_data

                    logger.info(f"Processing new branch: {target_branch}...")

                    target_lines_content = _get_file_lines(
                        target_file_lines[0], target_file_lines[1]
                    )

                    if target_lines_content:
                        assert (
                            len(target_lines_content.split("\n"))
                            == target_file_lines[1][1] - target_file_lines[1][0] + 1
                        )

                    # Create a new test case for each branch
                    new_testcase: TestCase = testcase_manager.create_new_testcase(
                        src_testcase.id,
                        latest_src_exec_summary,
                        target_branch,
                        justification,
                        target_file_lines,
                        target_lines_content,
                        target_path_constraint,
                    )

                    if branches_yielded_cnt == 0:
                        new_testcase.add_usage(
                            usage=selection_usage_details,
                            state=TestcaseState.SELECT,
                        )  # assign selection usage to the FIRST testcase
                    branches_yielded_cnt += 1
                    if branches_yielded_cnt > parallel_num:
                        logger.error(
                            f"Reached the maximum number ({parallel_num}) of branches to explore, but there are still branches to be processed...",
                        )
                    # Add current usage information
                    new_testcase.add_usage(
                        usage_details
                    )  # newly-generated testcase is in SUMMARIZE state
                    # Explicitly save the test case
                    new_testcase.save_to_disk()

                    # Store the message thread for this test case
                    under_gen_tc_msg_thread[new_testcase.id] = current_msg_thread.copy()
                    under_gen_tcs.append(new_testcase)

                    # use concurrent processing, submit tasks to the thread pool
                    task_executor.submit_task(
                        solve_and_execute,
                        under_gen_tcs[-1],
                        {
                            "summarize_msg_thread": under_gen_tc_msg_thread[
                                under_gen_tcs[-1].id
                            ],
                            "exec_timeout": timeout,
                            "disable_review": True,
                        },
                    )

                    logger.info(
                        f"Submitted new test case #{new_testcase.id} for solving and executing"
                    )

                # If no branches were generated, the should be prompt exceeded the token limit
                if branches_yielded_cnt == 0:
                    logger.error(
                        "No branches were selected and summarized during summarize process, maybe the prompt is too long"
                    )
                    cur_ce_state = ConcolicExecutionState.ITERATION_FINISHED
                else:
                    # state transition
                    cur_ce_state = ConcolicExecutionState.SOLVE_AND_EXECUTE
            case ConcolicExecutionState.SOLVE_AND_EXECUTE:
                # wait for all submitted test cases to finish
                logger.info(
                    f"Waiting for all submitted test cases to finish... (Round #{round_cnt})"
                )
                task_executor.wait_for_all_tasks()
                logger.info(
                    f"All test cases in round #{round_cnt} completed successfully"
                )

                # state transition
                cur_ce_state = ConcolicExecutionState.ITERATION_FINISHED
            case ConcolicExecutionState.ITERATION_FINISHED:
                # this iteration is finished, do some clean up and go to next iteration

                # update the successful generation count of the src testcase
                for tc in under_gen_tcs:
                    if tc.is_valuable():
                        src_testcase.successful_generation_cnt += 1
                src_testcase.save_to_disk()

                # update the plateau time
                last_new_coverage_time = (
                    time.time()
                    if any(tc.new_coverage for tc in under_gen_tcs)
                    else last_new_coverage_time
                )

                crash_cnt += sum(1 for tc in under_gen_tcs if tc.is_crash)
                hang_cnt += sum(1 for tc in under_gen_tcs if tc.is_hang)

                under_gen_tc_msg_thread.clear()
                under_gen_tcs.clear()

                logger.info(
                    f"{testcase_manager.get_statistics()[1]}\nCrash count: {crash_cnt}, hang count: {hang_cnt}"
                )

                # state transition
                cur_ce_state = ConcolicExecutionState.SELECT
                round_cnt += 1

                if rounds is None and plateau_slot is not None:
                    if time.time() - last_new_coverage_time > plateau_slot * 60:
                        logger.info(
                            "The code coverage has not improved for {} minutes, stopping the concolic execution...",
                            plateau_slot,
                        )
                        break


def setup_run_parser(parser):
    """Setup the run command parser."""
    run_parser = parser.add_parser(
        "run", help="run the concolic execution on an existing instrumented project"
    )
    run_parser.add_argument(
        "--project_dir",
        type=str,
        help="(instrumented) project directory",
        required=True,
    )
    run_parser.add_argument(
        "--execution",
        type=str,
        help="initial execution file path. Note: In this file, you can use (1) file path relative to the project directory, or (2) absolute file path.",
        required=False,
        default=None,
    )
    run_parser.add_argument(
        "--out",
        type=str,
        help="output directory",
        required=True,
    )
    run_parser.add_argument(
        "--resume_in",
        type=str,
        help="the original output directory to resume from",
        required=False,
        default=None,
    )
    run_parser.add_argument(
        "--rounds",
        type=int,
        help="number of rounds",
        required=False,
        default=None,
    )
    run_parser.add_argument(
        "--selection",
        type=str,
        help="test case selection method",
        required=False,
        default=TestCaseSelection.DFS,
        choices=[e.value for e in TestCaseSelection],
    )
    run_parser.add_argument(
        "--timeout",
        type=int,
        help="program execution timeout in seconds",
        required=False,
        default=3,
    )
    run_parser.add_argument(
        "--plateau_slot",
        type=int,
        help="plateau slot in minutes. The concolic execution will stop if the code coverage does not improve for this period of time (only used when --rounds is not specified, otherwise, the concolic execution will stop after running --rounds test cases).",
        required=False,
        default=None,
    )
    run_parser.add_argument(
        "--parallel_num",
        type=int,
        help="number of parallel testcase generation",
        required=False,
        default=5,
    )
    return run_parser
