"""
Tool for requesting additional code from files.
"""

import os

from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
from loguru import logger

from app.agents.common import (
    MAX_CODE_REQUEST_ATTEMPTS,
    delete_instrumentation_from_code,
)
from app.agents.coverage import Coverage
from app.utils.utils import (
    detect_language,
    format_code,
    get_comment_token,
    get_project_dir,
    load_code_from_file,
)

_CODE_REQUEST_DESCRIPTION = f"""Use this tool to request additional code from files to help with branch selection and constraint generation.

When you need more context to understand program behavior or to make informed decisions about target branches:
1. Specify one or more files you want to examine
2. Optionally specify line ranges for each file (if you only need to see specific sections)

Examples of when to use this tool:
- When you need to understand what happens in an unexecuted branch
- When you need to see variable declarations or type definitions
- When you need to examine code near a potential target branch

<IMPORTANT_PERFORMANCE_REQUIREMENTS>
1. REQUEST ONLY THE CODE YOU NEED for your analysis - be specific and precise
2. BATCH ALL REQUESTS together in ONE SINGLE CALL:
   - REQUEST LARGER CHUNKS (e.g., 50-100 lines) instead of multiple small requests (e.g., 10-20 lines)
   - COMBINE related code sections in a single request, whether they are:
     * Sequential regions, e.g., sequential two requests for lines 100-130 and 130-160 can be combined into one request for 100-160
     * Scattered regions, e.g., multiple requests for lines 20-25, 30-45, and 50-55 can be combined into one request for 20-55
3. AVOID requesting entire large files when possible - request focused regions relevant to your analysis
4. You have a STRICT LIMIT of {MAX_CODE_REQUEST_ATTEMPTS} on the number of code requests you can make during this session. Use each request wisely and make them count!
</IMPORTANT_PERFORMANCE_REQUIREMENTS>

ALWAYS ASK YOURSELF before making a new code request:
- Have you requested a large enough region to understand the context?
- Are you planning to request adjacent lines next? If so, include them now in a larger chunk!
- Are you planning to request multiple small sections? If so, include all of them in a single request!
- Can you anticipate what other code sections you might need soon and include them now?
- Is this request absolutely necessary? Remember you have a LIMITED number of requests available!

The tool will return all requested code snippets with line numbers for reference. The returned code will also include coverage information in the following format:
```
30|  | FILE *file = fopen(filename, "r");
31|  | if (!file) {{
32| -|     perror("Failed to open file");
33| -|     exit(1);
34|  | }}
```

Where:
- First column: Line number in the file
- Second column: Coverage indicator. 
    1. '-' means it has not been covered by any test cases in the existing test suite (e.g., `perror("Failed to open file");` in the example above)
    2. empty space ' ' means the line has already been covered in the existing test suite (e.g., `FILE *file = fopen(filename, "r");` in the example above)
- Third column: The actual code content
"""

# Define the code request tool
CodeRequestTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="request_code",
        description=_CODE_REQUEST_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "file_requests": {
                    "type": "array",
                    "description": "List of files and their line ranges to request",
                    "items": {
                        "type": "object",
                        "properties": {
                            "filepath": {
                                "type": "string",
                                "description": "Relative path to the file",
                            },
                            "lines": {
                                "type": "string",
                                "description": 'Line range in format "start-end" (e.g., "10-20"). Leave empty to request entire file.',
                            },
                        },
                        "required": ["filepath"],
                    },
                }
            },
            "required": ["file_requests"],
        },
    ),
)


def process_code_request(
    file_requests: list[dict] | None, remaining_attempts: int
) -> str:
    """
    Process code request by reading files and formatting their content.

    Args:
        file_requests: List of dictionaries containing filepath and optional line range

    Returns:
        Formatted code content or error message
    """

    if file_requests is None or not isinstance(file_requests, list):
        logger.warning("No `file_requests` provided or it is not a list.")
        return "Error: No `file_requests` provided or it is not a list. Please provide valid `file_requests`."

    num_files = len(file_requests)
    files = [(req.get("filepath"), req.get("lines", "ALL")) for req in file_requests]
    logger.info(
        f"Code request received for {num_files} file(s): {', '.join(f'{file[0]} ({file[1]})' for file in files)}"
    )

    # Process each file request
    code_snippets = []
    had_errors = False
    error_messages = []
    total_lines_requested = 0

    coverage = Coverage.get_instance()

    for file_request in file_requests:
        filepath = file_request.get("filepath")
        lines_text = file_request.get("lines", "")

        if filepath is None:
            error_msg = "Error: There is an `filepath` with value `None` in the `file_request`. Please provide a valid `filepath`."
            error_messages.append(error_msg)
            logger.info("One of the `filepath` is None.")
            had_errors = True
            continue
        elif filepath == "":
            error_msg = "Error: There is an `filepath` with empty string value in the `file_request`. Please provide a valid `filepath`."
            error_messages.append(error_msg)
            logger.info("One of the `filepath` is empty.")
            had_errors = True
            continue

        file_to_request = None

        # This should be relative path since we only provide relative path in the execution trace
        relative_filepath = os.path.normpath(filepath)
        # try both absolute and relative paths
        absolute_filepath = os.path.join(get_project_dir(), filepath)

        if not os.path.exists(relative_filepath) and not os.path.exists(
            absolute_filepath
        ):
            error_msg = f"Error: '{filepath}' not found. Please check the file path and try again."
            error_messages.append(error_msg)
            logger.info(f"Path not found: {filepath}")
            had_errors = True
            continue
        elif os.path.exists(relative_filepath):
            file_to_request = relative_filepath
        elif os.path.exists(absolute_filepath):
            file_to_request = absolute_filepath

        if os.path.isdir(file_to_request):
            error_msg = f"Error: '{filepath}' is a directory. Please provide a valid file path. Files in the directory {filepath} contains: {os.listdir(file_to_request)}"
            error_messages.append(error_msg)
            logger.info(f"Requested path '{filepath}' is a directory")
            had_errors = True
            continue

        try:
            source_code = load_code_from_file(file_to_request)
        except Exception as e:
            error_msg = f"Error: Failed to load code from file '{filepath}', ensure the file is textual. Error:\n{e}"
            error_messages.append(error_msg)
            logger.info(f"Failed to load code from file '{filepath}'")
            had_errors = True
            continue

        file_language = detect_language(file_to_request)
        comment_token = get_comment_token(file_language)
        source_code = delete_instrumentation_from_code(source_code, comment_token)
        total_lines = len(source_code)

        # Default to entire file
        start, end = 1, total_lines

        # Process line range if provided
        if lines_text:
            line_range = lines_text.split("-")
            if len(line_range) == 2:
                try:
                    start, end = min(int(line_range[0]), int(line_range[1])), max(
                        int(line_range[0]), int(line_range[1])
                    )

                    if start > total_lines:
                        error_msg = f"Line number {start} is greater than the total line number of file '{filepath}' ({total_lines} lines). Thus, we DO NOT return any code."
                        logger.info(error_msg)
                        error_messages.append(error_msg)
                        had_errors = True
                        continue
                    # Validate range bounds
                    elif end > total_lines:
                        error_msg = f"Line number {end} is greater than the total line number of file '{filepath}' ({total_lines} lines). Thus, we clip the end to the last line."
                        logger.info(error_msg)
                        end = total_lines
                        error_messages.append(error_msg)
                        had_errors = True
                        assert start <= end

                except ValueError:
                    error_msg = f"Error: Invalid line numbers in range '{lines_text}' for file '{filepath}'. Line numbers must be integers."
                    error_messages.append(error_msg)
                    logger.info(f"Invalid line numbers in range: {lines_text}")
                    had_errors = True
                    continue
            elif (
                len(line_range) == 1 and line_range[0].isdigit()
            ):  # fault tolerance for line number without range
                start = int(line_range[0])
                end = start
            else:
                error_msg = f"Error: Invalid line range format '{lines_text}' for file '{filepath}'. Expected format is 'start-end'."
                error_messages.append(error_msg)
                logger.info(f"Invalid line range format: {lines_text}")
                had_errors = True
                continue

        # Update the total lines counter
        lines_in_segment = end - start + 1
        total_lines_requested += lines_in_segment

        _copy_right_lines = coverage.get_file_coverage(
            relative_filepath
        ).begin_copyright_lines
        has_copyright_lines = False

        adjusted_start = start

        if (
            _copy_right_lines > 0
            and start <= _copy_right_lines
            and end > _copy_right_lines
        ):
            adjusted_start = _copy_right_lines + 1
            has_copyright_lines = True

        code_segment = format_code(
            source_code,
            file_language,
            numbered=True,
            qouted=True,
            range=(adjusted_start, end),
            line2cov=coverage.get_file_coverage(
                relative_filepath
            ).get_real_line_coverage(),
            numbering_style="prefix",
        )

        # Add a more distinctive header for each code segment
        segment_header = f"{'='*20}\n[FILE: {relative_filepath} ({total_lines} lines total)] [LINES: {start}-{end}]:\n('-' means have NOT been covered, '+' means have been covered{'' if not has_copyright_lines else f', lines {start}-{_copy_right_lines} are omitted due to copyright comments'})\n{'='*20} "
        code_snippets.append(f"{segment_header}\n{code_segment}")

    # Log the total lines requested
    logger.info(f"Total lines of code requested: {total_lines_requested}")

    result = ""

    # Return errors if any occurred, otherwise return code snippets
    if had_errors:
        if not code_snippets:
            # If no files were successfully read, return all error messages
            result = "\n\n".join(error_messages)
        else:
            # If some files were read successfully, append errors at the end
            result = "\n\n".join(code_snippets)
            if error_messages:
                result += (
                    "\n\n"
                    + "!" * 20
                    + "\nWARNINGS:\n"
                    + "!" * 20
                    + "\n"
                    + "\n".join(error_messages)
                )
        logger.info(f"Code request WARNINGS:\n{error_messages}")
    else:
        result = "\n\n".join(code_snippets)

    if remaining_attempts > 0:
        result += f"\n\n NOTE: You have {remaining_attempts} attempts for code requests left and use them wisely (e.g., batch multiple requests together in one single call)!"
    else:
        if remaining_attempts < 0:
            logger.warning(
                f"Max code request attempts reached, but LLM still required {-remaining_attempts} more attempts.",
            )
        else:
            logger.info(
                f"Max code request attempts reached ({MAX_CODE_REQUEST_ATTEMPTS} times). Forcing selection of target branch.",
            )
        result += f"\n\n NOTE: You have reached the maximum number of code request attempts ({MAX_CODE_REQUEST_ATTEMPTS} times). Please proceed based on current information. DO NOT make any more code requests!"
    return result
