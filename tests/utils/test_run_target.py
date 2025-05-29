import os
import signal

import pytest

from app.utils.utils import STDERR_TRUNCATE_LENGTH, run_target


def test_normal_execution():
    """Test normal execution without any crashes or errors."""
    code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    try:
        result = subprocess.run(
            ["echo", "Hello, World!"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.stderr, result.returncode
    except Exception as e:
        raise e
    """
    result = run_target(code, timeout=1)
    assert result["exec_success"] is True
    assert result["target_crashed"] is False
    assert result["target_return_code"] == 0
    assert result["exec_error"] is None
    assert result["target_timeout"] is False


def test_syntax_error():
    """Test execution with syntax error."""
    code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    try:
        result = subprocess.run(
            ["echo", "Hello, World!"  # Missing closing parenthesis
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.stderr, result.returncode
    except Exception as e:
        raise e
    """
    result = run_target(code, timeout=1)
    assert result["exec_success"] is False
    assert result["target_crashed"] is False
    assert result["target_return_code"] is None
    assert "closing parenthesis" in result["exec_error"]
    assert result["target_timeout"] is False


def test_non_zero_exit_code():
    """Test execution with non-zero exit code but no crash."""
    code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    try:
        result = subprocess.run(
            ["python3", "-c", "import sys; sys.exit(1)"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.stderr, result.returncode
    except Exception as e:
        raise e
    """
    result = run_target(code, timeout=1)
    print(result)
    assert result["exec_success"] is True
    assert result["target_crashed"] is False
    assert result["target_return_code"] == 1
    assert result["exec_error"] is None
    assert result["target_stderr"] == ""
    assert result["target_timeout"] is False


def test_segmentation_fault():
    """Test execution with segmentation fault."""
    code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    try:
        result = subprocess.run(
            ["python3", "-c", "import ctypes; ctypes.string_at(0xdeadbeef)"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.stderr, result.returncode
    except Exception as e:
        raise e
    """
    result = run_target(code, timeout=3)
    assert result["exec_success"] is True
    assert result["target_crashed"] is True
    assert result["target_return_code"] == -signal.SIGSEGV
    assert "SIGSEGV" in result["target_crash_reason"]
    assert result["target_timeout"] is False


@pytest.mark.skipif(
    not os.path.exists("/usr/bin/gcc"), reason="No C compiler available"
)
def test_asan_crash():
    """Test detection of ASAN crashes if C compiler is available."""
    code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    import tempfile
    import os
    import signal

    # Create a C program that causes ASAN crash
    c_code = '''
    #include <stdio.h>
    #include <stdlib.h>

    int main() {
        fprintf(stderr, "Hello, World!");
        sleep(2);
        int a[10];
        int b = a[10];  // Buffer overflow
        return 0;
    }
    '''

    # Write C code to temporary file
    with tempfile.NamedTemporaryFile(suffix='.c') as f:
        c_file = f.name
        f.write(c_code.encode())
        f.flush()

        try:
            # Compile with ASAN
            subprocess.run(['gcc', '-fsanitize=address', '-o', 'test_asan', c_file], check=True)
            
            # Run the program
            result = subprocess.run(
                ['./test_asan'],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            return result.stderr, result.returncode
        except subprocess.TimeoutExpired as e:
            return e.stderr, -signal.SIGKILL
        except Exception as e:
            raise e
    """
    result = run_target(code, timeout=4)
    assert result["exec_success"] is True
    assert result["target_crashed"] is True
    assert result["target_return_code"] == -signal.SIGABRT
    assert (
        "Hello, World!" in result["target_stderr"]
    )  # ensure the stderr before crash is kept
    assert "AddressSanitizer" in result["target_stderr"]
    assert result["target_timeout"] is False

    result = run_target(code, timeout=1)
    assert result["exec_success"] is True
    assert result["target_crashed"] is False
    assert "Hello, World!" in result["target_stderr"]
    assert result["target_return_code"] == -signal.SIGKILL
    assert result["target_timeout"] is True


def test_invalid_command():
    """Test execution with invalid command."""
    code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    try:
        result = subprocess.run(
            ["non_existent_command"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.stderr, result.returncode
    except Exception as e:
        raise e
    """
    result = run_target(code, timeout=1)
    assert result["exec_success"] is False
    assert result["target_crashed"] is False
    assert result["target_return_code"] is None
    assert "No such file or directory" in result["exec_error"]
    assert result["target_timeout"] is False


def test_return_only_stderr():
    """Test execution with invalid command."""
    code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    try:
        result = subprocess.run(
            ["ls"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.stderr
    except Exception as e:
        raise e
    """
    result = run_target(code, timeout=1)
    assert result["exec_success"] is False
    assert result["target_crashed"] is False
    assert result["target_return_code"] is None
    assert "Invalid return value type" in result["exec_error"]
    assert result["target_timeout"] is False


def test_return_invalid_return_code():
    """Test execution with invalid command."""
    code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    try:
        result = subprocess.run(
            ["ls"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.stderr, result.stderr
    except Exception as e:
        raise e
    """
    result = run_target(code, timeout=1)
    print(result)
    assert result["exec_success"] is False
    assert result["target_crashed"] is False
    assert result["target_return_code"] is None
    assert "Invalid return_code type" in result["exec_error"]
    assert result["target_timeout"] is False


def test_return_invalid_stderr():
    """Test execution with invalid command."""
    code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    try:
        result = subprocess.run(
            ["ls"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return 1, 1
    except Exception as e:
        raise e
    """
    result = run_target(code, timeout=1)
    print(result)
    assert result["exec_success"] is False
    assert result["target_crashed"] is False
    assert result["target_return_code"] is None
    assert "Invalid stderr type" in result["exec_error"]
    assert result["target_timeout"] is False


def test_timeout():
    """Test execution with timeout."""
    code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import time
    time.sleep(5)  # Sleep for 5 seconds to trigger timeout
    return "", 0
    """
    result = run_target(
        code, timeout=1
    )  # Set timeout to 1 second. However, the target code will not exit even after 2 seconds
    assert result["exec_success"] is True
    assert result["target_crashed"] is False
    assert result["target_return_code"] is None
    assert result["target_timeout"] is True
    assert result["exec_error"] is None


def test_normal_execution_without_timeout():
    """Test normal execution without timeout."""
    code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import time
    time.sleep(timeout)
    return "", 0
    """
    result = run_target(code, timeout=2)
    assert result["exec_success"] is True
    assert result["target_crashed"] is False
    assert result["target_return_code"] == 0
    assert result["target_timeout"] is False
    assert result["exec_error"] is None


def test_parallel_execution_with_timeout():
    """Test parallel execution with different timeouts."""
    import concurrent.futures

    def create_sleep_code(sleep_time: int) -> str:
        return f"""
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    import signal
    try:
        result = subprocess.run(
            ["python3", "-c", "import time; time.sleep({sleep_time})"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.stderr, result.returncode
    except subprocess.TimeoutExpired as e:
        return e.stderr, -signal.SIGKILL
    except Exception as e:
        raise e
    """

    # Create test cases with different sleep times
    test_cases = [
        (create_sleep_code(1), 2),  # Should complete
        (
            create_sleep_code(3),
            1,
        ),  # Should timeout but should still return stderr and return code
        (create_sleep_code(2), 3),  # Should complete
    ]

    # Run tests in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(run_target, code, timeout=timeout)
            for code, timeout in test_cases
        ]
        results = [future.result() for future in futures]

    # Verify results
    assert results[0]["exec_success"] is True
    assert results[0]["target_timeout"] is False
    assert results[0]["target_return_code"] == 0

    assert results[1]["exec_success"] is True
    assert results[1]["target_timeout"] is True
    assert results[1]["target_return_code"] == -signal.SIGKILL
    assert results[1]["target_stderr"] == ""

    assert results[2]["exec_success"] is True
    assert results[2]["target_timeout"] is False
    assert results[2]["target_return_code"] == 0


def test_parallel_execution_with_crash():
    """Test parallel execution with crash and timeout."""
    import concurrent.futures

    # Create test cases
    crash_code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    try:
        result = subprocess.run(
            ["python3", "-c", "import ctypes; ctypes.string_at(0xdeadbeef)"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.stderr, result.returncode
    except Exception as e:
        raise e
    """

    timeout_code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    import signal
    try:
        result = subprocess.run(
            ["python3", "-c", "import time; time.sleep(3)"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.stderr, result.returncode
    except subprocess.TimeoutExpired as e:
        return e.stderr, -signal.SIGKILL
    except Exception as e:
        raise e
    """

    # Run tests in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(run_target, crash_code, timeout=5),
            executor.submit(run_target, timeout_code, timeout=1),
        ]
        results = [future.result() for future in futures]

    # Verify crash result
    assert results[0]["exec_success"] is True
    assert results[0]["target_timeout"] is False
    assert results[0]["target_crashed"] is True
    assert "SIGSEGV" in results[0]["target_crash_reason"]

    # Verify timeout result
    assert results[1]["exec_success"] is True
    assert results[1]["target_timeout"] is True
    assert results[1]["target_crashed"] is False
    assert results[1]["target_return_code"] == -signal.SIGKILL


def test_parallel_execution_with_syntax_error():
    """Test parallel execution with syntax error and normal execution."""
    import concurrent.futures

    # Create test cases
    syntax_error_code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    try:
        result = subprocess.run(
            ["python3", "-c", "print('Hello')",  # Missing closing parenthesis
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.stderr, result.returncode
    except Exception as e:
        raise e
    """

    normal_code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    try:
        result = subprocess.run(
            ["echo", "Hello, World!"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.stderr, result.returncode
    except Exception as e:
        raise e
    """

    # Run tests in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(run_target, syntax_error_code, timeout=5),
            executor.submit(run_target, normal_code, timeout=5),
        ]
        results = [future.result() for future in futures]

    # Verify syntax error result
    assert results[0]["exec_success"] is False
    assert results[0]["target_timeout"] is False
    assert "closing parenthesis" in results[0]["exec_error"]

    # Verify normal execution result
    assert results[1]["exec_success"] is True
    assert results[1]["target_timeout"] is False
    assert results[1]["target_return_code"] == 0


def test_stderr_truncation():
    """Test that when stderr exceeds STDERR_TRUNCATE_LENGTH, it is truncated and a truncation message is added."""
    code = """
def execute_program(timeout: int) -> tuple[str, int]:
    import subprocess
    
    try:
        # generate a string that exceeds the truncation length, here directly write the length value
        cmd = "import sys; s = 'x' * {0}; sys.stderr.write(s)"
        
        # run the Python command to generate a large stderr output
        result = subprocess.run(
            ["python3", "-c", cmd.format({0})],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.stderr, result.returncode
    except Exception as e:
        raise e
    """.format(
        STDERR_TRUNCATE_LENGTH + 100000
    )

    result = run_target(code, timeout=5)

    assert result["exec_success"] is True
    assert result["target_crashed"] is False
    assert result["target_return_code"] == 0
    assert result["exec_error"] is None
    assert result["target_timeout"] is False

    # verify the stderr is truncated to STDERR_TRUNCATE_LENGTH
    assert (
        result["target_stderr"]
        == "x" * (STDERR_TRUNCATE_LENGTH) + "... and more (truncated)"
    )
