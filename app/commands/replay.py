import os
import subprocess
import tempfile
from pathlib import Path

from loguru import logger

from app.agents.states import TestcaseState
from app.agents.testcase import TestCase, TestCaseManager
from app.model.common import Usage
from app.utils.utils import get_project_dir, run_target, update_project_dir


def run_coverage_script(
    cov_script: str,
    file_path: str | None = None,
    line: int | None = None,
    line_content: str | None = None,
) -> tuple[float, int, float, int, int]:
    """
    Run the coverage script and parse its output

    Args:
        cov_script: path to the coverage script

    Returns:
        Tuple of (line_percentage, line_absolute, branch_percentage, branch_absolute, covered_times_of_line)
    """
    try:
        logger.debug(
            f"Running coverage script with args: {cov_script} {file_path} {line} {line_content}"
        )
        # get the absolute path and directory of the script
        script_abs_path = os.path.abspath(cov_script)

        if file_path is not None and line is not None and line_content is not None:

            assert line_content.strip()

            try:
                real_file_path = str(
                    Path(file_path).relative_to(Path(get_project_dir()))
                )
                logger.debug(
                    f"File path has been converted to relative path: '{real_file_path}' (from '{file_path}') when querying coverage script"
                )
            except Exception:
                real_file_path = file_path

            command = [
                "bash",
                script_abs_path,
                real_file_path,
                str(line),
                str(line_content.strip()),  # ensure not empty line
            ]  # use the absolute path
        else:
            command = ["bash", script_abs_path]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=get_project_dir(),  # set the working directory to the project directory
        )

        if result.returncode != 0:
            raise RuntimeError(f"Coverage script run failed: {result.stderr}")

        # Parse the output which should be in format: l_per,l_abs,b_per,b_abs,covered_times_of_line
        l_per, l_abs, b_per, b_abs, covered_times_of_line = map(
            float, result.stdout.strip().split(",")
        )
        return l_per, int(l_abs), b_per, int(b_abs), int(covered_times_of_line)
    except Exception as e:
        raise RuntimeError(f"Failed to run coverage script, error: {e}.")


def replay_test_case(
    out_dir: str,
    project_dir: str,
    timeout,
    output_file: str,
    cov_script: str | None = None,
):
    """
    Replay the test case

    Args:
        out_dir: output directory that contains the test cases for replay
        project_dir: project directory where the target program (with coverage instrumentation) is located
        timeout: under-test-program execution timeout in seconds
        output_file: path to save coverage data (required if cov_script is provided)
        cov_script: path to the coverage script that outputs coverage data
    """

    # set the project directory
    update_project_dir(project_dir)

    # create an temporary directory using tempfile, and delete it after the function is finished any way
    with tempfile.TemporaryDirectory() as temp_dir:
        testcase_manager: TestCaseManager = TestCaseManager(temp_dir)

        testcase_manager.load_testcases(out_dir)

        logger.info(f"Ready to replay {testcase_manager.next_testcase_id} test cases")

        headers = [
            "Time",
            "id",
            "cost",
            "crashes",
            "hangs",
            "internal_lines_covered",
            "internal_target_reached",
        ]

        if cov_script:
            headers.extend(
                ["l_per", "l_abs", "b_per", "b_abs", "target_really_reached"]
            )

        with open(output_file, "w") as f:
            f.write(",".join(headers) + "\n")

        crash_or_hang_tc_ids = []
        crash_cnt = 0
        hang_cnt = 0

        total_usage: Usage = Usage()

        # Collect all valid testcases
        valid_testcases = []
        for testcase_id in range(0, testcase_manager.next_testcase_id):
            testcase: TestCase | None = testcase_manager.get_testcase(testcase_id)

            if testcase is None:
                logger.warning(f"Test case #{testcase_id} not found, skipping...")
                continue

            if (testcase.current_state != TestcaseState.FINISHED) and (
                testcase.exec_code is None
            ):
                logger.info(
                    f"Test case #{testcase_id} has not finished and has no exec_code, skipping..."
                )
                continue

            valid_testcases.append((testcase_id, testcase))

        # Sort testcases by time_taken (Since some testcases are generated in parallel, maybe one testcase with higher id is generated earlier)
        valid_testcases.sort(key=lambda x: (x[1].time_taken, x[0]))

        logger.info(
            f"Valid testcases after time_taken sorting ({len(valid_testcases)} testcases): {[id for id, _ in valid_testcases]}"
        )

        # Initialize variables for statistics
        internal_total_covered_lines = 0

        # Process testcases in sorted order
        for testcase_id, testcase in valid_testcases:

            logger.info(f"--- Test case #{testcase_id}: replay started ---")

            is_target_lines_really_reached = True if testcase.src_id is None else False
            l_per, l_abs, b_per, b_abs = 0, 0, 0, 0

            if testcase.usage:
                total_usage += testcase.usage["TOTAL"]
            else:
                logger.info(f"Test case #{testcase_id} has no usage, skipping...")

            if testcase.exec_code is None:
                assert not testcase.is_crash_or_hang()
                assert not testcase.is_valuable()
                assert not testcase.is_satisfiable
                logger.info(
                    f"Test case #{testcase_id} is not satisfiable and has no exec_code, skipping..."
                )
            else:

                if cov_script and (testcase.src_id is not None):
                    target_file: str = testcase.target_file_lines[0]
                    target_line_range: tuple[int, int] = testcase.target_file_lines[1]
                    target_lines_content: list[str] = (
                        testcase.target_lines_content.split("\n")
                    )
                    if target_file is None or target_line_range == (None, None):
                        logger.error(
                            f"Test case #{testcase_id} has no target file or target line range!"
                        )
                    else:
                        target_lines_prev_cov = []
                        for line_no in range(
                            target_line_range[0], target_line_range[1] + 1
                        ):
                            _content = target_lines_content[
                                line_no - target_line_range[0]
                            ].strip()
                            line_prev_cov = 0
                            if _content:  # non-empty line
                                line_prev_cov = run_coverage_script(
                                    cov_script, target_file, line_no, _content
                                )[4]
                            target_lines_prev_cov.append(line_prev_cov)
                        logger.debug(
                            f"Target lines previous coverage: {target_lines_prev_cov}"
                        )

                result = run_target(execution_code=testcase.exec_code, timeout=timeout)

                if result["exec_success"]:
                    logger.info(
                        f"Test case #{testcase_id} has been executed successfully"
                    )

                    if result["target_crashed"] != testcase.is_crash:
                        logger.warning(
                            f"Test case #{testcase_id} crash status mismatch. Replay result:\n{result}"
                        )

                    if result["target_timeout"] != testcase.is_hang:
                        logger.warning(
                            f"Test case #{testcase_id} hang status mismatch. Replay result:\n{result}"
                        )

                    if (
                        result["target_crashed"]
                        or result["target_timeout"]
                        or testcase.is_crash_or_hang()
                    ):
                        crash_or_hang_tc_ids.append(testcase_id)
                        if result["target_crashed"] or testcase.is_crash:
                            crash_cnt += 1
                        if result["target_timeout"] or testcase.is_hang:
                            hang_cnt += 1
                else:
                    logger.error(f"Test case #{testcase_id} failed to execute")

            internal_total_covered_lines += testcase.newly_covered_lines

            data = [
                testcase.time_taken,
                testcase_id,
                total_usage.cost,
                crash_cnt,
                hang_cnt,
                internal_total_covered_lines,
                testcase.is_target_covered,
            ]
            if cov_script:
                l_per, l_abs, b_per, b_abs, _ = run_coverage_script(
                    cov_script, None, None, None
                )

                if (
                    testcase.src_id is not None
                    and target_file is not None
                    and target_line_range != (None, None)
                ):
                    for line_no in range(
                        target_line_range[0], target_line_range[1] + 1
                    ):
                        idx = line_no - target_line_range[0]
                        _content = target_lines_content[idx].strip()
                        if _content:  # non empty line
                            line_curr_cov = run_coverage_script(
                                cov_script, target_file, line_no, _content
                            )[4]
                            # at least one target with increased cov
                            if line_curr_cov > target_lines_prev_cov[idx]:
                                is_target_lines_really_reached = True
                                break

                data.extend(
                    [l_per, l_abs, b_per, b_abs, is_target_lines_really_reached]
                )

            with open(output_file, "a") as f:
                f.write(",".join(map(str, data)) + "\n")
            logger.info(f"--- Test case #{testcase_id}: replay finished ---")

    logger.info(
        f"All test cases have been replayed ({len(valid_testcases)} testcases): {[id for id, _ in valid_testcases]}"
    )
    if crash_or_hang_tc_ids:
        logger.info(
            f"Crash or hang test case ids (total: {len(crash_or_hang_tc_ids)}): {crash_or_hang_tc_ids}"
        )


def setup_replay_parser(subparsers):
    """Setup the statistics subcommand parser"""
    replay_parser = subparsers.add_parser("replay", help="replay the test case")
    replay_parser.add_argument(
        "out_dir",
        help="output directory that contains the test cases for replay",
    )
    replay_parser.add_argument(
        "project_dir",
        help="project directory where the target program (with coverage/sanitizer instrumentation) is located",
    )
    replay_parser.add_argument(
        "output_file",
        help="path to save coverage data",
    )
    replay_parser.add_argument(
        "--cov_script",
        help="path to the coverage script that outputs coverage data in format: line_cov_percentage,line_cov_absolute,branch_cov_percentage,branch_cov_absolute",
        required=False,
    )
    replay_parser.add_argument(
        "--timeout",
        type=int,
        help="under-test-program execution timeout in seconds",
        required=False,
        default=3,
    )

    return replay_parser
