import difflib
import io
import multiprocessing
import os
import re
import signal
import struct
import sys
import time
from typing import Any

from anthropic import Anthropic
from loguru import logger

PROJECT_DIR = ""
CONCOLIC_EXECUTION_START_TIME: None | float = None

STDERR_TRUNCATE_LENGTH = (
    200000  # if the stderr is too long, the process communication will hang
)


def update_project_dir(project_dir: str):
    global PROJECT_DIR
    PROJECT_DIR = os.path.normpath(project_dir)
    logger.info("Project directory {}", PROJECT_DIR)


def get_project_dir() -> str:
    global PROJECT_DIR
    return PROJECT_DIR


def update_ce_start_time(start_time: float):
    global CONCOLIC_EXECUTION_START_TIME
    CONCOLIC_EXECUTION_START_TIME = start_time


def get_time_taken() -> int:
    global CONCOLIC_EXECUTION_START_TIME
    if CONCOLIC_EXECUTION_START_TIME is None:
        return 0
    else:
        return int(time.time() - CONCOLIC_EXECUTION_START_TIME)


def strip_qoutes(code_str: str, language: str) -> str:
    return code_str.lstrip(f"\n```{language}\n").rstrip("```\n")


def add_qoutes(code_str: str, language: str) -> str:
    return f"\n```{language}\n{code_str}\n```\n"


# Reads source lines from a file, indexed by line numbers
def load_code_from_file(file_path: str) -> dict[int, str]:
    global PROJECT_DIR
    if not os.path.exists(file_path):
        if os.path.exists(os.path.join(PROJECT_DIR, file_path)):
            file_path = os.path.join(PROJECT_DIR, file_path)
        else:
            logger.error("File not found: {}", file_path)
            raise FileNotFoundError
    lines_dict = {}
    logger.info("Loading file from {}", file_path)
    with open(file_path) as file:
        for index, line in enumerate(file, start=1):
            lines_dict[index] = line.rstrip("\n")
    return lines_dict


# Format indexed code as a string
def format_code(
    source_code: dict[int, str],
    source_language: str,
    numbered=False,
    qouted=False,
    range: tuple[int, int] = None,
    line2cov: dict[int, int] = None,
    numbering_style="comment",  # New parameter: "comment" (end of line) or "prefix" (cat -n style)
) -> str:
    """
    source_code: a dict of line number (indexed by 1) to line content
    source_language: the language of the source code
    numbered: whether to add line numbers to the code
    qouted: whether to add quotes to the code
    range: a tuple of start and end line numbers to filter the code (indexed by 1)
    line2cov: a dict of line number (indexed by 1) to its covered times, enabled only when numbered=True and numbering_style="prefix"
    numbering_style: how to display line numbers when numbered=True
        - "comment": add line numbers as comments at the end of each line (original behavior)
        - "prefix": add line numbers at the beginning of each line (like `cat -n`)
    """

    if range:
        start, end = range
        source_code = {k: v for k, v in source_code.items() if start <= k <= end}

    if numbered:
        code_lines = []
        # Find the maximum line number to determine padding for prefix style
        max_line_num = max(source_code.keys()) if source_code else 0
        padding = len(str(max_line_num))

        if numbering_style == "prefix":
            # New behavior: line numbers as prefix (cat -n style)
            for line_num, code in source_code.items():
                if line2cov:
                    if line_num not in line2cov:
                        logger.error("Line number {} not found in line2cov", line_num)
                    cov_str = "+" if line2cov.get(line_num, 0) > 0 else "-"
                    code_lines.append(f"{line_num:>{padding}}| {cov_str}| {code}")
                else:
                    code_lines.append(f"{line_num:>{padding}} {code}")
        else:
            # Default to original behavior if invalid style specified
            for key, value in source_code.items():
                if value.strip():
                    code_lines.append(
                        f"{value} {get_comment_token(source_language)} line no: {key}"
                    )
                else:
                    code_lines.append(f"{value}")

        code_str = "\n".join(code_lines)
    else:
        code_str = "\n".join(f"{value}" for key, value in source_code.items())
    if qouted:
        return add_qoutes(code_str, source_language)
    else:
        return code_str


# Executes the give Python code and returns the output that would have been printed to stdout
def exec_code(code: str) -> str:
    # store the original stdout
    original_stdout = sys.stdout

    # Create a StringIO object to capture output
    output = io.StringIO()

    # Redirect stdout to StringIO object
    sys.stdout = output

    # Executing the code
    exec(
        code, {"struct": struct}
    )  # Need to import the modules that are used in the code

    # restore sys.stdout to default value
    sys.stdout = original_stdout

    # Read and print the captured output
    captured_output = output.getvalue()
    return captured_output


# Model-generated code execution error
class TargetExecutionError(Exception):
    """
    Custom exception to differentiate between exceptions from target code execution and exceptions from the higher-level program.
    """

    def __init__(self, original_exception, func_name):
        self.original_exception = original_exception
        super().__init__(f"`{func_name}` execution error:\n{original_exception}")


def _execute_target(
    pipe_conn,
    code: str,
    func_name: str,
    timeout: int,
    enable_sanitizer_env: bool,
    project_dir: str | None,
):
    """Target function to be executed in a separate process."""
    # save current working directory before potentially changing it
    original_cwd = os.getcwd()
    try:
        # if the project directory is set, then change to the project directory
        if project_dir:
            os.chdir(project_dir)
            logger.debug("Child process changed working directory to {}", project_dir)
        else:
            logger.debug(
                "No project directory set, working directory is {}", os.getcwd()
            )

        if enable_sanitizer_env:
            # Set up ASAN and UBSAN environment variables
            asan_options = [
                "abort_on_error=1",
                "detect_leaks=0",
                "symbolize=1",
                "allocator_may_return_null=1",
                "detect_stack_use_after_return=1",
                "handle_segv=0",
                "handle_sigbus=0",
                "handle_abort=0",
                "handle_sigfpe=0",
                "handle_sigill=0",
            ]

            os.environ["ASAN_OPTIONS"] = " ".join(asan_options)

            ubsan_options = [
                "print_stacktrace=1",
                "halt_on_error=1",
                "abort_on_error=1",
                "malloc_context_size=0",
                "allocator_may_return_null=1",
                "symbolize=1",
                "handle_segv=0",
                "handle_sigbus=0",
                "handle_abort=0",
                "handle_sigfpe=0",
                "handle_sigill=0",
            ]
            os.environ["UBSAN_OPTIONS"] = " ".join(ubsan_options)

        # Execute the code
        namespace = {}
        exec(code, namespace)

        # if the function 'func_name' is defined in the code, call it and send the result
        if func_name in namespace:
            result = namespace[func_name](timeout)

            # process the return value
            if isinstance(result, tuple) and len(result) == 2:
                stderr, return_code = result
            else:
                raise ValueError(
                    f"Invalid return value type: {type(result)}. The function {func_name} should return a tuple of (stderr, return_code), where stderr is a string or bytes, and return_code is an integer."
                )

            if stderr is not None:
                if not (isinstance(stderr, bytes) or isinstance(stderr, str)):
                    raise ValueError(
                        f"Invalid stderr type: {type(stderr)}. The function {func_name} should return a tuple of (stderr, return_code), where stderr is a string or bytes."
                    )
                if not isinstance(return_code, int):
                    raise ValueError(
                        f"Invalid return_code type: {type(return_code)}. The function {func_name} should return a tuple of (stderr, return_code), where return_code is an integer."
                    )
                if isinstance(stderr, bytes):  # ensure the stderr is a string
                    stderr = stderr.decode("utf-8", errors="replace")
                if len(stderr) > STDERR_TRUNCATE_LENGTH:
                    logger.info("stderr is too long and has been truncated")
                    stderr = (
                        stderr[:STDERR_TRUNCATE_LENGTH] + "... and more (truncated)"
                    )
            else:
                logger.info("stderr is empty")
                stderr = ""  # convert None to empty string
            pipe_conn.send((stderr, return_code))
        else:
            raise ValueError(f"Function {func_name} not found in code")

    except Exception as e:
        # Send exception back to parent process
        pipe_conn.send(e)
    finally:
        # restore the original working directory
        if original_cwd:
            os.chdir(original_cwd)
            logger.debug("Restored working directory to {}", original_cwd)
        pipe_conn.close()


def exec_code_function(
    code: str, func_name: str, timeout: int, enable_sanitizer_env: bool
) -> tuple[str, int]:
    """
    Executes the given code string in a separate process, calls the specified function,
    and returns its result. Includes timeout and isolation.
    """
    parent_conn, child_conn = multiprocessing.Pipe()
    target_project_dir = get_project_dir()  # Get project dir in parent process

    process = multiprocessing.Process(
        target=_execute_target,
        args=(
            child_conn,
            code,
            func_name,
            timeout,
            enable_sanitizer_env,
            target_project_dir,
        ),
    )
    process.start()
    child_conn.close()  # Close child end in parent

    # Wait for the process to finish or timeout
    process.join(timeout * 2)

    if process.is_alive():
        # Process timed out
        logger.warning(
            "Process execution timed out after {} seconds. Terminating.", timeout * 2
        )
        try:
            # Kill the process
            if hasattr(process, "kill"):
                process.kill()
            else:
                os.kill(process.pid, signal.SIGKILL)

            # Wait briefly for termination
            process.join(1)

            # Check if process is still alive
            if process.is_alive():
                logger.error(
                    f"Process {process.pid} did not terminate after kill signal"
                )
        except Exception as kill_err:
            logger.error(f"Error killing process {process.pid}: {kill_err}")
        finally:
            # Always close connection and raise timeout error
            parent_conn.close()
            raise TimeoutError(f"Execution timed out after {timeout*2} seconds")

    # Process finished within timeout, attempt to get the result
    logger.debug("Child process finished with exit code: {}", process.exitcode)

    result = None
    try:
        if parent_conn.poll():  # Check if there's data to receive
            result = parent_conn.recv()
        else:
            raise RuntimeError("Child process exited without sending any data")
    except EOFError:
        # Child process terminated abnormally without sending result through pipe.
        # Possible causes: killed by signal, C extension crash, os._exit() called, etc.
        raise TargetExecutionError(
            RuntimeError(
                f"Child process terminated abnormally (exit code: {process.exitcode}) "
                "without sending result through pipe."
            ),
            func_name,
        )
    finally:
        # Ensure the pipe connection is closed from the parent side
        parent_conn.close()

    # Check if the received result is an exception sent by the child
    if isinstance(result, Exception):
        raise TargetExecutionError(result, func_name)
    else:
        if isinstance(result, tuple):
            return result
        else:
            raise RuntimeError(
                f"Unexpected result type: {type(result)}, value: {result}"
            )


def restore_deleted_blocks(original_content: str, instrumented_content: str) -> str:
    """
    Compare original code and instrumented code to find and restore code blocks that were deleted

    Args:
        original_content (str): Original code content
        instrumented_content (str): Instrumented code content

    Returns:
        str: Code content after restoring deleted blocks
    """

    # Split content into lines
    original_lines = original_content.splitlines(keepends=True)
    instrumented_lines = instrumented_content.splitlines(keepends=True)

    # Create diff comparison
    differ = difflib.Differ()
    diff = list(differ.compare(original_lines, instrumented_lines))

    # Store lines to restore and their positions
    blocks_to_restore = []
    current_block = []
    line_num_to_restore = (
        0  # Start line number in instrumented code where block needs to be restored
    )
    is_valid_block = True

    # Find code blocks that were only deleted without any changes
    for line in diff:
        if line.startswith("- "):
            if not current_block:
                block_start = line_num_to_restore
            current_block.append(line[2:])
        elif line.startswith("+ "):
            # If we encounter an added line while collecting deleted block, this is not a pure deletion
            is_valid_block = False
            line_num_to_restore += 1
        elif line.startswith("  "):
            if current_block and is_valid_block:
                blocks_to_restore.append((block_start, current_block[:]))
            current_block = []
            is_valid_block = True
            line_num_to_restore += 1

    # Handle the last block
    if current_block and is_valid_block:
        blocks_to_restore.append((block_start, current_block))

    # Restore deleted blocks
    result_lines = instrumented_lines[:]

    # Process each block to restore from back to front
    for block_start, block in reversed(blocks_to_restore):
        # Insert deleted block directly at recorded position
        for line in reversed(block):
            result_lines.insert(block_start, line)

    return "".join(result_lines)


def detect_language(file_path: str) -> str | None:
    """
    Detect the programming language of a file based on its extension.

    Args:
        file_path (str): Path to the file

    Returns:
        str or None: The detected programming language or None if not a recognized code file
    """
    # Get the file extension
    _, ext = os.path.splitext(file_path.lower())

    # Remove the dot from extension
    ext = ext[1:] if ext.startswith(".") else ext

    # Map of file extensions to programming languages
    language_map = {
        # C/C++
        "c": "c",
        "cpp": "cpp",
        "cc": "cpp",
        "h": "cpp",
        "hpp": "cpp",
        # Python
        "py": "python",
        "pyw": "python",
        # Java
        "java": "java",
        # C#
        "cs": "csharp",
        # Ruby
        "rb": "ruby",
        # Go
        "go": "go",
        # Rust
        "rs": "rust",
        # JavaScript
        "js": "javascript",
        "jsx": "javascript",
        # TypeScript
        "ts": "typescript",
        "tsx": "typescript",
        # PHP
        "php": "php",
        # Swift
        "swift": "swift",
        # Kotlin
        "kt": "kotlin",
        "kts": "kotlin",
        # Scala
        "scala": "scala",
        # Shell scripts
        "sh": "bash",
        "bash": "bash",
        "zsh": "bash",
        # PowerShell
        "ps1": "powershell",
        # HTML
        "html": "html",
        "htm": "html",
        # CSS
        "css": "css",
        # SQL
        "sql": "sql",
        # Other languages
        "l": "lex",
        "y": "yacc",
        "pl": "perl",
        "r": "r",
        "lua": "lua",
        "hs": "haskell",
        "f": "fortran",
        "f90": "fortran",
        "f95": "fortran",
        "m": "matlab",
    }

    language = None
    # Check if the extension is recognized
    if len(ext) > 0:
        language = language_map.get(ext)
        if language is None:
            logger.warning(f"Unknown file extension: {ext}")

    return language


def get_comment_token(language: str | None) -> str:
    """
    Get the comment token for a specific programming language.

    Args:
        language (str): The programming language

    Returns:
        str: The comment token for the language, defaults to '#' if not found
    """

    # Map of programming languages to their comment tokens
    COMMENT_TOKENS = {
        # C-style comments
        "c": "//",
        "cpp": "//",
        "csharp": "//",
        "java": "//",
        "javascript": "//",
        "typescript": "//",
        "php": "//",
        "go": "//",
        "swift": "//",
        "rust": "//",
        "kotlin": "//",
        "scala": "//",
        "lex": "//",
        "css": "/*",  # CSS primarily uses /* */ for comments
        # Hash comments
        "python": "#",
        "bash": "#",
        "ruby": "#",
        "perl": "#",
        "r": "#",
        # Double-dash comments
        "sql": "--",
        "lua": "--",
        "haskell": "--",
        # Other comment styles
        "fortran": "!",
        "matlab": "%",
        # HTML/CSS comments are multi-line and not included here
        # Aliases for compatibility with detect_language
        "c++": "//",
        "c#": "//",
        "js": "//",
        "ts": "//",
        "py": "#",
        "shell": "#",
    }

    if language is None:
        logger.warning("language is None, returning '#' as default comment token")
        return "#"  # Default to # for unknown languages

    language = language.lower()
    if language not in COMMENT_TOKENS:
        logger.warning(
            "Unknown comment token for language '{}', returning '#' as default",
            language,
        )
        return "#"  # Default to # for unknown languages
    else:
        return COMMENT_TOKENS[language]


def get_multiline_comment_tokens(language: str) -> tuple[str, str] | tuple[None, None]:
    """
    Get the multiline comment tokens for a specific programming language.

    Args:
        language (str): The programming language

    Returns:
        tuple[str, str]: A tuple containing the start and end tokens of multiline comments.
                        Returns (None, None) if the language doesn't support multiline comments.
    """
    # Map of programming languages to their multiline comment tokens
    MULTILINE_COMMENT_TOKENS = {
        # C-style block comments /* */
        "c": ("/*", "*/"),
        "cpp": ("/*", "*/"),
        "csharp": ("/*", "*/"),
        "java": ("/*", "*/"),
        "javascript": ("/*", "*/"),
        "typescript": ("/*", "*/"),
        "php": ("/*", "*/"),
        "go": ("/*", "*/"),
        "rust": ("/*", "*/"),
        "swift": ("/*", "*/"),
        "kotlin": ("/*", "*/"),
        "scala": ("/*", "*/"),
        "css": ("/*", "*/"),
        "lex": ("/*", "*/"),
        "yacc": ("/*", "*/"),
        # Triple quotes for Python and others
        "python": ('"""', '"""'),
        # HTML style comments <!-- -->
        "html": ("<!--", "-->"),
        # ML-family languages (* *)
        "haskell": ("{-", "-}"),
        # Other languages
        "sql": ("/*", "*/"),
        "lua": ("--[[", "]]"),
        "ruby": ("=begin", "=end"),
        "perl": ("=pod", "=cut"),
        "r": ("'", "'"),
        "bash": (": <<'EOF'", "EOF"),
        "fortran": ("!>", "<!"),
        "matlab": ("%{", "}%"),
        # Aliases for compatibility with detect_language
        "c++": ("/*", "*/"),
        "c#": ("/*", "*/"),
        "js": ("/*", "*/"),
        "ts": ("/*", "*/"),
        "py": ('"""', '"""'),
        "shell": (": <<'EOF'", "EOF"),
    }

    if language is None:
        logger.warning("Unknown language")
        return (None, None)  # Default to # for unknown languages

    language = language.lower()
    if language not in MULTILINE_COMMENT_TOKENS:
        logger.warning("Unknown multiline comment tokens for language '{}'", language)
        return (None, None)
    else:
        return MULTILINE_COMMENT_TOKENS[language]


def list_all_files(directory_path: str, recursive: bool = True) -> list[str]:
    """
    List all files in the specified directory

    Args:
        directory_path (str): Directory path to search
        recursive (bool, optional): Whether to recursively search subdirectories. Defaults to True.

    Returns:
        list[str]: List of file paths
    """
    if not os.path.exists(directory_path):
        logger.error("Directory does not exist: {}", directory_path)
        return []

    if not os.path.isdir(directory_path):
        logger.error("Specified path is not a directory: {}", directory_path)
        return []

    all_files = []

    # Traverse directory
    if recursive:
        for root, _, files in os.walk(directory_path):
            for file in files:
                file_path = os.path.join(root, file)
                all_files.append(file_path)
    else:
        # Only search current directory
        for item in os.listdir(directory_path):
            file_path = os.path.join(directory_path, item)
            if os.path.isfile(file_path):
                all_files.append(file_path)

    return all_files


def compress_paths(file_list: list[str]) -> dict[str, list[str]]:
    """
    Group files by directory hierarchy, compressing directories where appropriate.
    If a directory and all its subdirectories have the same status (all included/excluded),
    it will be compressed as a single entry.

    Args:
        file_list: List of file paths to organize and compress

    Returns:
        Dictionary with directory paths as keys and lists of files as values.
        Compressed directories will be represented with a "/*" suffix.
    """
    if not file_list:
        return {}

    # Build a nested dictionary representing the directory structure
    dir_tree = {"__files": []}  # Initialize with empty files list at root
    for file_path in file_list:
        parts = file_path.split(os.sep)
        current = dir_tree

        # Handle special case for single files without directory
        if len(parts) == 1:
            current["__files"].append(parts[0])
            continue

        # Build tree structure
        for i, part in enumerate(parts[:-1]):  # All except the last part (filename)
            if part not in current:
                current[part] = {"__files": []}
            current = current[part]

        # Add the file to the deepest directory
        if parts[-1]:  # Ensure it's not an empty string
            current["__files"].append(parts[-1])

    # Compress the tree where possible
    def _compress_dir(
        tree: dict[str, Any], path_prefix: str = ""
    ) -> dict[str, list[str]]:
        result = {}

        # Handle case of files in the root directory (no path)
        if path_prefix == "" and tree.get("__files"):
            result[""] = tree["__files"]

        for dirname, contents in tree.items():
            if dirname == "__files":
                continue

            # Get files in this directory
            files = contents.get("__files", [])

            # Get subdirectories
            subdirs = {k: v for k, v in contents.items() if k != "__files"}

            if not subdirs:  # Leaf directory with files
                if files:
                    result[path_prefix + dirname] = files
            else:
                # Recursively count files in subdirectories
                def count_files_recursive(
                    dir_contents: dict[str, Any]
                ) -> tuple[int, list[str]]:
                    count = len(dir_contents.get("__files", []))
                    sub_files = []
                    for k, v in dir_contents.items():
                        if k != "__files":
                            subcount, subfiles = count_files_recursive(v)
                            count += subcount
                            sub_files.extend(subfiles)
                    return count, sub_files + dir_contents.get("__files", [])

                # Check if all subdirectories can be compressed
                all_empty = True
                for subdir_name, subdir_contents in subdirs.items():
                    if subdir_contents.get("__files") or any(
                        k != "__files" for k in subdir_contents.keys()
                    ):
                        all_empty = False
                        break

                if all_empty and not files:
                    # This directory and all subdirectories have no files - compress
                    result[path_prefix + dirname + "/*"] = []
                else:
                    # Check if we should compress this directory with its files count
                    subdir_total_count = 0
                    all_files = []

                    for subdir_name, subdir_contents in subdirs.items():
                        subdir_count, subdir_files = count_files_recursive(
                            subdir_contents
                        )
                        subdir_total_count += subdir_count
                        all_files.extend(subdir_files)

                    # Criteria for compressing directories:
                    # 1. Many similar subdirectories (more than 3)
                    # 2. OR same pattern of files across multiple directories
                    should_compress = False

                    if subdir_total_count > 0 and len(subdirs) > 3:
                        should_compress = True
                    # Check if there are multiple subdirectories with similar file patterns
                    elif len(subdirs) >= 2 and path_prefix and "/" in path_prefix:
                        # Focus on directories that follow a pattern (like git object dirs)
                        dir_names = list(subdirs.keys())
                        if all(len(name) == len(dir_names[0]) for name in dir_names):
                            # Similar naming pattern, likely should be compressed
                            should_compress = True

                    if should_compress:
                        # Compress directory with its total files count
                        result[path_prefix + dirname + "/*"] = all_files + files
                    else:
                        # Process subdirectories
                        sub_results = _compress_dir(
                            subdirs, path_prefix=path_prefix + dirname + os.sep
                        )
                        # Add this directory's files
                        if files:
                            result[path_prefix + dirname] = files
                        # Merge with subdirectory results
                        result.update(sub_results)

        return result

    return _compress_dir(dir_tree)


def compare_subsequences(arr, idx1, idx2, length, n):
    """
    Efficiently compare subsequences of arr from idx1 and idx2 with length.
    Avoid creating new list slices.
    """
    # Check boundaries, ensure comparison doesn't exceed list range
    if idx1 + length > n or idx2 + length > n:
        return False
    # Compare each element
    for l_offset in range(length):
        if arr[idx1 + l_offset] != arr[idx2 + l_offset]:
            return False
    return True


def compress_repeating_sequences(arr: list[Any]) -> list[tuple[Any, int]]:
    """
    Compress consecutive repeating subsequences in the list.

    Args:
        arr: The input list.

    Returns:
        A list containing (item, count) tuples.
        item can be a single element, or a list (representing a repeating subsequence).
        count is the number of consecutive repetitions of the item or subsequence.
    """
    if not arr:
        return []

    result = []
    i = 0
    n = len(arr)

    while i < n:
        # if the last element is not a repeating element, add it to the result
        if i == n - 1:
            result.append((arr[i], 1))
            break

        # first check if there is a single element continuous repetition
        if arr[i] == arr[i + 1]:
            # calculate the number of single element continuous repetitions
            element = arr[i]
            count = 1
            j = i
            while j < n - 1 and arr[j] == arr[j + 1]:
                count += 1
                j += 1

            # find the continuous single element repetition
            result.append((element, count))
            i += count
            continue

        # secondly, find the repeating subsequence
        found_repeat = False
        best_compression = None  # store the best compression scheme (k, count)
        best_compression_ratio = 0  # the best compression ratio

        max_k = (n - i) // 2
        for k in range(2, max_k + 1):  # only consider subsequences of length >= 2
            if compare_subsequences(arr, i, i + k, k, n):
                # find the repeating subsequence of length k, calculate the repetition count
                current_count = 2
                j = i + 2 * k
                while j + k <= n and compare_subsequences(arr, i, j, k, n):
                    current_count += 1
                    j += k

                # calculate the compression ratio: (total elements / compressed elements)
                # the compressed subsequence needs k elements to represent, plus 1 count
                compression_ratio = (k * current_count) / (k + 1)

                # if the ratio is higher, update the best compression scheme
                if (
                    compression_ratio > best_compression_ratio
                    and compression_ratio > 1.0
                ):
                    best_compression = (k, current_count)
                    best_compression_ratio = compression_ratio

        # apply the best compression scheme
        if best_compression:
            k, count = best_compression
            sequence = arr[i : i + k]
            result.append((sequence, count))
            i += k * count
            found_repeat = True

        # if no repeating subsequence is found, add the single element to the result
        if not found_repeat:
            result.append((arr[i], 1))
            i += 1

    return result


def run_target(
    execution_code: str, timeout: int, enable_sanitizer_env: bool = True
) -> dict[str, Any]:
    """Run the target program with the given execution code.

    This is a pure function that only executes the test case and returns the result.
    It does not perform any side effects like file saving or logging.

    Args:
        execution_code: The Python code to execute
        timeout: The (soft) timeout for the target program. If the target program runs 2x longer than the timeout, it will be killed.
        enable_sanitizer_env: Whether to enable the sanitizer environment for the target program

    Returns:
        A dictionary containing:
        - exec_success: Whether the model-generated code is executable
        - exec_error: The original exception object if the model-generated code is not executable
        - target_stderr: The stderr of the target program
        - target_return_code: The return code of the target program
        - target_crashed: Whether the target program crashed
        - target_crash_reason: The reason why the target program crashed
        - target_timeout: Whether the target program timed out
    """
    try:
        # `execute_program` returns (stderr, return_code)
        target_stderr, return_code = exec_code_function(
            execution_code, "execute_program", timeout, enable_sanitizer_env
        )

        is_crashed, crash_reason = detected_crash(target_stderr, return_code)

        # If we get here, the model-generated code executed successfully
        # Even if the target program crashed, it is still considered a successful execution from the concolic testing perspective
        return {
            "exec_success": True,  # Code executed successfully (even if target program crashed)
            "exec_error": None,
            "target_stderr": target_stderr,
            "target_return_code": return_code,
            "target_crashed": is_crashed,
            "target_crash_reason": crash_reason,
            "target_timeout": True if return_code == -signal.SIGKILL else False,
        }  # `execute_program` returns -signal.SIGKILL if the target program timed out

    except TimeoutError:
        logger.warning(f"Function execution timed out after {timeout} seconds")
        return {
            "exec_success": True,  # Model generation errors are failures
            "exec_error": None,
            "target_stderr": None,
            "target_return_code": None,
            "target_crashed": False,  # Not a crash, just a model error
            "target_crash_reason": None,
            "target_timeout": True,
        }
    except TargetExecutionError as error:
        # If we get here, the model-generated code itself failed to execute
        # This is a model generation error (syntax error, etc.) that needs to be fixed

        return {
            "exec_success": False,  # Model generation errors are failures
            "exec_error": str(error),
            "target_stderr": None,
            "target_return_code": None,
            "target_crashed": False,  # Not a crash, just a model error
            "target_crash_reason": None,
            "target_timeout": False,
        }
    except Exception as error:
        raise error


def detected_crash(stderr: str, returncode: int) -> tuple[bool, str]:
    """
    Check whether the target program crashed.

    Args:
        stderr: Standard error output from the program
        returncode: Return code from the program

    Returns:
        bool: True if a crash is detected, False otherwise
        str: Crash reason
    """
    reason = None
    signal_num = None
    if returncode < 0:
        signal_num = -returncode
    elif returncode >= 128:
        signal_num = returncode - 128

    if signal_num is not None and signal_num not in [signal.SIGKILL]:
        try:
            signal_name = signal.Signals(signal_num).name
            reason = f"Terminated by signal {signal_num} ({signal_name})"
        except ValueError:
            # Unknown signal number, use generic message
            reason = f"Terminated by signal {signal_num}"

    if reason is not None:
        return True, reason

    # check if the program crashed due to an error
    stderr_lower = stderr.lower()

    # memory related errors (C/C++/Rust etc.)
    memory_keywords = [
        "sanitizer",
        "heap corruption",
        "use after free",
        "double free",
        "memory leak",
        "outofmemoryerror",
        "overflow",
        "underflow",
        "segmentation fault",
        "null pointer",
        "undefined behavior",
        "ubsan",
    ]

    # system related errors
    system_keywords = [
        "illegal instruction",
        "bus error",
        "core dumped",
    ]

    # Python related errors
    python_keywords = [
        "nameerror",
        "typeerror",
        "valueerror",
        "indexerror",
        "keyerror",
        "attributeerror",
        "importerror",
        "syntaxerror",
        "indentationerror",
        "zerodivisionerror",
        "recursionerror",
        "memoryerror",
        "systemerror",
        "runtimeerror",
        "assertionerror",
        "keyboardinterrupt",
        "generatorexit",
        "stopiteration",
    ]

    # Java related errors
    java_keywords = [
        "stackoverflowerror",
        "outofmemoryerror",
    ]

    java_jni_keywords = [
        # memory related
        "local reference table overflow",
        "global reference table overflow",
        "weak global reference table overflow",
        "DeleteLocalRef failed",
        "DeleteGlobalRef failed",
        "DeleteWeakGlobalRef failed",
        # function call related
        "GetMethodID failed",
        "GetStaticMethodID failed",
        "CallMethod failed",
        "CallStaticMethod failed",
        "CallNonvirtualMethod failed",
        # field related
        "GetFieldID failed",
        "GetStaticFieldID failed",
        "SetField failed",
        "SetStaticField failed",
        "GetField failed",
        "GetStaticField failed",
        # array related
        "GetArrayLength failed",
        "GetArrayElements failed",
        "ReleaseArrayElements failed",
        "GetPrimitiveArrayCritical failed",
        "ReleasePrimitiveArrayCritical failed",
        # string related
        "GetStringUTFChars failed",
        "ReleaseStringUTFChars failed",
        "GetStringChars failed",
        "ReleaseStringChars failed",
        "NewString failed",
        "NewStringUTF failed",
        # exception related
        "ExceptionOccurred",
        "ExceptionCheck failed",
        "ExceptionClear failed",
        "Throw failed",
        "ThrowNew failed",
    ]

    # JavaScript related errors
    js_keywords = [
        "typeerror",
        "referenceerror",
        "syntaxerror",
        "rangeerror",
        "evalerror",
        "urierror",
        "promiserejection",
        "uncaught exception",
        "unhandledrejection",
    ]

    # General program errors
    program_keywords = [
        "exception",
        "traceback",
        "fatal",
        "divide by zero",
        "overflow",
        "assertion failed",
        "crash",
        "abort",
        "terminated",
        "hang",
        "deadlock",
        "race condition",
        "infinite loop",
    ]

    all_keywords = (
        memory_keywords
        + system_keywords
        + python_keywords
        + java_keywords
        + java_jni_keywords
        + js_keywords
        + program_keywords
    )

    for keyword in all_keywords:
        # use word boundary matching instead of simple substring matching
        # this can avoid the case where "hang" is mistakenly identified as "change"

        pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
        if re.search(pattern, stderr_lower):
            return True, f'Found keyword "{keyword}" in stderr'

    return False, None


def estimate_text_token(
    text: str | None, model: str = "claude-sonnet-4-5-20250929"
) -> int:
    """
    Estimate the number of tokens in a text.
    """
    client = Anthropic()

    count = client.beta.messages.count_tokens(
        model=model, messages=[{"role": "user", "content": text}]
    )
    return count.input_tokens
