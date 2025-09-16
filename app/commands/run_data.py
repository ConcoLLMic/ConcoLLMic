import tempfile

from app.agents.states import TestcaseState
from app.agents.testcase import TestCaseManager, TestCaseYAML
from app.model.common import Usage


def collect_run_data(out_dir: str, print_tokens: bool):
    """
    Collect and analyze cost statistics from files in the specified directory

    Args:
        directory (str): Directory path to search
    """

    # create an temporary directory using tempfile, and delete it after the function is finished any way
    with tempfile.TemporaryDirectory() as temp_dir:
        testcase_manager: TestCaseManager = TestCaseManager(temp_dir)

        testcase_manager.load_testcases(out_dir)

        overall_usage = {}
        for state in ["TOTAL"] + list(TestcaseState):
            overall_usage[str(state)] = Usage()

        finished_testcases = 0

        for testcase_id in range(0, testcase_manager.next_testcase_id):
            testcase = testcase_manager.get_testcase(testcase_id)
            if testcase is None:
                print(f"WARNING: Testcase {testcase_id} not found, skipping...")
                continue

            if testcase.src_id is None:
                print(f"Testcase {testcase_id} is an initial testcase, skipping...")
                continue

            if testcase.current_state != TestcaseState.FINISHED:
                print(f"Testcase {testcase_id} has not finished, skipping...")
                continue

            finished_testcases += 1

            if testcase.usage == {}:
                raise RuntimeError(
                    f"Testcase {testcase_id} has no usage, please check the testcase."
                )

            usage: Usage = testcase.usage
            print(
                f"--- Testcase {testcase_id} usage --- \n{TestCaseYAML.format_usage_dict(usage,print_tokens=print_tokens)}"
            )
            for key, value in usage.items():
                if key == "TOTAL":
                    overall_usage[key] += value
                else:
                    overall_usage[key] += value["TOTAL"]

        new_overall_usage = {}

        for key, value in overall_usage.items():
            if key.endswith("EXECUTE"):
                assert value.model_dump() == {}  # should be empty
            else:
                new_overall_usage[key] = value

        print("=" * 50)
        print(f"Overall usage of {finished_testcases} finished testcases:")
        print(
            TestCaseYAML.format_usage_dict(new_overall_usage, print_tokens=print_tokens)
        )
        print("=" * 50)

        _, show_str = testcase_manager.get_statistics()
        print(show_str)


def setup_run_data_parser(subparsers):
    """Setup the statistics subcommand parser"""
    statistics_parser = subparsers.add_parser(
        "run_data", help="collect and analyze cost statistics"
    )
    statistics_parser.add_argument(
        "out_dir",
        help="output directory to search for cost statistics",
    )
    statistics_parser.add_argument(
        "--print-tokens",
        type=lambda x: x.lower() == "true",
        help="print the tokens of the testcase (True/False)",
        default=True,
    )
    return statistics_parser
