import re

from loguru import logger

from app.agents.common import (
    FILE_TRACE_PATTERN,
    TRACE_PATTERN,
    delete_instrumentation_comments,
)
from app.utils.utils import (
    detect_language,
    format_code,
    get_comment_token,
    get_multiline_comment_tokens,
    load_code_from_file,
)

GLOBAL_BLOCK = ("Global", 0)
INSTRUMENT_BLOCK = ("Instrumentation", 0)


class TraceCollector:
    def __init__(self, file_path: str):
        self.file_path: str = file_path
        self.language: str = detect_language(self.file_path)
        self.comment_token: str = get_comment_token(self.language)
        self.multiline_comment_tokens: tuple[str, str] | tuple[None, None] = (
            get_multiline_comment_tokens(self.language)
        )
        self.line2code: dict[int, str] = delete_instrumentation_comments(
            load_code_from_file(self.file_path), self.comment_token
        )
        self.begin_copyright_lines: int = self._count_copyright_comments()
        if self.begin_copyright_lines > 0:
            logger.info(
                f"There are {self.begin_copyright_lines} lines of copyright comments at the beginning of {self.file_path}"
            )
        self.line2blocks: dict[int, list[tuple[str, int]]] = {}
        self.block2cov: dict[tuple[str, int], int] = {}
        self.block2lines: dict[tuple[str, int], tuple[int, int]] = (
            {}
        )  # block -> lines (with additional instrumentation comments)
        self.block2real_lines: dict[tuple[str, int], tuple[int, int]] = (
            {}
        )  # block -> the real lines (without additional instrumentation comments)
        self.real_line2line: dict[int, int] = {}
        self.size: int = len(self.line2code)
        self.instrumentation_cnt: int = 0
        self._parse_source_code_to_blocks()
        self.summary: dict[int, str] = {}

        # logger.debug(self._str_for_debug())

        # check to ensure the mapping is correct
        for block in self.block2real_lines:
            real_line_start, real_line_end = self.block2real_lines[block]
            line_start, line_end = self.block2lines[block]
            assert line_start == self.real_line2line[real_line_start]
            assert line_end == self.real_line2line[real_line_end]

    def _str_for_debug(self):
        _debug_str = ""
        # print all variables and their values (formatted)
        for var, value in vars(self).items():

            if isinstance(value, dict):
                _debug_str += f"==={var}===\n"
                for k, v in value.items():
                    _debug_str += f"{k}: {v}\n"
            else:
                _debug_str += f"*{var}*: {value}\n"
        return _debug_str

    def get_real_line_size(self):
        return len(self.real_line2line)

    def get_function_real_lines(self, func_name: str) -> set[int]:
        """
        Get the real lines of a function.
        """
        function_real_lines = set()
        for block, lines in self.block2real_lines.items():
            if block[0] == func_name:
                function_real_lines.update(range(lines[0], lines[1] + 1))
        return function_real_lines

    def get_function_line_cov(self, func_name: str) -> tuple[int, int]:
        """
        Get the line coverage of a function.
        """
        real_line2cov = self.get_real_line_coverage()
        function_real_lines = self.get_function_real_lines(func_name)
        func_covered_lines = 0
        for real_line in function_real_lines:
            if real_line2cov[real_line] > 0:
                func_covered_lines += 1

        assert len(function_real_lines) > 0
        return (func_covered_lines, len(function_real_lines))

    def get_exec_block_cov(
        self, func_name: str, exec_block_ids: list[int]
    ) -> tuple[int, int]:
        """
        Get the block coverage of a function.
        """

        function_real_lines = self.get_function_real_lines(func_name)

        exec_lines = set()

        for real_line in function_real_lines:
            line = self.real_line2line[real_line]
            for block_id in exec_block_ids:
                if self.line2blocks[line][-1] == (func_name, block_id):
                    exec_lines.add(real_line)

        assert len(function_real_lines) > 0
        assert len(exec_lines) <= len(function_real_lines)
        return (len(exec_lines), len(function_real_lines))

    def _count_copyright_comments(self):
        """
        Delete copyright notice comment blocks from the beginning of the file.
        Handles both multiline comment blocks (/* */, etc.) and consecutive single-line comments.

        Returns:
            int: Number of lines removed
        """
        lines = [self.line2code[i] for i in range(1, len(self.line2code) + 1)]

        # Skip leading empty lines
        current_line = 0
        # max_lines_to_check = min(150, len(lines))
        max_lines_to_check = len(lines)

        while current_line < max_lines_to_check and not lines[current_line].strip():
            current_line += 1

        if current_line >= max_lines_to_check:
            return 0  # File is empty or only contains empty lines

        # Define copyright-related keywords to identify copyright notices
        copyright_keywords = [
            "copyright",
            "license",
            "redistribution",
            "permission",
            "author",
            "rights reserved",
            "copying",
            "licensed",
        ]

        # Handle multiline comment blocks (/* */, """, etc.)
        if self.multiline_comment_tokens != (None, None):
            start_token, end_token = self.multiline_comment_tokens

            # Check if the file starts with a multiline comment
            first_non_empty_line = lines[current_line].strip()

            if first_non_empty_line.startswith(start_token):
                # Find the end of the multiline comment block
                comment_block_start = current_line
                comment_block_end = -1

                # Handle the case where start and end are on the same line
                if end_token in first_non_empty_line[len(start_token) :]:
                    comment_block_end = current_line
                else:
                    # Search for the end token
                    for i in range(current_line + 1, max_lines_to_check):
                        if end_token in lines[i]:
                            comment_block_end = i
                            break

                # If we found a complete multiline comment block
                if comment_block_end != -1:
                    # Check if it contains copyright information
                    comment_block = "\n".join(
                        lines[comment_block_start : comment_block_end + 1]
                    ).lower()

                    if any(keyword in comment_block for keyword in copyright_keywords):
                        # Remove the copyright block
                        lines_to_remove = comment_block_end + 1
                        return lines_to_remove

        # Handle consecutive single-line comments
        comment_token = self.comment_token
        consecutive_comments_start = current_line
        consecutive_comments_end = -1

        # Check if the file starts with a single-line comment
        if lines[current_line].strip().startswith(comment_token):

            # Find consecutive comment lines
            for i in range(current_line, max_lines_to_check):
                if (lines[i].strip()) and (lines[i].strip().startswith(comment_token)):
                    consecutive_comments_end = i
                else:
                    # Non-comment line found, end of block
                    break

            # If we found consecutive comment lines
            if consecutive_comments_end != -1:
                # Check if they contain copyright information
                comment_block = "\n".join(
                    lines[consecutive_comments_start : consecutive_comments_end + 1]
                ).lower()

                if any(keyword in comment_block for keyword in copyright_keywords):
                    # Remove the copyright block
                    lines_to_remove = consecutive_comments_end + 1
                    return lines_to_remove

        # No copyright block found or removed
        return 0

    # Map source code line numbers to block IDs
    def _parse_source_code_to_blocks(self):

        block_id_stack: list[tuple[str, int]] = [GLOBAL_BLOCK]

        self.instrumentation_cnt = 0
        for i in range(1, self.size + 1):
            line = self.line2code[i]
            match = re.match(TRACE_PATTERN, line.strip())
            if match:
                self.instrumentation_cnt += 1
                action, func_name, bb_id = match.groups()
                block_id = (func_name, int(bb_id))
                self.line2blocks[i] = [INSTRUMENT_BLOCK]
                if action == "enter":
                    block_id_stack.append(block_id)
                    self.block2lines[block_id] = [
                        i + 1,
                        i + 1,
                    ]  # i+1 may still be an instrumentation comment, we will adjust it when finding the end of the block
                    self.block2real_lines[block_id] = [
                        i + 1 - self.instrumentation_cnt,
                        i + 1 - self.instrumentation_cnt,
                    ]
                else:
                    last_block_id = block_id_stack.pop()
                    if last_block_id != block_id:
                        logger.error(
                            "block ID mismatch at line {}:\nexpect {}, got {}",
                            i,
                            last_block_id,
                            block_id,
                        )
                    self.block2lines[block_id][1] = i - 1
                    self.block2real_lines[block_id][1] = self.block2lines[block_id][
                        1
                    ] - (self.instrumentation_cnt - 1)

                    # adjust the [start, end] of the block to skip nested instrumentation comments
                    new_start, new_end = self.block2lines[block_id]
                    while (
                        new_start < self.size
                        and new_start < new_end
                        and self.line2blocks[new_start][-1] == INSTRUMENT_BLOCK
                    ):
                        new_start += 1
                    while (
                        new_end > 1
                        and new_start < new_end
                        and self.line2blocks[new_end][-1] == INSTRUMENT_BLOCK
                    ):
                        new_end -= 1
                    self.block2lines[block_id] = [new_start, new_end]

                    if self.block2lines[block_id][1] < self.block2lines[block_id][0]:
                        logger.error(
                            "block {} end line {} is less than start line {}",
                            block_id,
                            self.block2lines[block_id][1],
                            self.block2lines[block_id][0],
                        )
            else:
                self.real_line2line[i - self.instrumentation_cnt] = i
                self.line2blocks[i] = block_id_stack.copy()

        # self.block2lines[GLOBAL_BLOCK] = [1, self.size]
        # assert self.real_line2line[self.size - self.instrumentation_cnt] == self.size
        # self.block2real_lines[GLOBAL_BLOCK] = [1, self.size - self.instrumentation_cnt]

    def get_line_covered_times(self, line_no: int) -> int:
        return self.block2cov.get(self.line2blocks[line_no][-1], 0)

    def get_last_summary_as_code(self) -> str:
        return format_code(self.summary, self.language, numbered=False, qouted=True)

    def get_real_line_content(self, real_line_no: int) -> str:
        return self.line2code[self.real_line2line[real_line_no]]

    def get_real_line_coverage(self) -> dict[int, int]:
        real_line2cov = {}
        for real_line_no in range(1, len(self.real_line2line) + 1):
            real_line2cov[real_line_no] = self.get_line_covered_times(
                self.real_line2line[real_line_no]
            )
        return real_line2cov

    # Update execution summary with the given execution trace, and return whether the coverage is updated
    def collect_trace(
        self,
        trace_str: str,
        target_lines: tuple[int, int] | tuple[None, None] = (None, None),
        add_coverage: bool = True,
    ) -> tuple[int, bool, str]:
        """
        Collect execution trace and update coverage summary.

        Args:
            trace_str: The execution trace
            target_lines: The target lines (real lines without instrumentation) to collect coverage
            add_coverage: Whether to add coverage information

        Returns:
            - The number of new covered lines
            - Whether the target lines are covered (return True if target_lines is None)
            - The execution summary
        """
        target_lines_prev_cov = []
        if target_lines != (None, None):
            target_lines_prev_cov = [
                self.get_line_covered_times(self.real_line2line[line])
                for line in range(target_lines[0], target_lines[1] + 1)
            ]

        new_covered_lines = 0
        new_covered_line_contents: dict[int, str] = {}
        executed_blocks = get_executed_blocks(trace_str)
        if add_coverage:
            GLOBAL_BLOCK_first_covered = False
            for block in executed_blocks:
                prev_cov = self.block2cov.get(block, 0)
                self.block2cov[block] = prev_cov + 1
                if block == GLOBAL_BLOCK:
                    GLOBAL_BLOCK_first_covered = True if prev_cov == 0 else False
                    continue
                if prev_cov == 0:  # newly covered block
                    block_start_real_line = self.block2real_lines[block][0]
                    block_end_real_line = self.block2real_lines[block][1]
                    for real_line in range(
                        block_start_real_line,
                        block_end_real_line + 1,
                    ):
                        if (
                            self.get_real_line_content(
                                real_line
                            ).strip()  # only count non-empty lines
                            and self.line2blocks[self.real_line2line[real_line]][-1]
                            == block  # consider nested situations
                        ):
                            new_covered_lines += 1
                            assert real_line not in new_covered_line_contents
                            new_covered_line_contents[real_line] = self.line2code[
                                self.real_line2line[real_line]
                            ]
            if GLOBAL_BLOCK_first_covered:
                assert (
                    new_covered_lines > 0
                ), f"File {self.file_path} is newly covered but the count of newly covered lines is 0"

            # sort the dict new_covered_line_contents by the real line number
            new_covered_line_contents = dict(
                sorted(new_covered_line_contents.items(), key=lambda x: x[0])
            )

            logger.debug(
                "Newly covered code contents:\n{}",
                (
                    "\n".join(
                        f"{real_line}: {new_covered_line_contents[real_line]}"
                        for real_line in new_covered_line_contents
                    )
                    if new_covered_line_contents
                    else "(no newly covered code)"
                ),
            )

        summary_list = []
        visited_block = set()
        indent = ""
        for line_no in range(self.begin_copyright_lines + 1, self.size + 1):
            blocks = self.line2blocks[line_no].copy()
            code = self.line2code[line_no]
            match = re.match(r"^(\s*)", code)
            indent = match.group(1) if match else ""

            if blocks[-1] == INSTRUMENT_BLOCK:
                continue
            elif blocks[-1] == GLOBAL_BLOCK:
                summary_list.append(code)
                continue
            # Add a summary at the start of each block
            if blocks[-1] not in visited_block:
                visited_block.add(blocks[-1])

                skip_block = False
                # if any parent block is not executed, skip the current block (don't add a comment)
                for parent_block in blocks[:-1]:
                    if parent_block not in executed_blocks:
                        skip_block = True
                        break
                if skip_block:
                    continue
                # block_cov = self.block2cov.get(blocks[-1], 0)

                # Add comment for unexecuted lines
                if blocks[-1] not in executed_blocks:
                    start_line = self.block2lines[blocks[-1]][0]
                    end_line = self.block2lines[blocks[-1]][1]

                    real_start_line = self.block2real_lines[blocks[-1]][0]
                    real_end_line = self.block2real_lines[blocks[-1]][1]

                    lines_with_coverage = 0
                    total_real_lines = 0
                    for line in range(start_line, end_line + 1):
                        if not self.line2code[line].strip():
                            continue
                        if re.match(TRACE_PATTERN, self.line2code[line].strip()):
                            continue
                        total_real_lines += 1
                        if self.get_line_covered_times(line) > 0:
                            lines_with_coverage += 1

                    line_cov_ratio = lines_with_coverage / total_real_lines

                    unex_comment = f"{indent}{self.comment_token} unexecuted: ({real_start_line}-{real_end_line}), cov: {lines_with_coverage}/{total_real_lines} ({line_cov_ratio:.1%})"
                    summary_list.append(unex_comment)
            # Add source code for executed lines
            if blocks[-1] in executed_blocks:
                summary_list.append(code)

        # merge consecutive unexecuted comments
        merged_unex_comments = self._merge_unexecuted_comments(summary_list)
        summary_list = merged_unex_comments

        self.summary = {
            1: f"{self.comment_token} {self.file_path} ({self.size - self.instrumentation_cnt} lines total)"
        }
        self.summary.update({i + 2: summary_list[i] for i in range(len(summary_list))})

        if target_lines != (None, None):
            target_lines_cov = [
                self.get_line_covered_times(self.real_line2line[line])
                for line in range(target_lines[0], target_lines[1] + 1)
            ]

            # determine if any target lines are covered
            covered_lines_count = sum(
                1
                for target_line_cov, target_line_prev_cov in zip(
                    target_lines_cov, target_lines_prev_cov
                )
                if target_line_cov > target_line_prev_cov
            )
            is_target_lines_covered = covered_lines_count > 0
        else:
            is_target_lines_covered = True

        return (
            new_covered_lines,
            is_target_lines_covered,
            self.get_last_summary_as_code(),
        )

    def _merge_unexecuted_comments(self, summary_list):
        """Merge consecutive unexecuted code comments, directly extract information from the comment text"""
        # create a new list to store the merged results
        merged_list = []
        i = 0

        # compile the regex, for extracting line number and coverage information
        unexecuted_pattern = re.compile(
            rf"{self.comment_token} unexecuted: \((\d+)-(\d+)\), cov: (\d+)/(\d+) \(([0-9.]+)%\)"
        )

        while i < len(summary_list):
            line = summary_list[i]

            # check if the current line is an unexecuted code comment
            if unexecuted_pattern.search(line):
                # find consecutive unexecuted code comments
                consecutive_comments = [line]
                j = i + 1

                while j < len(summary_list):
                    next_line = summary_list[j]
                    if not next_line.strip():
                        j += 1
                        continue
                    if unexecuted_pattern.search(next_line):
                        consecutive_comments.append(next_line)
                        j += 1
                    else:
                        break

                indent_match = re.match(r"^(\s*)", line)
                indent = indent_match.group(1) if indent_match else ""

                # if there are multiple consecutive comments, merge them
                if len(consecutive_comments) > 1:
                    # extract the information from the first comment
                    first_comment = consecutive_comments[0]
                    first_match = unexecuted_pattern.search(first_comment)

                    # extract the information from the last comment
                    last_comment = consecutive_comments[-1]
                    last_match = unexecuted_pattern.search(last_comment)

                    # if failed to extract information, keep the original
                    if not first_match or not last_match:
                        logger.warning(
                            "Failed to extract information from consecutive unexecuted comments"
                        )
                        for comment in consecutive_comments:
                            merged_list.append(comment)
                        i = j
                        continue

                    # get the start line number and end line number
                    start_line = int(first_match.group(1))
                    end_line = int(last_match.group(2))

                    # calculate the total coverage information
                    total_lines_with_coverage = 0
                    total_lines = 0

                    for comment in consecutive_comments:
                        match = unexecuted_pattern.search(comment)
                        if match:
                            total_lines_with_coverage += int(match.group(3))
                            total_lines += int(match.group(4))
                        else:
                            raise ValueError(
                                "Failed to extract information from consecutive unexecuted comments"
                            )

                    # calculate the total coverage ratio
                    overall_cov_ratio = (
                        total_lines_with_coverage / total_lines
                        if total_lines > 0
                        else 0
                    )

                    # create the merged comment
                    merged_comment = f"{indent}{self.comment_token} Unexecuted code (lines {start_line}-{end_line}) removed. Its line cov: {total_lines_with_coverage}/{total_lines} ({overall_cov_ratio:.0%})"
                    merged_list.append(merged_comment)

                    # update the index
                    i = j
                else:
                    # only one comment, add it directly but we need to change the format
                    match = unexecuted_pattern.search(line)
                    if match:
                        # percentage already has % symbol, no need to use .1% format
                        start_line = match.group(1)
                        end_line = match.group(2)
                        lines_with_cov = match.group(3)
                        total_lines = match.group(4)
                        cov_ratio = float(match.group(5)) / 100  # convert to 0-1 ratio
                        if start_line == end_line:
                            merged_comment = f"{indent}{self.comment_token} Unexecuted code (line {start_line}) removed. Its line cov: {lines_with_cov}/{total_lines} ({cov_ratio:.0%})"
                        else:
                            merged_comment = f"{indent}{self.comment_token} Unexecuted code (lines {start_line}-{end_line}) removed. Its line cov: {lines_with_cov}/{total_lines} ({cov_ratio:.0%})"
                    else:
                        raise ValueError(
                            "Failed to extract information from consecutive unexecuted comments"
                        )
                    merged_list.append(merged_comment)
                    i += 1
            else:
                # non-comment line, add it directly
                merged_list.append(line)
                i += 1

        return merged_list


def get_executed_blocks(trace_str: str) -> set[tuple[str, int]]:

    executed_blocks = set()
    executed_blocks.add(GLOBAL_BLOCK)

    for line in trace_str.split("\n"):
        match = re.match(TRACE_PATTERN, line.strip())
        if match:
            action, func_name, bb_id = match.groups()
            executed_blocks.add((func_name, int(bb_id)))

    return executed_blocks


def trace_compress(trace: str) -> list[tuple[str, str, list[int]]]:
    """
    Compress trace into call chain: [filename1][function_name1] -> [filename2][function_name2]

    Args:
        trace: original trace string

    Returns:
        compressed trace string
    """
    lines = trace.strip().split("\n")

    last_file_and_func = (None, None)
    cur_func_blocks = set()

    call_chain = []

    for line in lines:
        matches = re.findall(FILE_TRACE_PATTERN, line.strip())
        if len(matches) == 0:
            continue

        for match in matches:
            file_name, action, func_name, block_id = match
            block_id = int(block_id)
            if last_file_and_func == (None, None):
                last_file_and_func = (file_name, func_name)

            if (file_name, func_name) != last_file_and_func:
                call_chain.append(
                    (
                        last_file_and_func[0],
                        last_file_and_func[1],
                        list(cur_func_blocks),
                    )
                )
                last_file_and_func = (file_name, func_name)
                cur_func_blocks = set()

            if action == "enter":
                cur_func_blocks.add(block_id)

    # Add statistics for the last function
    if last_file_and_func != (None, None) and len(cur_func_blocks) > 0:
        call_chain.append(
            (last_file_and_func[0], last_file_and_func[1], list(cur_func_blocks))
        )

    return call_chain
