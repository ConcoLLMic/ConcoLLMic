"""
Statistics collection command for ACE.
"""

import os
import re
from collections import defaultdict

from loguru import logger

from app.agents.common import (
    FILE_TRACE_PATTERN,
    INSTRUMENTED_COST_PATTERN,
    SPLIT_COST_PATTERN,
    TOTAL_COST_PATTERN,
)
from app.utils.utils import detect_language


def collect_instrument_code_data(directory, extensions=None):
    """
    Collect instrumentation code data from all files in the specified directory

    Args:
        directory (str): Directory path to search
        extensions (list): List of file extensions to search for, if None, search all files

    Returns:
        list: List of dictionaries containing statistics for each file
    """

    statistics = []

    for root, _, files in os.walk(directory):
        for file in files:
            # If extensions are specified, only process matching files
            if extensions and not any(file.endswith(ext) for ext in extensions):
                continue

            if not detect_language(
                file
            ):  # we does not instrument file with unknown language, accelerate the process
                continue

            file_path = os.path.join(root, file)

            # Try to read the file
            try:
                with open(file_path, encoding="utf-8") as f:
                    content = f.read()
            except (UnicodeDecodeError, OSError):
                # Skip files that cannot be read
                continue

            instr_statement_count = 0

            # Use regex to find cost statistics
            total_cost_match = re.search(TOTAL_COST_PATTERN, content)
            split_cost_match = re.search(SPLIT_COST_PATTERN, content)
            instrumented_cost_match = re.search(INSTRUMENTED_COST_PATTERN, content)

            if total_cost_match and split_cost_match and instrumented_cost_match:
                # Count instrumentation statements using FILE_TRACE_PATTERN
                for line in content.split("\n"):
                    if re.search(FILE_TRACE_PATTERN, line.strip()):
                        instr_statement_count += 1
                if instr_statement_count % 2 != 0:
                    logger.error(
                        f"Odd number of instrumentation statements for file {file_path}"
                    )
                # Calculate original code lines - use the second number of the last tuple in Split chunks list
                original_lines = 0
                if split_cost_match and len(split_cost_match.groups()) >= 6:
                    # get split chunks string - note group index change
                    last_group_index = len(split_cost_match.groups())
                    chunks_str = split_cost_match.group(last_group_index)
                    try:
                        # Parse the string in format [(start, end), (start, end), ...]
                        chunks_str = chunks_str.strip()
                        if chunks_str:
                            # Convert string to Python list
                            chunks = eval(chunks_str)
                            if (
                                isinstance(chunks, list)
                                and len(chunks) > 0
                                and isinstance(chunks[-1], tuple)
                                and len(chunks[-1]) == 2
                            ):
                                # Use the second number of the last tuple as original code lines
                                original_lines = chunks[-1][1]
                                logger.debug(
                                    f"Original code lines for file {file_path}: {original_lines}"
                                )
                    except Exception as e:
                        logger.warning(
                            f"Failed to parse Split chunks: {e}, original string: {chunks_str}"
                        )

                stat = {
                    "file": os.path.relpath(file_path, directory),
                    "original_lines": original_lines,
                    "extension": os.path.splitext(file)[1],
                    "instr_statement_count": instr_statement_count,
                    "total_cost": (
                        float(total_cost_match.group(1)) if total_cost_match else None
                    ),
                    "split_cost": (
                        float(split_cost_match.group(1)) if split_cost_match else None
                    ),
                    "split_input_tokens": (
                        int(split_cost_match.group(2)) if split_cost_match else None
                    ),
                    "split_output_tokens": (
                        int(split_cost_match.group(3)) if split_cost_match else None
                    ),
                    "split_cache_read_tokens": (
                        int(split_cost_match.group(4))
                        if split_cost_match and split_cost_match.group(4)
                        else 0
                    ),
                    "split_cache_write_tokens": (
                        int(split_cost_match.group(5))
                        if split_cost_match and split_cost_match.group(5)
                        else 0
                    ),
                    "instrumented_cost": (
                        float(instrumented_cost_match.group(1))
                        if instrumented_cost_match
                        else None
                    ),
                    "instrumented_input_tokens": (
                        int(instrumented_cost_match.group(2))
                        if instrumented_cost_match
                        else None
                    ),
                    "instrumented_output_tokens": (
                        int(instrumented_cost_match.group(3))
                        if instrumented_cost_match
                        else None
                    ),
                    "instrumented_cache_read_tokens": (
                        int(instrumented_cost_match.group(4))
                        if instrumented_cost_match and instrumented_cost_match.group(4)
                        else 0
                    ),
                    "instrumented_cache_write_tokens": (
                        int(instrumented_cost_match.group(5))
                        if instrumented_cost_match and instrumented_cost_match.group(5)
                        else 0
                    ),
                }
                statistics.append(stat)
            elif total_cost_match or split_cost_match or instrumented_cost_match:
                logger.error(
                    f'There is something wrong with the pattern (for file "{file_path}"), please check it.'
                )

    return statistics


def generate_summary(statistics):
    """
    Generate a summary of the statistics

    Args:
        statistics (list): List of dictionaries containing statistics for each file

    Returns:
        dict: Dictionary containing summary information
    """
    if not statistics:
        return {
            "total_instr_files": 0,
            "total_original_lines": 0,
            "total_instr_statements": 0,
            "total_cost": 0,
            "total_split_cost": 0,
            "total_instrumented_cost": 0,
            "total_split_input_tokens": 0,
            "total_split_output_tokens": 0,
            "total_split_cache_read_tokens": 0,
            "total_split_cache_write_tokens": 0,
            "total_instrumented_input_tokens": 0,
            "total_instrumented_output_tokens": 0,
            "total_instrumented_cache_read_tokens": 0,
            "total_instrumented_cache_write_tokens": 0,
        }

    # File counts grouped by extension
    extension_counts = defaultdict(int)
    for stat in statistics:
        extension_counts[stat["extension"]] += 1

    # Calculate total costs and token counts
    total_cost = sum(
        stat["total_cost"] for stat in statistics if stat["total_cost"] is not None
    )
    total_split_cost = sum(
        stat["split_cost"] for stat in statistics if stat["split_cost"] is not None
    )
    total_instrumented_cost = sum(
        stat["instrumented_cost"]
        for stat in statistics
        if stat["instrumented_cost"] is not None
    )

    total_split_input_tokens = sum(
        stat["split_input_tokens"]
        for stat in statistics
        if stat["split_input_tokens"] is not None
    )
    total_split_output_tokens = sum(
        stat["split_output_tokens"]
        for stat in statistics
        if stat["split_output_tokens"] is not None
    )
    total_split_cache_read_tokens = sum(
        stat["split_cache_read_tokens"]
        for stat in statistics
        if stat["split_cache_read_tokens"] is not None
    )
    total_split_cache_write_tokens = sum(
        stat["split_cache_write_tokens"]
        for stat in statistics
        if stat["split_cache_write_tokens"] is not None
    )
    total_instrumented_input_tokens = sum(
        stat["instrumented_input_tokens"]
        for stat in statistics
        if stat["instrumented_input_tokens"] is not None
    )
    total_instrumented_output_tokens = sum(
        stat["instrumented_output_tokens"]
        for stat in statistics
        if stat["instrumented_output_tokens"] is not None
    )
    total_instrumented_cache_read_tokens = sum(
        stat["instrumented_cache_read_tokens"]
        for stat in statistics
        if stat["instrumented_cache_read_tokens"] is not None
    )
    total_instrumented_cache_write_tokens = sum(
        stat["instrumented_cache_write_tokens"]
        for stat in statistics
        if stat["instrumented_cache_write_tokens"] is not None
    )

    # Calculate total original code lines
    total_original_lines = sum(
        stat["original_lines"] for stat in statistics if "original_lines" in stat
    )

    # record the max 3 files with longest original code lines
    longest_files = sorted(statistics, key=lambda x: x["original_lines"], reverse=True)[
        : min(3, len(statistics))
    ]

    return {
        "total_instr_files": len(statistics),
        "total_original_lines": total_original_lines,
        "longest_files": longest_files,
        "extension_counts": dict(extension_counts),
        "total_cost": total_cost,
        "total_split_cost": total_split_cost,
        "total_instrumented_cost": total_instrumented_cost,
        "total_split_input_tokens": total_split_input_tokens,
        "total_split_output_tokens": total_split_output_tokens,
        "total_split_cache_read_tokens": total_split_cache_read_tokens,
        "total_split_cache_write_tokens": total_split_cache_write_tokens,
        "total_instrumented_input_tokens": total_instrumented_input_tokens,
        "total_instrumented_output_tokens": total_instrumented_output_tokens,
        "total_instrumented_cache_read_tokens": total_instrumented_cache_read_tokens,
        "total_instrumented_cache_write_tokens": total_instrumented_cache_write_tokens,
        "total_instr_statements": sum(
            stat["instr_statement_count"] for stat in statistics
        ),
    }


def print_cost_summary(summary):
    """
    Print the cost statistics summary

    Args:
        summary (dict): Dictionary containing summary information
    """
    SEPARATOR_LENGTH = 80
    separator = "=" * SEPARATOR_LENGTH
    subseparator = "-" * SEPARATOR_LENGTH

    print(f"\n{separator}")
    token = "INSTRUMENTATION SUMMARY"
    title = " " * ((SEPARATOR_LENGTH - len(token)) // 2) + token
    print(title)
    print(f"{separator}")
    print(f"Total files instrumented:         {summary['total_instr_files']}")
    max_file_lines_str = ""
    for f in summary["longest_files"]:
        max_file_lines_str += f"{f['file']} ({f['original_lines']}), "

    max_file_lines_str = max_file_lines_str[:-2]
    print(
        f"Total original code lines:        {summary['total_original_lines']}\n  - Max {len(summary['longest_files'])} files: {max_file_lines_str}"
    )
    print(f"Total instrumentation statements: {summary['total_instr_statements']}")
    print(f"{subseparator}")
    print("COSTS:")
    print(f"  Total cost:                     ${summary['total_cost']:.6f}")
    print(f"  Total split cost:               ${summary['total_split_cost']:.6f}")
    print(
        f"  Total instrumented cost:        ${summary['total_instrumented_cost']:.6f}"
    )

    print_token = True
    if print_token:
        print(f"{subseparator}")
        print("TOKENS:")
        print(
            f"  Total split input tokens:       {summary['total_split_input_tokens']}"
        )
        print(
            f"  Total split output tokens:      {summary['total_split_output_tokens']}"
        )
        print(
            f"  Total split cache read:         {summary['total_split_cache_read_tokens']}"
        )
        print(
            f"  Total split cache write:        {summary['total_split_cache_write_tokens']}"
        )
        print(
            f"  Total instrumented input:       {summary['total_instrumented_input_tokens']}"
        )
        print(
            f"  Total instrumented output:      {summary['total_instrumented_output_tokens']}"
        )
        print(
            f"  Total instrumented cache read:  {summary['total_instrumented_cache_read_tokens']}"
        )
        print(
            f"  Total instrumented cache write: {summary['total_instrumented_cache_write_tokens']}"
        )

    print(f"\n{separator}")
    token = "FILE COUNTS BY EXTENSION"
    title = " " * ((SEPARATOR_LENGTH - len(token)) // 2) + token
    print(title)
    print(f"{separator}")

    # Sort extensions by count (descending)
    sorted_extensions = sorted(
        summary["extension_counts"].items(), key=lambda x: x[1], reverse=True
    )

    for ext, count in sorted_extensions:
        print(f"  {ext:<10} {count:>6}")


def collect_instrument_data(directory, extensions=None, output=None):
    """
    Collect and analyze cost statistics from files in the specified directory

    Args:
        directory (str): Directory path to search
        extensions (list): List of file extensions to search for
        output (str): Output CSV file path
    """
    logger.info(f"Searching directory: {directory}")

    # process extensions
    processed_extensions = []
    if extensions:
        for ext in extensions:
            # check if there is a comma-separated format
            if "," in ext:
                # split and add each extension
                comma_extensions = [e.strip() for e in ext.split(",") if e.strip()]
                processed_extensions.extend(comma_extensions)
            else:
                processed_extensions.append(ext)

        logger.info(f"File extensions: {', '.join(processed_extensions)}")
        extensions = processed_extensions

    # Collect statistics
    statistics = collect_instrument_code_data(directory, extensions)

    if not statistics:
        logger.info("No cost statistics found.")
        return

    # Generate summary
    summary = generate_summary(statistics)

    # Print summary
    print_cost_summary(summary)

    # Save to CSV
    if output:
        import pandas as pd

        df = pd.DataFrame(statistics)
        df.to_csv(output, index=False)
        logger.info(f"Statistics saved to: {output}")


def setup_instrument_data_parser(subparsers):
    """Setup the statistics subcommand parser"""
    instrument_data_parser = subparsers.add_parser(
        "instrument_data", help="collect and analyze instrumentation data"
    )
    instrument_data_parser.add_argument(
        "directory", help="directory to search for instrumentation data"
    )
    instrument_data_parser.add_argument(
        "--extensions", nargs="+", help="file extensions to search for"
    )
    instrument_data_parser.add_argument("--output", help="output CSV file path")
    return instrument_data_parser
