"""
Tool for executing Python code in an isolated environment.
"""

import binascii  # Import binascii for hex conversion
import os
import subprocess
import tempfile

from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
from loguru import logger

from app.agents.common import filter_instr_print
from app.utils.utils import get_project_dir

EXECUTION_TIMEOUT = 10  # 10 seconds for the Python code execution
MAX_OUTPUT_CHARS = 10000  # Maximum number of characters to return from stdout/stderr

_PYTHON_EXECUTOR_DESCRIPTION = f"""Use this tool to execute Python code in an isolated environment. This is an INTERMEDIATE tool used to obtain some intermediate results or conclusions. This tool is NOT used to provide the final solution.

This is useful for testing or validating code snippets, especially when:
- You need to verify code behavior or output
- You want to test different approaches to solving constraints
- You need to perform complex calculations

The Python code will be executed in a sandboxed environment with a {EXECUTION_TIMEOUT}-second timeout.
The tool returns the STANDARD OUTPUT of the execution, or an error message if execution fails.

Note: 
- The execution environment is isolated for each call. State is not preserved between calls.
- Use this tool wisely and only call when necessary, e.g., when you need to compute a result that is not directly provided by the other tools.
- Avoid using this tool for large outputs. For large outputs, only the first {MAX_OUTPUT_CHARS} characters of STDOUT/STDERR will be returned.
"""

# Define the Python executor tool
PythonExecutorTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="execute_python",
        description=_PYTHON_EXECUTOR_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "python_code": {
                    "type": "string",
                    "description": "The complete Python code to execute.",
                }
            },
            "required": ["python_code"],
        },
    ),
)


# Helper function to safely decode byte streams and truncate if necessary
def _safe_decode_with_truncation(byte_stream: bytes | None) -> tuple[str, str | None]:
    """
    Attempts to decode a byte stream using UTF-8. If decoding fails,
    it returns a lossy representation (using 'replace') and the hex dump of the original bytes.
    Both outputs are truncated if too long.

    Args:
        byte_stream: The byte stream to decode.

    Returns:
        A tuple containing:
        - The decoded string (potentially lossy and truncated).
        - The hex dump string if decoding encountered errors (truncated), otherwise None.
    """
    if not byte_stream:
        return "", None  # Return empty string, no hex needed

    try:
        # Try strict decoding first to detect errors
        decoded_string = byte_stream.decode("utf-8", errors="strict")
        # Truncate if necessary
        if len(decoded_string) > MAX_OUTPUT_CHARS:
            decoded_string = decoded_string[:MAX_OUTPUT_CHARS]
            decoded_string += (
                f"\n[... output truncated after {MAX_OUTPUT_CHARS} characters ...]"
            )
        return decoded_string, None  # Success, no hex dump needed
    except UnicodeDecodeError:
        # Decoding failed, decode again with replacement characters
        lossy_string = byte_stream.decode("utf-8", errors="replace")
        # Truncate if necessary
        if len(lossy_string) > MAX_OUTPUT_CHARS:
            lossy_string = lossy_string[:MAX_OUTPUT_CHARS]
            lossy_string += (
                f"\n[... output truncated after {MAX_OUTPUT_CHARS} characters ...]"
            )

        # Get the hex dump
        hex_representation = binascii.hexlify(byte_stream).decode("ascii")
        # Truncate hex - allow twice as many characters since each byte becomes two hex chars
        hex_limit = MAX_OUTPUT_CHARS * 2
        if len(hex_representation) > hex_limit:
            hex_representation = hex_representation[:hex_limit]
            hex_representation += (
                f"\n[... hex output truncated after {hex_limit} characters ...]"
            )

        # Return the lossy string AND the hex dump
        return lossy_string, hex_representation


def _format_execution_error(
    initial_msg: str, stdout_bytes: bytes | None, stderr_bytes: bytes | None
) -> str:
    """
    Formats the error message for failed or timed-out Python execution,
    including decoded output/error and hex dumps if decoding failed.

    Args:
        initial_msg: The starting error message (e.g., timeout, non-zero return code).
        stdout_bytes: The raw stdout bytes.
        stderr_bytes: The raw stderr bytes.

    Returns:
        The formatted error message string.
    """
    error_msg = initial_msg + "\n"

    # Decode and process stdout
    stdout_str, stdout_hex_dump = _safe_decode_with_truncation(stdout_bytes)
    if stdout_str.strip():
        error_msg += f"--- stdout captured ---\n{stdout_str}\n"
    if stdout_hex_dump:
        error_msg += f"--- stdout captured (in hex) ---\n{stdout_hex_dump}\n"

    # Decode, filter, and process stderr
    stderr_str, _ = _safe_decode_with_truncation(stderr_bytes)
    if stderr_str:
        filtered_stderr = filter_instr_print(stderr_str)

        if filtered_stderr.strip():
            error_msg += f"--- stderr captured ---\n{filtered_stderr}"

    return error_msg


def process_python_executor(python_code: str | None) -> tuple[str, bool]:
    """
    Process Python executor tool by running the provided code in an isolated environment.

    Args:
        python_code: The Python code to execute

    Returns:
        Tuple of (result message, execution_success)
    """
    if python_code is None or python_code.strip() == "":
        logger.warning("No `python_code` provided or it is empty.")
        return (
            "Error: No `python_code` provided or it is empty. Please provide a valid and complete `python_code`.",
            False,
        )

    temp_file = None

    logger.debug("LLM requested to execute Python code:\n{}", python_code)

    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(python_code)
            f.flush()
            temp_file = f.name

        # Get project directory if set
        project_dir = get_project_dir()
        if project_dir:
            logger.debug("Using project directory: {}", project_dir)
        else:
            logger.debug("No project directory set, using current directory")

        # Execute code in subprocess with specified working directory
        result = subprocess.run(
            ["python3", temp_file],
            capture_output=True,  # Capture raw bytes
            timeout=EXECUTION_TIMEOUT,
            cwd=(
                project_dir if project_dir else None
            ),  # Use project_dir as working directory if set
        )

        # Decode stdout and stderr safely
        stdout_str, stdout_hex_dump = _safe_decode_with_truncation(result.stdout)

        if result.returncode == 0:
            result_msg = "Python execution succeeded.\n"

            if stdout_str.strip():
                result_msg += f"--- stdout captured ---\n{stdout_str}\n"

            if stdout_hex_dump:
                result_msg += f"--- stdout captured (in hex) ---\n{stdout_hex_dump}\n"

            logger.info(
                f"Python execution succeeded. stdout length: {len(stdout_str)}, hex dump generated: {stdout_hex_dump is not None}"
            )
            return result_msg, True
        else:
            # Format error using the helper function
            error_msg = _format_execution_error(
                f"Python execution failed with return code {result.returncode}.\n",
                result.stdout,
                result.stderr,
            )
            logger.info(error_msg)
            return error_msg, False

    except subprocess.TimeoutExpired as e:
        # Format error using the helper function
        error_msg = _format_execution_error(
            f"Python execution timeout ({EXECUTION_TIMEOUT} seconds) and was killed. Please divide the complex code into sub-tasks.\n",
            e.stdout,
            e.stderr,
        )
        logger.info(error_msg)
        return error_msg, False
    except Exception as e:
        error_msg = f"Python execution error: {str(e)}"
        logger.warning(error_msg)
        return error_msg, False
    finally:
        # Clean up temporary file if it exists
        if temp_file:
            try:
                os.unlink(temp_file)
            except OSError:
                pass  # Ignore deletion errors
