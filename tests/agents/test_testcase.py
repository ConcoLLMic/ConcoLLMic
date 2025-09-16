import os
import tempfile

from app.agents.testcase import TestCase, TestCaseYAML, create_yaml_instance
from app.commands.run import TestcaseState


def test_target_file_lines_conversion():
    """Test conversion between target_file_lines tuple and string"""
    # Test normal case
    file_lines = ("app/main.py", (10, 20))
    str_value = TestCaseYAML.target_file_lines_to_str(file_lines)
    assert str_value == "app/main.py:10-20"

    # Test conversion back from string to tuple
    converted_back = TestCaseYAML.str_to_target_file_lines(str_value)
    assert converted_back == file_lines

    # Test None values
    assert TestCaseYAML.target_file_lines_to_str((None, (None, None))) is None
    assert TestCaseYAML.str_to_target_file_lines(None) == (None, (None, None))


def test_process_dict_for_yaml():
    """Test processing dictionary for YAML serialization"""
    # Create dictionary with special types
    data = {
        "id": 1,
        "target_file_lines": ("app/main.py", (10, 20)),
        "states": [TestcaseState.SUMMARIZE, TestcaseState.SOLVE],
    }

    # Process dictionary
    processed = TestCaseYAML.process_dict_for_yaml(data)

    # Verify results
    assert processed["id"] == 1
    assert processed["target_file_lines"] == "app/main.py:10-20"
    assert processed["states"] == ["SUMMARIZE", "SOLVE"]


def test_process_dict_from_yaml():
    """Test processing dictionary loaded from YAML deserialization"""
    # Simulate data loaded from YAML
    data = {
        "id": 1,
        "target_file_lines": "app/main.py:10-20",
        "states": ["SUMMARIZE", "SOLVE"],
    }

    # Process dictionary
    processed = TestCaseYAML.process_dict_from_yaml(data)

    # Verify results
    assert processed["id"] == 1
    assert processed["target_file_lines"] == ("app/main.py", (10, 20))
    assert processed["states"] == [TestcaseState.SUMMARIZE, TestcaseState.SOLVE]


def test_testcase_serialization_deserialization():
    """Test complete serialization and deserialization process for TestCase"""
    # Create temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create TestCase instance
        test_case = TestCase(
            id=1,
            exec_code="print('hello')",
            execution_trace="trace data",
            execution_summary="summary",
            target_file_lines=("app/main.py", (10, 20)),
            states=[TestcaseState.SUMMARIZE, TestcaseState.SOLVE],
            is_target_covered=True,
            new_coverage=True,
        )
        test_case._out_dir = temp_dir

        queue_dir = os.path.join(temp_dir, "queue")
        os.makedirs(queue_dir, exist_ok=True)

        # Save to file
        test_case.save_to_disk()

        # Load from file
        yaml_file = os.path.join(queue_dir, "id:000001.yaml")
        loaded_test_case = TestCase.load_from_file(yaml_file, temp_dir)

        # Verify key attributes are correctly restored
        assert loaded_test_case.id == test_case.id
        assert loaded_test_case.exec_code == test_case.exec_code
        assert loaded_test_case.execution_trace == test_case.execution_trace
        assert loaded_test_case.execution_summary == test_case.execution_summary
        assert loaded_test_case.target_file_lines == test_case.target_file_lines
        assert loaded_test_case.states == test_case.states
        assert loaded_test_case.is_target_covered == test_case.is_target_covered
        assert loaded_test_case.new_coverage == test_case.new_coverage


def test_testcase_create_initial():
    """Test creation of initial test case and its serialization"""
    with tempfile.TemporaryDirectory() as temp_dir:
        queue_dir = os.path.join(temp_dir, "queue")
        os.makedirs(queue_dir, exist_ok=True)
        # Create initial test case
        test_case = TestCase.create_initial(
            id=1,
            exec_code="print('test')",
            execution_trace="initial trace",
            execution_summary="initial summary",
            newly_covered_lines=1,
            out_dir=temp_dir,
        )

        # Verify initial test case properties
        assert test_case.id == 1
        assert test_case.exec_code == "print('test')"
        assert test_case.new_coverage
        assert test_case.newly_covered_lines == 1
        # Confirm file was saved
        yaml_file = os.path.join(queue_dir, "id:000001.yaml")
        assert os.path.exists(yaml_file)

        # Reload and verify
        loaded_case = TestCase.load_from_file(yaml_file, temp_dir)
        assert loaded_case.id == test_case.id
        assert loaded_case.exec_code == test_case.exec_code


def test_time_taken_loading():
    yaml_str = """id: 5
src_id: 3
create_time: '2025-04-16 14:52:16.589'
time_taken: 232
states:
  - SELECT
  - SUMMARIZE
  - SOLVE
  - EXECUTE
  - REVIEW_SOLVER
is_target_covered: false
new_coverage: false
is_satisfiable: true
is_crash: false
is_hang: false
usage: |
  TOTAL:
    model: claude-3-7-sonnet-20250219
    cost: $0.09256080
    call_cnt: 4
    latency: 29.06s
    input_tokens: 85907
    output_tokens: 1522
    cache_read_tokens: 69626
    cache_write_tokens: 0
  SUMMARIZE:
    TOTAL:
      model: claude-3-7-sonnet-20250219
      cost: $0.07532340
      call_cnt: 2
      latency: 14.59s
      input_tokens: 78999
      output_tokens: 736
      cache_read_tokens: 63968
      cache_write_tokens: 0
    generate_path_constraint:
      model: claude-3-7-sonnet-20250219
      cost: $0.03839220
      call_cnt: 1
      latency: 7.72s
      input_tokens: 39656
      output_tokens: 448
      cache_read_tokens: 31984
      cache_write_tokens: 0
    select_target_branch:
      model: claude-3-7-sonnet-20250219
      cost: $0.03693120
      call_cnt: 1
      latency: 6.86s
      input_tokens: 39343
      output_tokens: 288
      cache_read_tokens: 31984
      cache_write_tokens: 0
  SOLVE:
    TOTAL:
      model: claude-3-7-sonnet-20250219
      cost: $0.01723740
      call_cnt: 2
      latency: 14.47s
      input_tokens: 6908
      output_tokens: 786
      cache_read_tokens: 5658
      cache_write_tokens: 0
    INITIAL:
      model: claude-3-7-sonnet-20250219
      cost: $0.00207270
      call_cnt: 0
      latency: 0.00s
      input_tokens: 0
      output_tokens: 0
      cache_read_tokens: 0
      cache_write_tokens: 0
    think:
      model: claude-3-7-sonnet-20250219
      cost: $0.00968970
      call_cnt: 1
      latency: 8.45s
      input_tokens: 3237
      output_tokens: 421
      cache_read_tokens: 2829
      cache_write_tokens: 0
    provide_solution:
      model: claude-3-7-sonnet-20250219
      cost: $0.00547500
      call_cnt: 1
      latency: 6.02s
      input_tokens: 3671
      output_tokens: 365
      cache_read_tokens: 2829
      cache_write_tokens: 0
  EXECUTE:
    TOTAL: {}
target_branch: "case 'R': /* Square Root function. */ -> bc_sqrt (&ex_stack->s_num,
  scale) returns false in execute.c"
target_file_lines: /bc-instr/bc/execute.c:294-295
justification: This branch handles the error case when the square root function is
  called with a negative number. It has 0% coverage in the current execution trace.
  This is an important edge case to test as it's a runtime error condition that should
  be properly handled. The branch is triggered when the square root function is called
  with a negative number, which would result in a runtime error message "Square root
  of a negative number". Testing this branch would ensure that the error handling
  for mathematical operations works correctly, which is crucial for a calculator program
  like bc. This branch is reachable by providing an input that calls the square root
  function with a negative number.
target_path_constraint: |-
  To reach the target branch where `bc_sqrt(&ex_stack->s_num, scale)` returns false in the square root function case 'R', we need to satisfy the following constraints:

  1. Program Execution Path:
     - The program must reach the square root function execution in the switch statement
     - This happens when the instruction 'c' (Call special function) is processed with new_func == 'R'
     - The special function 'R' is executed when the sqrt() function is called in the bc program

  2. Input Value Constraints:
     - The argument to the square root function must be a negative number
     - This will cause bc_sqrt() to return false, triggering the error branch

  The square root function in bc is invoked using the syntax `sqrt(x)` in an expression. When this function is called with a negative number, it should trigger the error branch.

  Therefore, the symbolic constraints for the input are:
  - Input must include a call to the sqrt() function: `sqrt(x)` where x is a negative number
  - The program must be executed with the `-l` option to load the math library that contains the sqrt function
  - The input must be structured so that the expression is evaluated (e.g., by ending the line or using a print statement)

  A simple expression that would satisfy these constraints would be `sqrt(-1)` or any other expression that results in a negative number being passed to the sqrt function.

  The complete path constraint is:
  1. The program must be invoked with the `-l` option to load the math library
  2. The input must contain an expression that calls the sqrt() function with a negative number
  3. The expression must be structured to be evaluated (e.g., by ending the line or using a print statement)
selected_cnt: 0
successful_generation_cnt: 0
exec_code: |-
  def execute_program(timeout: int) -> tuple[str, int]:
      import signal
      import subprocess

      # Modified commands to include a call to sqrt() with a negative number
      commands = ["sqrt(-1)", "quit"]
      input_str = "\\n".join(commands) + "\\n"

      try:
          # ./bc/bc is interactive!
          # Using the -l command line option to load the math library
          result = subprocess.run(
              ["./bc/bc", "-l"],
              input=input_str,
              capture_output=True,
              encoding="utf-8",
              errors="replace",
              timeout=timeout,
          )
          # return stderr and the returncode
          return result.stderr, result.returncode
      except subprocess.TimeoutExpired as e:
          # Timeout occurred, also ensure to return stderr captured before timeout and return code -signal.SIGKILL
          return e.stderr, -signal.SIGKILL
      except Exception as e:
          # ensure to raise the error if run failed
          raise e
returncode: 0
"""
    # test TestCase.load_from_file

    # first write the yaml file
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".yaml", delete=False) as tmp:
        yaml_path = tmp.name
        tmp.write(yaml_str)
        tmp.flush()

    # then load the file
    test_case = TestCase.load_from_file(yaml_path, None)
    assert test_case.time_taken == 232
    assert test_case.states == [
        TestcaseState.SELECT,
        TestcaseState.SUMMARIZE,
        TestcaseState.SOLVE,
        TestcaseState.EXECUTE,
        TestcaseState.REVIEW_SOLVER,
    ]


def test_to_dict_simple():
    """Test to_dict method with a simple TestCase instance"""
    # Create a simple TestCase instance
    test_case = TestCase(
        id=42,
        exec_code="print('Hello, world!')",
        execution_trace="Sample trace",
        src_id=10,
    )

    # Convert to dictionary
    data = test_case.to_dict()

    # Verify basic fields
    assert data["id"] == 42
    assert data["exec_code"] == "print('Hello, world!')"
    assert data["execution_trace"] == "Sample trace"
    assert data["src_id"] == 10

    # Verify private fields are not included
    assert "_out_dir" not in data
    assert "_in_setattr" not in data


def test_from_dict_simple():
    """Test from_dict method with a simple dictionary"""
    # Create a dictionary representation
    data = {
        "id": 42,
        "exec_code": "print('Hello, world!')",
        "execution_trace": "Sample trace",
        "src_id": 10,
        "is_target_covered": True,
    }

    # Convert to TestCase
    test_case = TestCase.from_dict(data)

    # Verify fields
    assert test_case.id == 42
    assert test_case.exec_code == "print('Hello, world!')"
    assert test_case.execution_trace == "Sample trace"
    assert test_case.src_id == 10
    assert test_case.is_target_covered


def test_to_dict_from_dict_roundtrip():
    """Test complete roundtrip conversion between TestCase and dictionary"""
    # Create a complex TestCase instance with all fields
    original = TestCase(
        id=99,
        src_exec_code="original_code()",
        src_execution_trace="parent trace",
        src_execution_summary="parent summary",
        exec_code="modified_code()",
        execution_trace="execution trace",
        execution_summary="detailed summary",
        is_target_covered=True,
        new_coverage=True,
        target_branch="if x > 10:",
        justification="Branch was negated",
        target_path_constraint="x <= 10",
        target_file_lines=("src/main.py", (42, 45)),
        is_satisfiable=True,
        src_id=50,
        create_time=1234567890.0,
        is_crash=False,
        crash_info="",
        states=[
            TestcaseState.SUMMARIZE,
            TestcaseState.EXECUTE,
        ],
    )

    # Convert to dict
    data = original.to_dict()

    # Verify special fields were transformed correctly
    assert data["target_file_lines"] == "src/main.py:42-45"
    assert data["states"] == ["SUMMARIZE", "EXECUTE"]

    # Convert back to TestCase
    restored = TestCase.from_dict(data)

    # Verify all fields match the original
    assert restored.id == original.id
    assert restored.src_exec_code == original.src_exec_code
    assert restored.src_execution_trace == original.src_execution_trace
    assert restored.src_execution_summary == original.src_execution_summary
    assert restored.exec_code == original.exec_code
    assert restored.execution_trace == original.execution_trace
    assert restored.execution_summary == original.execution_summary
    assert restored.is_target_covered == original.is_target_covered
    assert restored.new_coverage == original.new_coverage
    assert restored.target_branch == original.target_branch
    assert restored.justification == original.justification
    assert restored.target_path_constraint == original.target_path_constraint
    assert restored.target_file_lines == original.target_file_lines
    assert restored.is_satisfiable == original.is_satisfiable
    assert restored.src_id == original.src_id
    assert restored.create_time == original.create_time
    assert restored.is_crash == original.is_crash
    assert restored.crash_info == original.crash_info
    assert restored.states == original.states


def test_to_dict_with_special_field_transformations():
    """Test to_dict handles all special field transformations correctly"""
    # Create a TestCase with all special fields that need transformation
    test_case = TestCase(
        id=1,
        target_file_lines=("app/main.py", (10, 20)),
        states=[
            TestcaseState.SUMMARIZE,
            TestcaseState.SOLVE,
            TestcaseState.EXECUTE,
            TestcaseState.REVIEW_SOLVER,
        ],
    )

    # Convert to dict
    data = test_case.to_dict()

    # Verify transformations
    assert data["target_file_lines"] == "app/main.py:10-20"
    assert data["states"] == [
        "SUMMARIZE",
        "SOLVE",
        "EXECUTE",
        "REVIEW_SOLVER",
    ]

    # Convert back to verify bidirectional transformation
    restored = TestCase.from_dict(data)
    assert restored.target_file_lines == ("app/main.py", (10, 20))
    assert restored.states == [
        TestcaseState.SUMMARIZE,
        TestcaseState.SOLVE,
        TestcaseState.EXECUTE,
        TestcaseState.REVIEW_SOLVER,
    ]


def test_yaml_serialization_end_to_end():
    """End-to-end test for YAML serialization and deserialization of TestCase"""
    # Create a TestCase with various field types
    test_case = TestCase(
        id=1,
        exec_code="print('test code')",
        target_file_lines=("app/main.py", (10, 20)),
        states=[TestcaseState.SUMMARIZE, TestcaseState.EXECUTE],
    )

    # Use temporary file for YAML serialization
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".yaml", delete=False) as tmp:
        yaml_path = tmp.name

        # Convert TestCase to dict and then dump to YAML
        data = test_case.to_dict()
        yaml_instance = create_yaml_instance()
        yaml_instance.dump(data, tmp)

    # Verify YAML file contains expected serialized values
    with open(yaml_path) as f:
        content = f.read()
        assert "target_file_lines: app/main.py:10-20" in content
        assert "states:" in content
        assert "- SUMMARIZE" in content
        assert "- EXECUTE" in content

    # Load YAML back into dictionary
    with open(yaml_path) as f:
        yaml_instance = create_yaml_instance()
        loaded_data = yaml_instance.load(f)

    # Verify dictionary has expected values
    assert loaded_data["id"] == 1
    assert loaded_data["exec_code"] == "print('test code')"
    assert loaded_data["target_file_lines"] == "app/main.py:10-20"
    assert loaded_data["states"] == ["SUMMARIZE", "EXECUTE"]

    # Convert back to TestCase
    restored_test_case = TestCase.from_dict(loaded_data)

    # Verify TestCase fields match original
    assert restored_test_case.id == test_case.id
    assert restored_test_case.exec_code == test_case.exec_code
    assert restored_test_case.target_file_lines == test_case.target_file_lines
    assert restored_test_case.states == test_case.states

    # Clean up
    os.unlink(yaml_path)


def test_yaml_serialization_edge_cases():
    """Test YAML serialization with edge cases for target_file_lines and states"""
    test_cases = [
        # Case 1: None values in target_file_lines
        TestCase(id=1, target_file_lines=(None, (None, None)), states=[]),
        # Case 2: Empty states list
        TestCase(id=2, target_file_lines=("path/to/file.py", (1, 100)), states=[]),
        # Case 3: Multiple states including rare ones
        TestCase(
            id=3,
            target_file_lines=("app/complex_path.py", (5, 25)),
            states=[
                TestcaseState.SUMMARIZE,
                TestcaseState.SOLVE,
                TestcaseState.REVIEW_SOLVER,
                TestcaseState.REVIEW_SUMMARY,
            ],
        ),
    ]

    for tc in test_cases:
        # Use temporary file for YAML serialization
        with tempfile.NamedTemporaryFile(
            mode="w+", suffix=".yaml", delete=False
        ) as tmp:
            yaml_path = tmp.name

            # Convert TestCase to dict and then dump to YAML
            data = tc.to_dict()
            yaml_instance = create_yaml_instance()
            yaml_instance.dump(data, tmp)

        # Load YAML back into dictionary and then to TestCase
        with open(yaml_path) as f:
            yaml_instance = create_yaml_instance()
            loaded_data = yaml_instance.load(f)

        restored_tc = TestCase.from_dict(loaded_data)

        # Verify key fields match
        assert restored_tc.id == tc.id
        assert restored_tc.target_file_lines == tc.target_file_lines
        assert restored_tc.states == tc.states

        # Clean up
        os.unlink(yaml_path)
