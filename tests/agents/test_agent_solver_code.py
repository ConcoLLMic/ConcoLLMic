import pytest

from app.agents.tools.python_executor import process_python_executor


def test_process_python_executor_success():
    """Test successful Python code execution"""
    code = """
print('Hello, World!')
"""
    output, success = process_python_executor(code)
    assert success
    assert output.split("--- stdout captured ---\n")[1].strip() == "Hello, World!"


def test_process_python_executor_with_calculation():
    """Test Python code with calculation"""
    code = """
result = 2 + 3
print(f'Result: {result}')
"""
    output, success = process_python_executor(code)
    assert success
    assert output.split("--- stdout captured ---\n")[1].strip() == "Result: 5"


def test_process_python_executor_invalid_code():
    """Test invalid UTF-8 input"""
    code = """
print(b"\xff\xfe\x80This is not valid UTF-8\xff".decode("utf-8"))
"""
    _, success = process_python_executor(code)
    assert not success


def test_process_python_executor_syntax_error():
    """Test syntax error case"""
    code = """
print('Hello'
"""
    output, success = process_python_executor(code)
    assert not success
    assert "SyntaxError" in output


def test_process_python_executor_timeout():
    """Test code execution timeout"""
    code = """
import time
while True:
    time.sleep(1)
"""
    output, success = process_python_executor(code)
    assert not success
    assert "timeout" in output.lower()


def test_process_python_executor_runtime_error():
    """Test runtime error case"""
    code = """
x = 1 / 0
"""
    output, success = process_python_executor(code)
    assert not success
    assert "ZeroDivisionError" in output


def test_process_python_executor_with_imports():
    """Test code with import statements"""
    code = """
import math
print(math.pi)
"""
    output, success = process_python_executor(code)
    assert success
    assert float(output.split("--- stdout captured ---\n")[1].strip()) == pytest.approx(
        3.14159, rel=1e-5
    )


def test_process_python_executor_with_multiline_output():
    """Test multiline output case"""
    code = """
for i in range(3):
    print(f'Line {i}')
"""
    output, success = process_python_executor(code)
    assert success
    expected_output = "Line 0\nLine 1\nLine 2"
    assert output.split("--- stdout captured ---\n")[1].strip() == expected_output
