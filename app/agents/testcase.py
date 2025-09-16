"""
TestCase class for Concolic Execution.

This module provides a data structure similar to fuzzing seeds to store
information about each test case generated during concolic execution.
"""

import fcntl
import io
import math
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from io import StringIO
from typing import Any

import yaml as pyyaml
from loguru import logger
from ruamel.yaml import YAML, scalarstring

from app.agents.common import (
    SCHEDULING_FORMAT_REMINDER,
    ExecutionInformation,
    FunctionCallChain,
    HistoricalInformation,
    PathConstraint,
    SrcTestCaseId,
    TestCaseId,
    TestCaseInformation,
    wrap_between_tags,
)
from app.agents.coverage import Coverage
from app.agents.states import TestcaseState
from app.agents.trace import trace_compress
from app.model.common import Usage
from app.utils.utils import estimate_text_token, get_time_taken


# Create YAML configuration function
def create_yaml_instance():
    """Create a properly configured YAML instance."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.sort_keys = False
    return yaml


class TestCaseYAML:
    """Custom YAML handlers for TestCase serialization."""

    @staticmethod
    def target_file_lines_to_str(file_lines):
        """Convert target_file_lines tuple to readable string format."""
        if not file_lines or file_lines[0] is None:
            return None

        file_path, line_range = file_lines

        return f"{file_path}:{line_range[0]}-{line_range[1]}"

    @staticmethod
    def str_to_target_file_lines(value):
        """Convert string back to target_file_lines tuple."""
        if not value:
            return (None, (None, None))

        file_path, line_range = value.split(":", 1)

        start, end = line_range.split("-", 1)
        return (file_path, (int(start), int(end)))

    @staticmethod
    def format_usage_dict(usage_dict: dict, print_tokens: bool = True) -> str:
        """Format a dictionary containing Usage objects into a readable string.

        Args:
            usage_dict: Dictionary containing Usage objects or nested dictionaries
            print_tokens: Whether to include token counts in the output

        Returns:
            str: Formatted string representation of the dictionary
        """

        def format_value(value):
            if isinstance(value, dict):
                return {k: format_value(v) for k, v in value.items()}
            elif isinstance(value, Usage):
                return value.model_dump(print_tokens=print_tokens)
            else:
                return value

        formatted_dict = {k: format_value(v) for k, v in usage_dict.items()}

        # Use YAML dump for better formatting
        yaml_formatter = create_yaml_instance()

        # Convert to string using YAML
        string_stream = StringIO()
        yaml_formatter.dump(formatted_dict, string_stream)
        return string_stream.getvalue()

    @staticmethod
    def parse_usage_dict(yaml_str: str) -> dict[str, Usage]:
        """Parse a YAML string into a dictionary of Usage objects.

        This function reverses the operation performed by format_usage_dict.
        It parses a YAML string and reconstructs Usage objects from their serialized form.

        Args:
            yaml_str: YAML string representation of usage data

        Returns:
            dict: Dictionary with string keys and Usage object values
        """

        # Parse YAML string to dictionary
        data = pyyaml.safe_load(yaml_str)
        if not data:
            return {}

        result = {}

        # Process each key in the YAML data
        for key, value in data.items():
            if isinstance(value, dict):
                if "TOTAL" in value:
                    # Handle nested dictionary with TOTAL and other keys
                    result[key] = TestCaseYAML._process_nested_usage_dict(value)
                else:
                    # Handle flat usage dictionary
                    result[key] = Usage.model_validate(value)
            else:
                # Handle non-dictionary values
                result[key] = value

        return result

    @staticmethod
    def _process_nested_usage_dict(nested_dict: dict) -> dict[str, Usage]:
        """Process a nested dictionary of usage data.

        Args:
            nested_dict: Dictionary containing nested usage data

        Returns:
            dict: Dictionary with string keys and Usage object values
        """
        result = {}

        for key, value in nested_dict.items():
            if isinstance(value, dict):
                result[key] = Usage.model_validate(value)
            else:
                result[key] = value

        return result

    @staticmethod
    def process_dict_for_yaml(data):
        """Process dictionary for YAML serialization, converting special types."""
        result = data.copy()

        if "target_file_lines" in result and isinstance(
            result["target_file_lines"], tuple
        ):
            result["target_file_lines"] = TestCaseYAML.target_file_lines_to_str(
                result["target_file_lines"]
            )

        if (
            "states" in result
            and isinstance(result["states"], list)
            and result["states"]
        ):
            result["states"] = [str(state) for state in result["states"]]

        # Handle usage dictionary if it's not empty
        if "usage" in result and isinstance(result["usage"], dict) and result["usage"]:
            result["usage"] = TestCaseYAML.format_usage_dict(result["usage"])

        # use YAML block style for all string fields
        for _field, value in result.items():
            if isinstance(value, str) and "\n" in value:
                result[_field] = scalarstring.LiteralScalarString(value)

        return result

    @staticmethod
    def process_dict_from_yaml(data):
        """Process dictionary loaded from YAML, converting strings back to complex types."""
        result = data.copy()

        if "target_file_lines" in result:
            if result["target_file_lines"] is None:
                result["target_file_lines"] = (None, (None, None))
            elif isinstance(result["target_file_lines"], str):
                result["target_file_lines"] = TestCaseYAML.str_to_target_file_lines(
                    result["target_file_lines"]
                )

        if (
            "states" in result
            and isinstance(result["states"], list)
            and result["states"]
            and isinstance(result["states"][0], str)
        ):
            result["states"] = [TestcaseState[state] for state in result["states"]]

        # Parse usage string back to dictionary if it looks like YAML
        if (
            "usage" in result
            and isinstance(result["usage"], str)
            and result["usage"].strip()
        ):
            try:
                result["usage"] = TestCaseYAML.parse_usage_dict(result["usage"])
            except Exception as e:
                logger.warning(f"Failed to parse usage as YAML: {e}")

        return result


@dataclass(slots=True)
class TestCase:
    """
    A class representing a test case in concolic execution.

    Similar to seeds in fuzzing, each test case contains execution code,
    trace information, and metadata about its performance and generation.
    """

    # Basic information
    id: int
    src_id: int | None = (
        None  # "None" means this is an initial testcase. This is a flag to indicate the testcase is an initial testcase.
    )

    create_time: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    )  # creation time of this test case
    time_taken: int | None = (
        None  # time taken to generate this test case (in seconds). Continously updated before the test case has been finished.
    )

    states: list[TestcaseState] = field(default_factory=list)

    # Constraint information
    is_target_covered: bool = False
    new_coverage: bool = False
    newly_covered_lines: int = 0
    is_satisfiable: bool = False
    is_crash: bool = False
    is_hang: bool = False
    usage: dict = field(default_factory=lambda: {"TOTAL": Usage()})

    target_branch: str | None = None
    target_file_lines: tuple[str | None, tuple[int, int] | None] = (
        None,
        (None, None),
    )  # file path relative to project root, [start line, end line]
    target_lines_content: str | None = (
        None  # only used for comparison with standard coverage mechanism (like GCOV) in replay stage.
    )
    justification: str | None = None
    target_path_constraint: str | None = None

    # Selection statistics
    selected_cnt: int = 0
    successful_generation_cnt: int = 0

    # Execution and results
    exec_code: str | None = None
    returncode: int | None = None
    src_execution_summary: str | None = None
    crash_info: str | None = None

    execution_trace: str | None = None
    execution_summary: str | None = None

    src_exec_code: str | None = None
    src_execution_trace: str | None = None

    # Output directory (non-serialized)
    _out_dir: str | None = field(default=None, repr=False)
    _in_setattr: bool = field(
        default=False, repr=False
    )  # Flag to prevent infinite recursion

    def __post_init__(self):
        """Called after dataclass initialization."""
        # Ensure non-serialized fields are initialized
        object.__setattr__(self, "_out_dir", None)
        object.__setattr__(self, "_in_setattr", False)

    def __setattr__(self, name, value):
        """
        Intercept attribute assignments to automatically save when modified.

        This will be called whenever an attribute is set on the object.
        """
        # safely check _in_setattr attribute, use try-except to catch possible exceptions
        try:
            in_setattr = self._in_setattr
        except (AttributeError, TypeError):
            # if the attribute does not exist or the object is not fully initialized, set a default value
            in_setattr = False

        # avoid infinite recursion
        if in_setattr:
            object.__setattr__(self, name, value)
            return

        # set the attribute
        object.__setattr__(self, name, value)

        # Update time_taken if not setting time_taken itself
        if (
            name != "time_taken"
            and not name.startswith("_")
            and hasattr(self, "states")  # ensure states attribute is initialized
            and self.states  # ensure states is not empty
            and self.states[-1] != TestcaseState.FINISHED
        ):
            object.__setattr__(
                self,
                "time_taken",
                get_time_taken(),
            )

        # Auto-save functionality disabled to prevent file I/O errors
        # If you want to save the object, call save_to_disk() explicitly
        # try:
        #     # only save when the attribute is not a private attribute and _out_dir exists
        #     if (
        #         not name.startswith("_")
        #         and hasattr(self, "_out_dir")
        #         and self._out_dir is not None
        #     ):
        #         # set the flag to prevent recursion
        #         object.__setattr__(self, "_in_setattr", True)
        #         try:
        #             self.save_to_disk()
        #         finally:
        #             # reset the flag
        #             object.__setattr__(self, "_in_setattr", False)
        # except Exception as e:
        #     # record the error but allow the attribute setting to succeed
        #     logger.error(f"Error during auto-save in __setattr__: {e}")
        #     # ensure the flag is reset
        #     object.__setattr__(self, "_in_setattr", False)

    @property
    def current_state(self) -> TestcaseState | None:
        """Get the current execution state."""
        return self.states[-1] if self.states else None

    def add_state(self, state: TestcaseState) -> None:
        """Add a new state to the state history."""
        self.states.append(state)

    @classmethod
    def create_initial(
        cls,
        id: int,
        exec_code: str,
        execution_trace: str,
        execution_summary: str,
        newly_covered_lines: int,
        out_dir: str = None,
    ) -> "TestCase":
        """Create an initial test case (first seed)."""
        assert (
            newly_covered_lines > 0
        ), "Initial test case should always provide new coverage"
        tc = cls(
            id=id,
            src_id=None,  # initial test case has no source test case
            time_taken=0,
            src_exec_code=None,
            src_execution_trace=None,
            exec_code=exec_code,
            execution_trace=execution_trace,
            execution_summary=execution_summary,
            new_coverage=True,  # Initial test case always provides new coverage
            newly_covered_lines=newly_covered_lines,
            is_target_covered=True,  # there is no target lines for initial test case
            states=[
                TestcaseState.FINISHED,
            ],  # initial test case is always finished
        )
        # Set output directory and ensure initial save
        if out_dir:
            # Use direct attribute setting instead of __dict__
            setattr(tc, "_out_dir", out_dir)
            tc.save_to_disk()  # Explicitly save after creation
        return tc

    @classmethod
    def from_src(cls, src_tc: "TestCase", id: int) -> "TestCase":
        """Create a new test case derived from a source test case."""
        tc = cls(
            id=id,
            src_exec_code=src_tc.exec_code,
            src_execution_trace=src_tc.execution_trace,
            src_id=src_tc.id,
            states=[
                TestcaseState.SELECT,
                TestcaseState.SUMMARIZE,
            ],  # the first state of a new test case is always SUMMARIZE
        )
        # Inherit parent's output directory
        if src_tc._out_dir:
            # Use direct attribute setting
            setattr(tc, "_out_dir", src_tc._out_dir)
            tc.save_to_disk()  # Explicitly save after creation
        else:
            raise ValueError("Source test case has no output directory")

        # update selection statistics
        src_tc.selected_cnt += 1
        return tc

    def to_dict(self) -> dict[str, Any]:
        """Convert the test case to a dictionary for YAML serialization."""
        # Use asdict to convert dataclass to dict
        data = asdict(self)
        # Remove non-serialized fields
        for _field in ["_out_dir", "_in_setattr"]:
            if _field in data:
                del data[_field]

        # Process data for better YAML representation
        return TestCaseYAML.process_dict_for_yaml(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TestCase":
        """Create a test case from a dictionary (from YAML deserialization)."""
        # Process the data to convert strings back to complex types
        processed_data = TestCaseYAML.process_dict_from_yaml(data)

        # Remove non-serialized fields if they are in the dictionary
        for _field in ["_out_dir", "_in_setattr"]:
            if _field in processed_data:
                del processed_data[_field]

        return cls(**processed_data)

    def write_to_yaml_file(self, yaml_path: str, content: str) -> None:
        """Write content to a YAML file with file locking."""
        # maximum number of retries
        max_retries = 3
        retry_delay = 0.1

        for attempt in range(max_retries):
            try:
                with open(yaml_path, "w") as yaml_file:
                    # acquire an exclusive lock
                    fcntl.flock(yaml_file.fileno(), fcntl.LOCK_EX)
                    try:
                        yaml_file.write(content)
                    finally:
                        # release the lock
                        fcntl.flock(yaml_file.fileno(), fcntl.LOCK_UN)
                    return  # successfully write, exit function
            except (ValueError, OSError) as e:
                logger.warning(
                    f"Attempt {attempt+1}/{max_retries} failed to write to {yaml_path}: {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)  # brief delay before retrying
                else:
                    # last attempt, record the error but do not raise an exception
                    raise Exception(
                        f"Failed to save test case to {yaml_path}, reached the maximum number of retries"
                    )

    def save_to_disk(self) -> None:  # should ensure "queue" directory exists
        """
        Save the test case information to disk.
        """
        if not self._out_dir:
            raise ValueError("Cannot save test case: no output directory specified")

        # Always save to queue
        queue_dir = os.path.join(self._out_dir, "queue")

        # Convert TestCase to dictionary
        data = self.to_dict()

        # Construct filename using AFL-style naming convention
        if self.src_id is not None:
            filename = f"id:{self.id:06d},src:{self.src_id:06d}.yaml"
        else:
            filename = f"id:{self.id:06d}.yaml"

        # Try multiple serialization methods for robustness
        yaml_str = None
        try:
            # Create a new YAML instance each time
            yaml_instance = create_yaml_instance()
            string_stream = io.StringIO()
            yaml_instance.dump(data, string_stream)
            yaml_str = string_stream.getvalue()
        except Exception as e:
            logger.error(
                f"Primary YAML serialization failed: {e}\nOriginal data:\n{data}"
            )
            try:
                # Fallback to a simpler YAML instance
                backup_yaml = YAML()
                backup_yaml.default_flow_style = False
                string_stream = io.StringIO()
                backup_yaml.dump(data, string_stream)
                yaml_str = string_stream.getvalue()
            except Exception as e2:
                logger.error(f"Secondary YAML serialization failed:\n{e2}\n")
                try:
                    # Final fallback to pyyaml
                    yaml_str = pyyaml.safe_dump(
                        data, default_flow_style=False, sort_keys=False
                    )
                except Exception as e3:
                    err_msg = f"Final YAML serialization fallback failed:\n{e3}"
                    logger.error(err_msg)
                    raise RuntimeError(err_msg)

        assert yaml_str is not None

        # Save to queue folder
        yaml_path = os.path.join(queue_dir, filename)

        self.write_to_yaml_file(yaml_path, yaml_str)

        # Optionally also save to crashes folder - only if it's a crash
        if self.is_crash or self.is_hang:
            _dir = os.path.join(self._out_dir, "crashes_or_hangs")
            os.makedirs(_dir, exist_ok=True)

            # Use the same filename and copy the file to crashes_or_hangs folder
            _file_path = os.path.join(_dir, filename)
            shutil.copy(yaml_path, _file_path)

    @classmethod
    def load_from_file(cls, yaml_path: str, out_dir: str) -> "TestCase":
        """
        Load a test case directly from a YAML file path.

        Args:
            yaml_path: Path to the YAML file
            out_dir: output directory to set for the loaded test case
        """
        # Use binary mode to read the file and filter out NULL characters
        with open(yaml_path, "rb") as yaml_file:
            content = yaml_file.read()
            # Filter out NULL characters, keep all other characters
            content = content.replace(b"\x00", b"")
            # Filter out EOT (End of Transmission) characters - ASCII 0x04
            content = content.replace(b"\x04", b"")
            # Also filter DEL character (0x7F)
            content = content.replace(b"\x7F", b"")

            # # Filter out other control characters that may cause issues
            # # Keep whitespace characters: TAB (0x09), LF (0x0A), CR (0x0D)
            # for i in range(0, 32):
            #     if i not in (9, 10, 13):  # Skip TAB, LF, CR
            #         content = content.replace(bytes([i]), b"")

            yaml_instance = create_yaml_instance()
            data = yaml_instance.load(content.decode("utf-8", errors="replace"))

        if not isinstance(data, dict):
            raise ValueError("Invalid YAML format")

        tc = cls.from_dict(data)
        if out_dir:
            # Use direct attribute setting
            setattr(tc, "_out_dir", out_dir)

        setattr(
            tc,
            "time_taken",
            data["time_taken"],
        )  # since time_taken would automatically be set in __setattr__, ensure it confirms to the YAML file
        return tc

    def __str__(self) -> str:
        """String representation of the test case."""
        return (
            f"TestCase(id={self.id}, src_id={self.src_id}, "
            f"is_target_covered={self.is_target_covered}, newly_covered_lines={self.newly_covered_lines})"
        )

    def add_usage(self, usage: dict, state: TestcaseState | None = None):
        """Add usage information to the test case."""
        self.usage["TOTAL"] += usage["TOTAL"]
        if state is None:
            state = self.current_state
        assert str(state) not in self.usage
        self.usage[str(state)] = usage

    def get_historical_information(self) -> tuple[int, int]:
        """
        Get historical information about how many times this test case has been selected
        and its failure ratio.

        Returns:
            A string with the format "[failure times]/[total selection times](ratio)"
        """
        failure_cnt = self.selected_cnt - self.successful_generation_cnt
        # Calculate success ratio

        assert failure_cnt <= self.selected_cnt

        return (failure_cnt, self.selected_cnt)

    def is_crash_or_hang(self) -> bool:
        """Check if the test case is crash or hang."""
        return self.is_crash or self.is_hang

    def is_valuable(self) -> bool:
        """Check if the test case is valuable for further exploration."""
        return self.is_target_covered or self.new_coverage


class TestCaseManager:
    """Manages a collection of test cases during concolic execution."""

    def __init__(self, out_dir: str):
        """Initialize the test case manager."""
        self.out_dir = out_dir
        self.test_cases: dict[int, TestCase] = {}
        self.next_testcase_id = 0

        # Only create queue directory at initialization
        os.makedirs(os.path.join(out_dir, "queue"), exist_ok=True)
        # Crashes directory will be created when first crash occurs

    def add_initial_testcase(
        self,
        exec_code: str,
        execution_trace: str,
        execution_summary: str,
        newly_covered_lines: int,
        save_immediately: bool = True,
    ) -> TestCase:
        """Add the initial test case (first seed)."""
        testcase = TestCase.create_initial(
            self.next_testcase_id,
            exec_code,
            execution_trace,
            execution_summary,
            newly_covered_lines,
            self.out_dir,
        )
        self.test_cases[self.next_testcase_id] = testcase
        self.next_testcase_id += 1
        if save_immediately:
            testcase.save_to_disk()
        return testcase

    def create_new_testcase(
        self,
        src_id: int,
        latest_src_exec_summary: str,
        target_branch: str,
        justification: str,
        target_file_lines: tuple[str | None, tuple[int, int] | None],
        target_lines_content: str | None,
        target_path_constraint: str,
        save_immediately: bool = True,
    ) -> TestCase:
        """Add a new test case derived from a parent test case."""
        parent = self.test_cases.get(src_id)
        if not parent:
            raise ValueError(f"Parent test case with ID {src_id} does not exist.")

        testcase = TestCase.from_src(parent, self.next_testcase_id)

        testcase.src_execution_summary = latest_src_exec_summary
        testcase.target_branch = target_branch
        testcase.justification = justification
        testcase.target_file_lines = target_file_lines
        testcase.target_lines_content = target_lines_content
        testcase.target_path_constraint = target_path_constraint

        self.test_cases[self.next_testcase_id] = testcase
        self.next_testcase_id += 1
        if save_immediately:
            testcase.save_to_disk()
        return testcase

    def get_testcase(self, id: int) -> TestCase | None:
        """Get a test case by ID."""
        return self.test_cases.get(id)

    def get_already_selected_branch_but_not_reached(self, src_id: int) -> list[str]:
        """Get the already selected branch but not reached for a test case."""
        if not self.get_testcase(src_id):
            raise ValueError(f"Test case with ID {src_id} does not exist.")

        result = []
        for _id in range(src_id + 1, self.next_testcase_id):
            tc = self.get_testcase(_id)
            if (
                tc.current_state != TestcaseState.FINISHED
            ):  # only count for finished test cases
                continue
            if tc.src_id == src_id:
                if not (tc.is_crash_or_hang() or tc.is_valuable()):
                    result.append(tc.target_branch)
        return result

    def save_all_testcases(self) -> None:
        """Save all test cases to disk."""
        for tc in self.test_cases.values():
            tc.save_to_disk()

    def _load_testcases_from_dir(
        self,
        directory: str,
    ) -> tuple[dict[int, TestCase], int]:
        """
        Load test cases from a specific directory.

        Args:
            directory: Directory to load test cases from
        """
        if not os.path.exists(directory):
            logger.warning(
                f"Directory {directory} does not exist, skipping loading test cases"
            )
            return {}, 0

        testcases = {}
        max_id = 0

        for filename in os.listdir(directory):
            if filename.endswith(".yaml") and filename.startswith("id:"):
                # Extract ID from filename (format: id:000000,src:000000.yaml)
                if "," in filename:
                    id_part = filename.split(",")[0]
                else:
                    id_part = filename.split(".")[0]

                id_str = id_part[3:]  # Remove "id:" prefix
                try:
                    tc_id = int(id_str)

                    # Load directly from file path
                    yaml_path = os.path.join(directory, filename)
                    testcase = TestCase.load_from_file(yaml_path, self.out_dir)

                    # Add to appropriate dictionary
                    testcases[tc_id] = testcase
                    max_id = max(max_id, tc_id)
                except Exception as e:
                    logger.error(f"Error loading test case from file: {filename} - {e}")

        return testcases, max_id + 1  # Return the next available ID

    def load_testcases(
        self,
        in_dir: str,
    ) -> None:
        """Load all test cases from disk."""
        self.test_cases, self.next_testcase_id = self._load_testcases_from_dir(
            os.path.join(in_dir, "queue")
        )

        # Log summary of loaded test cases
        logger.info(f"Loaded {len(self.test_cases)} test cases")

    def get_statistics(self) -> tuple[dict, str]:
        """Get statistics about the test cases."""
        statistics = {
            "reach_success": [],
            "reach_failure": [],
            "unsatisfiable_constraints": [],
            "new_coverage": [],
            "crashes": [],
            "hangs": [],
        }

        gen_finished_tc_cnt = 0
        for testcase_id in range(0, self.next_testcase_id):
            testcase: TestCase | None = self.get_testcase(testcase_id)
            if testcase is None:
                logger.error(f"Test case with ID {testcase_id} not found")
                continue  # testcase not found

            if testcase.src_id is None:
                continue  # initial testcase is not included

            if testcase.current_state != TestcaseState.FINISHED:
                continue  # unfinished testcase is not included

            gen_finished_tc_cnt += 1

            if testcase.new_coverage:
                statistics["new_coverage"].append(testcase.id)

            if testcase.is_crash:
                statistics["crashes"].append(testcase.id)

            if testcase.is_hang:
                statistics["hangs"].append(testcase.id)

            if testcase.is_target_covered:
                assert testcase.is_satisfiable

                if testcase.states.__contains__(TestcaseState.REVIEW_SUMMARY_EXECUTE):
                    statistics["reach_success"].append(
                        str(testcase.id) + " (ReviewSummarizer)"
                    )
                elif testcase.states.__contains__(TestcaseState.REVIEW_SOLVER_EXECUTE):
                    statistics["reach_success"].append(
                        str(testcase.id) + " (ReviewSolver)"
                    )
                else:
                    statistics["reach_success"].append(testcase.id)
            else:
                if testcase.is_satisfiable:
                    if testcase.new_coverage:
                        statistics["reach_failure"].append(
                            str(testcase.id) + " (NewCov)"
                        )
                    else:
                        statistics["reach_failure"].append(testcase.id)
                else:
                    statistics["unsatisfiable_constraints"].append(testcase.id)

        if gen_finished_tc_cnt == 0:
            return statistics, "No newly generated test cases found"
        else:
            show_str = "========== Statistics ==========\n"
            for key, value in statistics.items():
                show_str += f"{key}: {len(value)}/{gen_finished_tc_cnt} ({len(value)/gen_finished_tc_cnt:.2%})\n\t- {value}\n"

            return statistics, show_str

    def get_crash_and_hang_count(self) -> tuple[int, int]:
        """Get the number of crashes and hangs."""
        crashes = sum(1 for tc in self.test_cases.values() if tc.is_crash)
        hangs = sum(1 for tc in self.test_cases.values() if tc.is_hang)
        return crashes, hangs

    def get_max_time_taken(self) -> int:
        """Get the maximum time taken to generate all test cases."""
        return max(tc.time_taken for tc in self.test_cases.values())

    def get_all_scheduling_information(self) -> dict[int, str]:
        """
        Get information about all test cases for the scheduling agent.
        Returns a formatted string with all test cases information needed for scheduling.

        Returns:
            A dict containing:
            - test case ID -> test case information
        """
        if not self.test_cases:
            raise ValueError("No test cases available.")

        valuable_testcase_info: list[tuple[str, float, int]] = []

        for tc_id, tc in self.test_cases.items():
            if tc.is_valuable():
                if tc.current_state != TestcaseState.FINISHED:
                    logger.error(
                        "Test case #{} is valuable but not finished, this should not happen",
                        tc_id,
                    )
                assert tc.exec_code is not None
                info, weight = self.get_test_case_scheduling_information(tc_id)
                info = wrap_between_tags(
                    TestCaseInformation.__xml_tag__,
                    info,
                )
                valuable_testcase_info.append((info, weight, tc_id))

        raw_str = "\n\n".join(
            [SCHEDULING_FORMAT_REMINDER]
            + [info for info, _, _ in valuable_testcase_info]
        )

        TOKEN_LIMIT = 180 * 1000

        estimated_token = estimate_text_token(raw_str)
        logger.info(
            "Estimated token for scheduling before truncation: {}", estimated_token
        )

        if estimated_token > TOKEN_LIMIT:
            logger.info("Truncating test cases due to token limit")
            selected_tc_ids = []
            # sort by weight in descending order
            valuable_testcase_info.sort(key=lambda x: (x[1], x[2]), reverse=True)

            truncated_str = SCHEDULING_FORMAT_REMINDER + "\n\n"
            for info, weight, tc_id in valuable_testcase_info:
                if estimate_text_token(truncated_str + info) > TOKEN_LIMIT:
                    logger.warning(
                        "Truncated to {} test cases (from {} test cases) due to token limit",
                        len(selected_tc_ids),
                        len(valuable_testcase_info),
                    )
                    assert len(selected_tc_ids) > 0  # should be at least one test case
                    return {tc_id: info for info, _, tc_id in selected_tc_ids}

                truncated_str += info + "\n\n"
                selected_tc_ids.append((info, weight, tc_id))

            assert False  # should not reach here
        else:
            return {tc_id: info for info, _, tc_id in valuable_testcase_info}

    def get_test_case_scheduling_information(self, tc_id: int) -> tuple[str, float]:
        """
        Get detailed information about a specific test case for the scheduling agent.

        Args:
            tc_id: The ID of the test case to get information for

        Returns:
            A formatted string containing all the information needed by the scheduling agent
        """
        tc: TestCase | None = self.get_testcase(tc_id)
        if tc is None:
            raise ValueError(f"Test case with ID {tc_id} not found.")

        coverage = Coverage.get_instance()

        # 1. Test Case ID
        info = wrap_between_tags(TestCaseId.__xml_tag__, str(tc.id))

        # 2. Source Test Case ID
        info += wrap_between_tags(
            SrcTestCaseId.__xml_tag__,
            str(tc.src_id if tc.src_id is not None else "None"),
        )

        # 3. Path Constraint
        if tc.is_target_covered:
            path_constraint = tc.target_path_constraint
        else:
            path_constraint = "None"
        info += wrap_between_tags(PathConstraint.__xml_tag__, path_constraint)

        # 4. Execution Information
        info += wrap_between_tags(ExecutionInformation.__xml_tag__, tc.exec_code)

        # 5. Function Call Chain
        func_call_chain = trace_compress(tc.execution_trace)
        func_call_chain_parts = []
        _file_coverage = []
        for relative_file_path, func_name, blocks in func_call_chain:
            relative_file_path = os.path.normpath(relative_file_path)

            file_coverage = coverage.get_file_coverage(relative_file_path)

            _l, _total = file_coverage.get_function_line_cov(func_name)

            func_call_chain_parts.append(
                (
                    relative_file_path,
                    func_name,
                    (_l, _total),
                    file_coverage.get_exec_block_cov(func_name, blocks),
                )
            )
            _file_coverage.append(_l / _total)

        SHOW_FUNC_NUM = 20

        # Generate function call chain string
        if len(func_call_chain_parts) > SHOW_FUNC_NUM:
            # Ensure the first and last functions are selected
            first_index = 0
            last_index = len(func_call_chain_parts) - 1

            # Create a list with indices, excluding the first and last
            indexed_coverage = [
                (i, cov)
                for i, cov in enumerate(_file_coverage)
                if i != first_index and i != last_index
            ]

            # Sort by coverage rate from smallest to largest
            indexed_coverage.sort(key=lambda x: x[1])

            # Get the indices of the SHOW_FUNC_NUM-2 functions with the lowest coverage (if any)
            middle_indices = [idx for idx, _ in indexed_coverage[: (SHOW_FUNC_NUM - 2)]]

            # Merge indices: first + middle 18 + last
            lowest_indices = [first_index] + middle_indices + [last_index]

            # Sort by the original order of the function call chain
            lowest_indices.sort()

            # Select the functions to display
            selected_parts = [func_call_chain_parts[i] for i in lowest_indices]

            # Generate a string with ellipsis
            func_call_chain_str = f"(The call chain is with {len(func_call_chain_parts)} funcs. Only showing the funcs with lowest coverage in the middle of the chain)\n"
            for i, part in enumerate(selected_parts):
                if i == 0:
                    func_call_chain_str += f"{part[0]}[{part[1]} ({math.ceil(part[2][0]/part[2][1]*100)}%)][{math.ceil(part[3][0]/part[3][1]*100)}%]"
                else:
                    func_call_chain_str += f"=>{part[0]}[{part[1]} ({math.ceil(part[2][0]/part[2][1]*100)}%)][{math.ceil(part[3][0]/part[3][1]*100)}%]"

                # Add "..." in the appropriate position to represent the omitted
                if (
                    i < len(selected_parts) - 1
                    and lowest_indices[i + 1] - lowest_indices[i] > 1
                ):
                    func_call_chain_str += f"=>[..{lowest_indices[i+1]-lowest_indices[i]-1} funcs omitted..]"
        else:
            func_call_chain_str = "=>".join(
                [
                    f"{part[0]}[{part[1]} ({math.ceil(part[2][0]/part[2][1]*100)}%)][{math.ceil(part[3][0]/part[3][1]*100)}%]"
                    for part in func_call_chain_parts
                ]
            )

        info += wrap_between_tags(
            FunctionCallChain.__xml_tag__,
            func_call_chain_str,
        )

        # 6. Historical Information
        historical_fail_info = tc.get_historical_information()
        fail_ratio = (
            historical_fail_info[0] / historical_fail_info[1]
            if historical_fail_info[1] > 0
            else 0
        )
        weight = 1 - fail_ratio
        info += wrap_between_tags(
            HistoricalInformation.__xml_tag__,
            f"{historical_fail_info[0]}/{historical_fail_info[1]}({fail_ratio:.1%})",
        )

        return info, weight + 1 if tc.new_coverage else 0
