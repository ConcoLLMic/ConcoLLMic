"""
Code instrumentation command for ACE.
"""

import atexit
import concurrent.futures
import datetime
import os
import threading
from collections import deque
from collections.abc import Callable

import yaml
from loguru import logger

from app.agents.agent_instrumentation import InstrumentationAgent
from app.utils.utils import (
    compress_paths,
    detect_language,
    get_comment_token,
    list_all_files,
)

INSTRUMENTATION_INFO_FILE = ".instrument_info"


class TaskExecutor:
    """Class to manage concurrent file instrumentation tasks using a thread pool."""

    def __init__(self, max_workers):
        """Initialize the task executor with a thread pool.

        Args:
            max_workers (int): Maximum number of concurrent workers in the thread pool
        """
        self.max_workers = max_workers
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.submitted_futures = (
            {}
        )  # Map future to file path for better status reporting
        self.futures_lock = threading.Lock()
        self.completed_results = []  # Store completed results (future, success)
        self.results_lock = threading.Lock()

        # Register cleanup method to be called at program exit
        atexit.register(self.cleanup)

    def cleanup(self):
        """Clean up thread pool resources"""
        logger.debug("Shutting down thread pool executor...")
        self.executor.shutdown(wait=True)
        logger.debug("Thread pool executor has been shut down.")

    def submit_task(
        self, func: Callable, file_path: str, rel_path: str, chunk_size: int
    ):
        """Submit a file instrumentation task to the thread pool

        Args:
            func (Callable): The function to execute
            file_path (str): The file path to process
            rel_path (str): The relative path of the file

        Returns:
            Future: The future representing the submitted task
        """
        logger.info(f'Submitting file "{file_path}" to thread pool for instrumentation')

        future = self.executor.submit(
            func, file_path=file_path, rel_path=rel_path, chunk_size=chunk_size
        )

        with self.futures_lock:
            self.submitted_futures[future] = file_path

        logger.debug(f'File "{file_path}" successfully submitted')
        return future

    def wait_for_available_worker(self):
        """Wait until there's at least one available worker in the pool.
        This method blocks until at least one worker becomes available.
        Also processes and yields completed futures as they finish.

        Returns:
            list: List of (future, success) tuples for each completed task
        """
        results = []

        def _process_completed_futures(done_futures):
            """Process completed futures and add them to the results list"""
            nonlocal results
            for future in done_futures:
                if future in self.submitted_futures:  # Make sure it's still there
                    file_path = self.submitted_futures.pop(future, "Unknown file")
                    try:
                        # Get the result, which will raise any exception that occurred
                        result = future.result()
                        assert isinstance(result, bool)
                        logger.info(
                            f'File "{file_path}" instrumentation completed, success: {result}'
                        )
                        results.append((future, result))
                    except Exception as e:
                        logger.error(f'Exception in file "{file_path}": {e}')
                        results.append((future, False))

        with self.futures_lock:
            # Process any completed futures even if the pool is not full
            current_futures = list(self.submitted_futures.keys())

            if current_futures:
                # Release the lock temporarily to check for completed futures
                self.futures_lock.release()

                # Check if any futures are done without blocking
                done, _ = concurrent.futures.wait(
                    current_futures,
                    timeout=0,  # Non-blocking check
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                # Reacquire the lock
                self.futures_lock.acquire()

                # Process completed futures
                _process_completed_futures(done)

            # If the pool is still full, wait for at least one task to complete
            while len(self.submitted_futures) >= self.max_workers:
                # Get current futures to check
                current_futures = list(self.submitted_futures.keys())

                # Release the lock temporarily to allow other threads to update futures
                self.futures_lock.release()

                # Wait for any future to complete
                done, _ = concurrent.futures.wait(
                    current_futures,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                # Reacquire the lock
                self.futures_lock.acquire()

                # Process completed futures
                _process_completed_futures(done)

        # Return all completed results
        return results

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
            f"Finally, waiting for {total_tasks} files to complete instrumentation"
        )

        # Process futures as they complete
        for future in concurrent.futures.as_completed(futures_map.keys()):
            file_path = futures_map[future]
            completed_tasks += 1

            try:
                # Get the result, which will raise any exception that occurred
                result = future.result()
                assert isinstance(result, bool)
                logger.info(
                    f'File "{file_path}" instrumentation completed, success: {result} ({completed_tasks}/{total_tasks})'
                )
                yield future, result
            except Exception as e:
                logger.error(f'Exception in file "{file_path}": {e}')
                yield future, False


def _is_in_excluded_dirs(file_path, exclude_dirs_list):
    """Check if file is in an excluded directory"""
    if not exclude_dirs_list:
        return False

    return any(
        os.path.normpath(file_path).startswith(os.path.normpath(dir))
        or os.path.normpath(dir) in os.path.normpath(file_path).split(os.sep)
        for dir in exclude_dirs_list
    )


def _is_already_instrumented(file_path):
    """
    Check if file is already instrumented by looking for cost summary comments at the end

    Returns False if file doesn't exist or can't be read
    """
    if not os.path.exists(file_path):
        return False

    try:
        language = detect_language(file_path)
        if not language:
            return False

        comment_token = get_comment_token(language)

        with open(file_path, encoding="utf-8", errors="ignore") as f:
            last_lines = deque(f, 10)

            for line in last_lines:
                line = line.strip()
                if (
                    line.lstrip().startswith(comment_token)
                    and "instrumented cost" in line
                ):
                    return True
            return False
    except Exception as e:
        logger.warning(f"Error checking if {file_path} is already instrumented: {e}")
        return False


def _copy_file(src, dst):
    """Copy a file"""
    os.system(f"cp {src} {dst}")


def _prepare_instrumentation_summary(
    instrumented_files,
    instr_failed_files,
    excluded_files,
    already_instrumented_files,
    unsupported_files,
    special_files,
    binary_files,
    read_error_files,
):
    """
    Prepare common data for instrumentation summary and detailed information

    Args:
        instrumented_files: List of successfully instrumented files
        instr_failed_files: List of files that failed during instrumentation
        excluded_files: List of excluded files
        already_instrumented_files: List of already instrumented files
        unsupported_files: List of unsupported language files
        special_files: List of special files
        binary_files: List of binary files
        read_error_files: List of files with errors

    Returns:
        Tuple containing:
        - Dictionary of compressed file paths
        - Dictionary of calculated totals
    """
    # Compress all file lists
    compressed_paths = {
        "instr": compress_paths(instrumented_files),
        "instr_failed": compress_paths(instr_failed_files),
        "excluded": compress_paths(excluded_files),
        "already_instr": compress_paths(already_instrumented_files),
        "unsupported": compress_paths(unsupported_files),
        "special": compress_paths(special_files),
        "binary": compress_paths(binary_files),
        "read_error": compress_paths(read_error_files),
    }

    # Calculate totals
    total_instrumented = len(instrumented_files) + len(already_instrumented_files)

    total_other_skipped = (
        len(unsupported_files)
        + len(special_files)
        + len(binary_files)
        + len(read_error_files)
    )

    total_non_instrumented = len(excluded_files) + total_other_skipped

    total_processed = (
        total_instrumented + len(instr_failed_files) + total_non_instrumented
    )

    totals = {
        "total_processed": total_processed,
        "total_instrumented": total_instrumented,
        "total_non_instrumented": total_non_instrumented,
        "total_other_skipped": total_other_skipped,
    }

    return compressed_paths, totals


def format_instrumentation_paths(
    compressed_paths, log_output=True, max_files_to_show=5, indent_level=1
):
    """
    Format path information for instrumentation output

    Args:
        compressed_paths: Dictionary with compressed directory paths as keys and lists of files as values
        log_output: If True, format for terminal/log output with limited details. If False, more verbose output.
        max_files_to_show: Maximum number of files to display in log output mode (ignored in detailed mode)
        indent_level: Level of indentation for log output (number of "  " prefixes)

    Returns:
        Dictionary with formatted directory information or formatted log lines depending on log_output
    """
    indent = "  " * indent_level

    if log_output:
        # Format for log output - returns list of strings
        log_lines = []
        for dirname, files in sorted(compressed_paths.items()):
            if dirname.endswith("/*"):
                # Compressed directory
                log_lines.append(f"{indent}{dirname}: {len(files)} files")
            else:
                # Regular directory with files
                display_name = "./" if dirname == "" else f"{dirname}/"
                log_lines.append(f"{indent}{display_name}: {len(files)} files")
                _files_to_show = min(len(files), max_files_to_show)
                if _files_to_show > 0:  # Only show individual files if there are few
                    for file in sorted(files)[:_files_to_show]:
                        log_lines.append(f"{indent}  - {file}")
                    if len(files) > max_files_to_show:
                        log_lines.append(
                            f"{indent}  - ... and {len(files) - max_files_to_show} more files"
                        )
        return log_lines
    else:
        # Format for detailed info - returns structured data
        structured_data = {}
        for dirname, files in sorted(compressed_paths.items()):
            is_compressed = dirname.endswith("/*")
            # use "./" as root directory
            key_name = "./" if dirname == "" else dirname
            structured_data[key_name] = {
                "is_compressed": is_compressed,
                # Include all files in detailed info even for compressed directories
                f"{len(files)}_files": sorted(files),
            }
        return structured_data


def format_file_category(
    file_list, compressed_dirs, title, indent_level=1, max_dirs_to_show=5, out_dir=None
):
    """
    Format a file category with consistent styling for the log output

    Args:
        file_list: List of files in this category
        compressed_dirs: Dictionary of compressed directories for these files
        title: Category title to display
        indent_level: Indentation level for this category
        max_dirs_to_show: Maximum number of directories to show before truncating
        out_dir: Output directory (for info_file reference in truncation message)

    Returns:
        List of formatted log lines for this category
    """
    lines = []

    # Add category header with file count
    lines.append(f"{' ' * (indent_level * 2)}{title}: {len(file_list)} files")

    # Only proceed if there are files in this category
    if file_list:
        # Limit by directory count
        if max_dirs_to_show is None or len(compressed_dirs) <= max_dirs_to_show:
            for line in format_instrumentation_paths(
                compressed_dirs, indent_level=indent_level + 1
            ):
                lines.append(line)
        elif out_dir:  # Only show truncation message if out_dir is provided
            lines.append(
                f"{' ' * ((indent_level + 1) * 2)}(Too many directories to display, see detailed info in {out_dir}/{INSTRUMENTATION_INFO_FILE})"
            )

    return lines


def format_other_skipped_files(
    unsupported_files,
    compressed_unsupported,
    special_files,
    compressed_special,
    binary_files,
    compressed_binary,
    read_error_files,
    compressed_error,
    out_dir,
):
    """
    Format the "Other skipped files" section with all its subcategories

    Args:
        unsupported_files: List of unsupported language files
        compressed_unsupported: Compressed directories for unsupported files
        special_files: List of special files
        compressed_special: Compressed directories for special files
        binary_files: List of binary files
        compressed_binary: Compressed directories for binary files
        read_error_files: List of files with read errors
        compressed_error: Compressed directories for read error files
        out_dir: Output directory for info file reference

    Returns:
        List of formatted log lines for the entire "Other skipped files" section
    """
    total_skipped = (
        len(unsupported_files)
        + len(special_files)
        + len(binary_files)
        + len(read_error_files)
    )

    skipped_summary = []
    # Main header for other skipped files
    skipped_summary.append(f"  b) Other skipped files ({total_skipped} files):")

    # i. Unsupported language files
    unsupported_lines = format_file_category(
        unsupported_files,
        compressed_unsupported,
        "i. Unsupported language",
        indent_level=3,
        max_dirs_to_show=5,
        out_dir=out_dir,
    )
    skipped_summary.extend(unsupported_lines)

    # ii. Special files
    special_lines = format_file_category(
        special_files,
        compressed_special,
        "ii. Special files",
        indent_level=3,
        max_dirs_to_show=5,
        out_dir=out_dir,
    )
    skipped_summary.extend(special_lines)

    # iii. Binary/non-UTF-8 files
    binary_lines = format_file_category(
        binary_files,
        compressed_binary,
        "iii. Binary/non-UTF-8 files",
        indent_level=3,
        max_dirs_to_show=5,
        out_dir=out_dir,
    )
    skipped_summary.extend(binary_lines)

    # iv. Error files
    error_lines = format_file_category(
        read_error_files,
        compressed_error,
        "iv. Error files",
        indent_level=3,
        max_dirs_to_show=5,
        out_dir=out_dir,
    )
    skipped_summary.extend(error_lines)

    return skipped_summary


def generate_detailed_instrumentation_info(
    instrumented_files,
    instr_failed_files,
    excluded_files,
    already_instrumented_files,
    unsupported_files,
    special_files,
    binary_files,
    read_error_files,
):
    """
    Generate detailed instrumentation information and save to file

    Args:
        instrumented_files: List of successfully instrumented files
        instr_failed_files: List of files that failed during instrumentation
        excluded_files: List of excluded files
        already_instrumented_files: List of already instrumented files
        unsupported_files: List of unsupported language files
        special_files: List of special files
        binary_files: List of binary files
        read_error_files: List of files with errors
    """
    # Get compressed paths and totals
    compressed_paths, totals = _prepare_instrumentation_summary(
        instrumented_files,
        instr_failed_files,
        excluded_files,
        already_instrumented_files,
        unsupported_files,
        special_files,
        binary_files,
        read_error_files,
    )

    # Create the detailed info structure
    detailed_info = {
        "timestamp": datetime.datetime.now().isoformat(),
        "summary": {
            "total_processed_files": totals["total_processed"],
            "instrumented_files": totals["total_instrumented"],
            "instrumentation_failed_files": len(instr_failed_files),
            "non_instrumented_files": totals["total_non_instrumented"],
        },
        "categories": {
            "1_instrumented_files": {
                "count": totals["total_instrumented"],
                "subcategories": {
                    "a_newly_instrumented_files": {
                        "count": len(instrumented_files),
                        "directories": format_instrumentation_paths(
                            compressed_paths["instr"], log_output=False
                        ),
                    },
                    "b_already_instrumented_files": {
                        "count": len(already_instrumented_files),
                        "directories": format_instrumentation_paths(
                            compressed_paths["already_instr"], log_output=False
                        ),
                    },
                },
            },
            "2_instrumentation_failed_files": {
                "count": len(instr_failed_files),
                "directories": format_instrumentation_paths(
                    compressed_paths["instr_failed"], log_output=False
                ),
            },
            "3_non_instrumented_files": {
                "count": totals["total_non_instrumented"],
                "subcategories": {
                    "a_excluded_files": {
                        "count": len(excluded_files),
                        "directories": format_instrumentation_paths(
                            compressed_paths["excluded"], log_output=False
                        ),
                    },
                    "b_other_skipped_files": {
                        "count": totals["total_other_skipped"],
                        "subcategories": {
                            "unsupported_language": {
                                "count": len(unsupported_files),
                                "directories": format_instrumentation_paths(
                                    compressed_paths["unsupported"], log_output=False
                                ),
                            },
                            "special_files": {
                                "count": len(special_files),
                                "directories": format_instrumentation_paths(
                                    compressed_paths["special"], log_output=False
                                ),
                            },
                            "binary_files": {
                                "count": len(binary_files),
                                "directories": format_instrumentation_paths(
                                    compressed_paths["binary"], log_output=False
                                ),
                            },
                            "read_error_files": {
                                "count": len(read_error_files),
                                "directories": format_instrumentation_paths(
                                    compressed_paths["read_error"], log_output=False
                                ),
                            },
                        },
                    },
                },
            },
        },
    }

    return yaml.dump(
        detailed_info, sort_keys=False, default_flow_style=False, allow_unicode=True
    )


def _instrument_file(file_path, rel_path, chunk_size):
    """Instrument a single file

    Args:
        file_path (str): Path to the output file
        rel_path (str): Relative path for marking

    Returns:
        bool: True if instrumentation was successful, False otherwise
    """
    instr_agent = InstrumentationAgent()
    logger.info(f'Instrumenting "{file_path}"')
    instrumented_content, success = instr_agent.instrument(
        source_code_file=file_path, mark=rel_path, chunk_size=chunk_size
    )
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(
            instrumented_content
        )  # If not successful, the file is INCOMPLETE (for debugging)
    return success


def instrument_code(
    src_dir: str,
    out_dir: str,
    instr_languages: str,
    exclude_dirs: str | None,
    parallel_num: int,
    chunk_size: int,
):
    """
    Code instrumentation phase

    Args:
        src_dir: Source code directory
        out_dir: Output directory
        instr_languages: Languages to instrument, comma-separated string
        exclude_dirs: Directories to exclude, comma-separated string
        parallel_num: Number of parallel workers for instrumentation
        chunk_size: Chunk size for instrumentation
    """
    logger.info("Starting code instrumentation phase...")

    # Create output directory if it doesn't exist
    os.makedirs(out_dir, exist_ok=True)

    # Convert exclude_dirs from comma-separated string to list if provided
    exclude_dirs_list = []
    if exclude_dirs:
        exclude_dirs_list = [
            os.path.normpath(dir.strip()) for dir in exclude_dirs.split(",")
        ]
        logger.info(f"Excluding directories: {exclude_dirs_list}")

    # Automatically add common directories to exclude list
    common_dirs_to_exclude = [
        ".git",
        ".github",
        ".vscode",
        "node_modules",
        "__pycache__",
        "venv",
        ".idea",
    ]
    for common_dir in common_dirs_to_exclude:
        if common_dir not in exclude_dirs_list:
            exclude_dirs_list.append(common_dir)
            logger.info(
                f"Automatically adding common directories to excluded directories: {common_dirs_to_exclude}"
            )

    # List all code files in the source directory
    all_files = list_all_files(src_dir)
    logger.info(f"Found {len(all_files)} files to process")

    # Convert instr_languages from comma-separated string to list
    supported_languages = [lang.strip() for lang in instr_languages.split(",")]
    if "c" in supported_languages:
        supported_languages.append(
            "cpp"
        )  # ".h" ".cc" files are detected as "cpp" language
    logger.info(f"Instrumenting languages: {supported_languages}")

    # Lists to track processed files for summary
    instrumented_files = []
    instr_failed_files = []
    excluded_files = []
    already_instrumented_files = []
    unsupported_files = []
    special_files = []
    binary_files = []
    read_error_files = []

    # Create task executor for parallel instrumentation
    task_executor = TaskExecutor(max_workers=parallel_num)
    futures_to_outfiles = {}

    # Process each file - files that need to be instrumented will be submitted to the thread pool
    # When the thread pool is full (10 workers), we'll wait for a worker to become available before submitting new tasks
    for file in all_files:
        # create output file with the same relative path
        rel_path = os.path.relpath(file, src_dir)
        out_file = os.path.join(out_dir, rel_path)
        os.makedirs(os.path.dirname(out_file), exist_ok=True)

        should_copy = True
        should_instrument = True
        skip_reason = None

        # 1. Check if file is in excluded directory
        if _is_in_excluded_dirs(file, exclude_dirs_list):
            skip_reason = "in excluded directory"
            should_instrument = False
            excluded_files.append(rel_path)

        # 2. Check if file is already instrumented
        elif _is_already_instrumented(out_file):
            skip_reason = "already instrumented"
            should_instrument = False
            should_copy = False  # No need to copy already instrumented files
            already_instrumented_files.append(rel_path)

        # 3. Check file type
        elif detect_language(file) not in supported_languages:
            skip_reason = f"unsupported language ({detect_language(file)})"
            should_instrument = False
            unsupported_files.append(rel_path)

        # 4. Check if it's a special file
        elif file.endswith("setup.py"):  # TODO: add other special files to skip
            skip_reason = "special file"
            should_instrument = False
            special_files.append(rel_path)

        # 5. Check if file is binary or non-UTF-8
        else:
            try:
                with open(file, encoding="utf-8") as f:
                    f.read()
            except UnicodeDecodeError:
                skip_reason = "binary or non-UTF-8 file"
                should_instrument = False
                binary_files.append(rel_path)
            except Exception as e:
                skip_reason = f"error reading file: {e}"
                should_instrument = False
                read_error_files.append(rel_path)

        # Take action based on checks
        if not should_instrument:
            if skip_reason:
                logger.info(f"Skipping {file}: {skip_reason}")

            if should_copy:
                _copy_file(file, out_file)
            continue

        # Perform instrumentation - wait for available worker if needed and process any completed tasks
        else:
            assert should_copy
            completed_results = task_executor.wait_for_available_worker()
            for future, success in completed_results:
                completed_rel_path = futures_to_outfiles.get(future)
                if completed_rel_path:
                    if success:
                        instrumented_files.append(completed_rel_path)
                    else:
                        instr_failed_files.append(completed_rel_path)

            # Copy file before submitting the task
            _copy_file(file, out_file)

            # Submit the instrumentation task
            future = task_executor.submit_task(
                func=_instrument_file,
                file_path=out_file,
                rel_path=rel_path,
                chunk_size=chunk_size,
            )
            futures_to_outfiles[future] = rel_path

    # Wait for all tasks to complete and collect results
    # This ensures all instrumentation tasks finish before we generate the summary
    for future, success in task_executor.wait_for_all_tasks():
        rel_path = futures_to_outfiles.get(future)
        if rel_path:
            if success:  # Success
                instrumented_files.append(rel_path)
            else:  # Failed
                instr_failed_files.append(rel_path)

    ### final check
    # check instrumentation or not
    for file in instrumented_files + already_instrumented_files:
        if not _is_already_instrumented(os.path.join(out_dir, file)):
            logger.error(
                f"File {file} was not instrumented but recorded as instrumented"
            )

    for file in instr_failed_files:
        if _is_already_instrumented(os.path.join(out_dir, file)):
            logger.error(
                f"File {file} was recorded as instrumentation failed but was instrumented"
            )

    # ensure src_dir and out_dir have the same files (use relative path!)
    src_files = [
        os.path.relpath(file, src_dir)
        for file in list_all_files(src_dir, recursive=True)
    ]
    out_files = [
        os.path.relpath(file, out_dir)
        for file in list_all_files(out_dir, recursive=True)
    ]
    for file in src_files:
        if file not in out_files:
            logger.error(
                f"File {file} is in source dir ({src_dir}) but not in out dir ({out_dir})"
            )

    # Generate summary grouped by directories
    logger.info("=" * 50)
    logger.info("INSTRUMENTATION SUMMARY")
    logger.info("=" * 50)

    # Get compressed paths and totals
    compressed_paths, totals = _prepare_instrumentation_summary(
        instrumented_files,
        instr_failed_files,
        excluded_files,
        already_instrumented_files,
        unsupported_files,
        special_files,
        binary_files,
        read_error_files,
    )

    # Show totals first
    logger.info(f"Total files processed: {totals['total_processed']} files")

    # 1. Instrumented files category
    logger.info(f"1) Instrumented files: {totals['total_instrumented']} files")

    # 1.1 Newly instrumented files
    logger.info(f"  a) Newly instrumented files: {len(instrumented_files)} files")
    if instrumented_files:
        for line in format_instrumentation_paths(
            compressed_paths["instr"], indent_level=2
        ):
            logger.info(line)

    # 1.2 Already instrumented files
    logger.info(
        f"  b) Already instrumented files: {len(already_instrumented_files)} files"
    )
    if already_instrumented_files:
        for line in format_instrumentation_paths(
            compressed_paths["already_instr"], indent_level=2
        ):
            logger.info(line)

    # 2. Instrumentation failed files category
    logger.info(f"2) Instrumentation failed files: {len(instr_failed_files)} files")
    if instr_failed_files:
        for line in format_instrumentation_paths(
            compressed_paths["instr_failed"], indent_level=1
        ):
            logger.info(line)

    # 3. Non-instrumented files category
    logger.info(f"3) Non-instrumented files: {totals['total_non_instrumented']} files")

    # 3.1 Excluded files subcategory - use the helper function
    excluded_lines = format_file_category(
        excluded_files,
        compressed_paths["excluded"],
        "a) Excluded files (in excluded directories)",
        indent_level=1,
        max_dirs_to_show=None,  # No limit for these main categories
    )
    for line in excluded_lines:
        logger.info(line)

    # 3.2 Other skipped files subcategory - use the format_other_skipped_files helper
    skipped_summary = format_other_skipped_files(
        unsupported_files,
        compressed_paths["unsupported"],
        special_files,
        compressed_paths["special"],
        binary_files,
        compressed_paths["binary"],
        read_error_files,
        compressed_paths["read_error"],
        out_dir,
    )

    # Log all skipped summary lines
    for line in skipped_summary:
        logger.info(line)

    logger.info("=" * 50)
    logger.info(f"Instrumentation completed. Output in {out_dir}")

    # Generate detailed instrumentation info and save to file
    content = generate_detailed_instrumentation_info(
        instrumented_files,
        instr_failed_files,
        excluded_files,
        already_instrumented_files,
        unsupported_files,
        special_files,
        binary_files,
        read_error_files,
    )
    # Save detailed info to file
    info_file_path = os.path.join(out_dir, INSTRUMENTATION_INFO_FILE)
    with open(info_file_path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"Detailed instrumentation info saved to {info_file_path}")
    logger.info("=" * 50)


def setup_instrument_parser(subparsers):
    """Setup the instrument subcommand parser"""
    instrument_parser = subparsers.add_parser(
        "instrument", help="perform code instrumentation"
    )
    instrument_parser.add_argument(
        "--src_dir",
        type=str,
        help="source code directory",
        required=True,
    )
    instrument_parser.add_argument(
        "--out_dir", type=str, help="output directory", required=True
    )
    instrument_parser.add_argument(
        "--instr_languages",
        type=str,
        help="comma-separated list of languages to instrument (e.g. 'python,java,c,cpp')",
        required=True,
    )
    instrument_parser.add_argument(
        "--exclude_dirs",
        type=str,
        help="comma-separated list of directories to exclude from instrumentation (e.g. 'deps,tests,examples')",
        required=False,
        default=None,
    )
    instrument_parser.add_argument(
        "--parallel_num",
        type=int,
        help="number of parallel workers for instrumentation",
        required=False,
        default=10,
    )
    instrument_parser.add_argument(
        "--chunk_size",
        type=int,
        help="chunk size for instrumentation",
        required=False,
        default=800,
    )
    return instrument_parser
