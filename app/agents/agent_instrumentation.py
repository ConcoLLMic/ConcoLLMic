"""
This agent negates and solves input constraints 
"""

import random
import re
import string
from xml.sax.saxutils import unescape

from loguru import logger

from app.agents.common import (
    INSTRUMENTED_COST_FORMAT,
    SPLIT_COST_FORMAT_WITH_CHUNKS,
    TOTAL_COST_FORMAT,
    TRACE_PATTERN,
    ExampleAssistantOutput,
    ExampleUserInput,
    FilePath,
    Instructions,
    InstrumentedCode,
    ResponseParseException,
    SourceCode,
    extract_between_tags,
    parse_tool_arguments,
    wrap_between_tags,
)
from app.agents.tools import (
    ReportFuncFinishTool,
    ReportFunctionsTool,
    process_report_func_finish,
    process_report_functions,
)
from app.data_structures import MessageThread
from app.model import claude
from app.model.common import Usage
from app.utils.utils import (
    detect_language,
    format_code,
    get_comment_token,
    load_code_from_file,
    restore_deleted_blocks,
    strip_qoutes,
)

NO_INSTRUMENTATION_NEEDED = "NO_INSTRUMENTATION_NEEDED"

INSTR_SYSTEM_PROMPT = f"""
You are a code instrumentation expert. Your task is to insert logging statements to track the execution flow of basic blocks in the given code snippet (the given code snippet may be incomplete, you DO NOT need to complete the code).

**Tasks**:
1. First, determine if the code snippet needs instrumentation:
   - If the code snippet ONLY contains declarations without any executable code (i.e., ONLY contains function declarations, class/enum definitions without implementations, or type definitions), output ONLY `<{InstrumentedCode.__xml_tag__}>{NO_INSTRUMENTATION_NEEDED}</{InstrumentedCode.__xml_tag__}>` and stop.
   - Note: Any executable code, including top-level code not wrapped in functions (common in Python, JavaScript etc.), should be instrumented.
   - Otherwise, proceed with instrumentation.

2. Identify code to instrument, focusing ONLY on:
   a) Function/method implementations (code blocks with curly braces {{}} or indented blocks in Python), INCLUDING constructors, destructors, and other special member functions
   b) Top-level executable code (code not wrapped in functions but still executed)
   DO NOT instrument at class/enum definition level or any non-executable code structures (such as pure declarations). 
  
3. Instrument ALL basic blocks in the code:
   - A basic block is a sequence of statements that is executed linearly and has a *single* entry/exit point. 
   - Ensure that exactly *one* enter and *one* exit logging statements are added for each block.
   - For the code needing instrumentation, pay attention to the control flow statements that split the code into multiple blocks, including 
     a) Branch statements (if, else, switch-case, etc.)
     b) Loop statements (for, while, etc.)
   - The instrumention must *only* make necessary changes to the code. Avoid expanding function prototypes or shifting code segments.
   - For other code structures that don't need instrumentation, they MUST still be preserved in the output exactly as they appear in the input WITHOUT ANY MODIFICATION, including the original code comments.

4. Use the *appropriate logging method for the target language* to instrument EVERY basic block:
   1. Insert BEFORE each block: "enter <unique_function_name> <basic_block_id>".
    - For top-level code, use "module" or the filename as the function name
   2. Insert AFTER each block: "exit <unique_function_name> <basic_block_id>". 
    - For example, for switch-case statements, you should insert the logging statement AFTER the "break" statement; for function definitions, you should insert the logging statement AFTER the "return" statement. 
    - Even though the exit logging statement after a return will never be executed at runtime, it MUST be placed AFTER the return statement in the code to correctly represent the control flow structure.
    - IMPORTANT: All "exit" logging statements should be commented out (e.g., `// fprintf(stderr, "exit func 1\n");` in C/C++). They serve only as MARKERS in the code for text analysis purposes and should not be executed at runtime. Only "enter" statements should be active and executable.
   3. Use the appropriate logging method for the target language:
    - e.g., `fprintf(stderr, ...)` for C/C++, `sys.stderr.write(...)` for Python, etc.
    HEADER_REQUIREMENTS_PLACEHOLDER
   4. Place each logging statement in a standalone line. Do NOT insert logging statements to the same line as the original code logic.

5.IMPORTANT things to remember: 
- DO NOT skip any basic blocks, including similar patterns like switch-cases and simple conditional statements like following code:
```
if (condition)
    statement;
```
    In above, you should instrument before and after the "statement" (with essential brackets) to ensure this basic block is correctly tracked.
- The logging information should be output to the standard error stream (stderr).
- DO NOT create nested instrumentation - basic blocks are sequential, not nested. For example:
```
"enter func 1"          // INCORRECT - Nested instrumentation
[Sequential statements...]
if (condition) {{
    "enter func 2"      // This creates nesting with "enter func 1"
    [Sequential statements...]
    // "exit func 2"
}}
// "exit func 1"
```
    This is incorrect because it suggests blocks can be nested, which violates the sequential nature of basic blocks.
    The correct instrumentation should be:
```
"enter func 1"          // CORRECT - Sequential blocks
[Sequential statements...]
// "exit func 1"           // First block ends before if statement (commented out as per requirement)
if (condition) {{
    "enter func 2"      // New block starts inside if
    [Sequential statements...]
    // "exit func 2"       // Blocks are sequential, not nested (commented out as per requirement)
}}
```
- ENSURE that the "enter" and "exit" logging statements are paired correctly.

6. Maintain the exact indentation of both original and logging statements. 

**Output Format**:
Output only the WHOLE INSTRUMENTED CODE in `<{InstrumentedCode.__xml_tag__}>` tags. Check the output code THOROUGHLY to ensure:
1. ALL original code is preserved without any loss, including code comments
2. Have CORRECTLY PLACED and PAIRED logging statements for ALL basic blocks
"""


HEADER_SUPPLEMENTAL_REQUIREMENTS = "- If the original code doesn't include necessary header files or import statements required for the logging method, add them at the beginning of the code, e.g., `#include <stdio.h>` for fprintf, `import sys` for sys.stderr.write"

src_example_file = "./code_example/prompt/sleep.c"
src_example_language = "c"

instrumented_example_file = "./code_example/prompt/sleep.c.instr"

SOURCE_CODE_EXAMPLE = format_code(
    load_code_from_file(src_example_file),
    src_example_language,
    numbered=False,
    qouted=True,
)

INSTRUMENTED_CODE_EXAMPLE = format_code(
    load_code_from_file(instrumented_example_file),
    src_example_language,
    numbered=False,
    qouted=True,
)

INSTRUMENTATION_TEMPERATURE = 0


FILE_SPLIT_SYSTEM_PROMPT = f"""
You are an expert code analyzer specializing in function detection. Your task is to meticulously identify and report the signature of EVERY function implementation in the given code file.

**Important Rules**:
1. Scan the ENTIRE file line by line to ensure no functions are missed
2. Include ALL types of functions implementations while discarding function declarations
3. The extracted signature must be EXACTLY as it appears in the code - do not reformat or modify it in any way


**Process for Function Detection**:
1. Use the `{ReportFunctionsTool['function']['name']}` tool to submit batches of function signatures as you find them
2. Continue scanning the entire file, submitting all function signatures you find
3. Once you've reported ALL functions, or confirmed there are no function implementations in the file, use the `{ReportFuncFinishTool['function']['name']}` tool to complete the process.

Remember that accuracy is CRUCIAL - the signatures will be used for exact string matching in the original file.
"""


def generate_random_id(length: int = 4) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def _str_block_id(block_id: tuple[str, int]) -> str:
    return f"{block_id[0]} {block_id[1]}"


def check_instrumentation(instrumented_code: str) -> tuple[bool, str]:
    """
    Check if the instrumentation is correct.
    Args:
        instrumented_code: instrumented code
    Returns:
        A tuple of (is_correct, refined_instrumented_code or error_message).
        is_correct is True if the instrumentation is correct or can be refined, False otherwise.
        The second element is the original instrumented code if the instrumentation is correct or is refined code if can be refined, otherwise, there is error_message indicating the error.

    Note: This function is also capable of recognizing and correctly processing commented-out exit statements
    (e.g., "// fprintf(stderr, "exit func 1\n");"), as the TRACE_PATTERN will match both active and commented-out
    instrumentation statements.
    """

    instrumented_code_lines = instrumented_code.split("\n")
    active_blocks: list[tuple[str, int]] = []
    all_blocks: dict[tuple[str, int], list[tuple[int, str]]] = (
        {}
    )  # block_id (func_name, bb_id) -> list of (line_num, action), action is "enter" or "exit"

    # First pass - collect all block information
    for line_num, line in enumerate(instrumented_code_lines):
        matches = re.finditer(TRACE_PATTERN, line.strip())
        for match in matches:
            action, func_name, bb_id = match.groups()
            block_id = (func_name, int(bb_id))
            if action == "enter":
                if block_id not in all_blocks:
                    all_blocks[block_id] = []
                all_blocks[block_id].append((line_num, "enter"))
                active_blocks.append(block_id)
            else:
                if len(active_blocks) > 0 and active_blocks[-1] == block_id:
                    all_blocks[block_id].append((line_num, "exit"))
                    active_blocks.pop()
                else:
                    error_msg = (
                        f'Block ID mismatch at line {line_num+1}("{line.strip()}"): '
                    )
                    if len(active_blocks) > 0 and active_blocks[-1] != block_id:
                        error_msg += f'expect "exit" for block "{_str_block_id(active_blocks[-1])}", but got "exit" for block "{_str_block_id(block_id)}"'
                        return False, error_msg
                    elif len(active_blocks) == 0:
                        if block_id not in all_blocks:
                            error_msg += f'there is no "enter" statement before "exit" statement for block "{_str_block_id(block_id)}"'
                            return False, error_msg
                        else:
                            # For strict ONE exit per block, uncomment the following
                            error_msg += f'there are multiple "exit" statements for block "{_str_block_id(block_id)}". Ensure there is only one "exit" statement for each "enter" statement'
                            return False, error_msg

                            # Fault tolerance: take the last if there are multiple exits
                            logger.warning(
                                f'there are multiple "exit" statements for block "{_str_block_id(block_id)}"!'
                            )
                            active_blocks.append(block_id)
                            all_blocks[block_id].pop()
                            all_blocks[block_id].append((line_num, "exit"))

    if len(active_blocks) > 3:
        return (
            False,
            f'At the end of the code, these "enter" logging statements have no "exit" logging statements: {", ".join([f"enter {block_id[0]} {block_id[1]}" for block_id in active_blocks])}',
        )
    elif len(active_blocks) > 0:
        # Fault tolerance: if there are only a few, we directly delete them.
        logger.warning(
            f'At the end of the code, these "enter" logging statements have no "exit" logging statements: {", ".join([f"enter {block_id[0]} {block_id[1]}" for block_id in active_blocks])}. Since there are only a few, we directly delete them.'
        )

    # Check and reassign block IDs
    needs_update = False
    update_lines: dict[int, tuple[str, str | tuple[str, int]]] = (
        {}
    )  # line_num (with instrumentation) -> (action: update/delete, content: new_block_id or "")

    for block_id, pairs in all_blocks.items():
        if len(pairs) > 2:  # If a block_id has multiple enter/exit pairs
            needs_update = True
            # Track newly generated IDs to avoid conflicts within the same update
            generated_ids = set()
            for i in range(2, len(pairs), 2):
                # Generate a random ID between 100-1000 that doesn't conflict
                while True:
                    new_id_num = random.randint(100, 5000)
                    # Check if ID already exists in original code
                    specific_pattern = (
                        f"(enter|exit)\\s+{re.escape(block_id[0])}\\s+{new_id_num}"
                    )
                    if (new_id_num not in generated_ids) and (
                        not re.search(specific_pattern, instrumented_code)
                    ):
                        generated_ids.add(new_id_num)
                        break

                new_block_id = (block_id[0], new_id_num)
                update_lines[pairs[i][0]] = ("update", new_block_id)
                update_lines[pairs[i + 1][0]] = ("update", new_block_id)

    for block_id, pairs in all_blocks.items():
        if len(pairs) >= 2:
            for i in range(0, len(pairs), 2):
                enter_line = pairs[i][0]
                exit_line = pairs[i + 1][0]
                if enter_line + 1 == exit_line:
                    needs_update = True
                    update_lines[enter_line] = ("delete", "")
                    update_lines[exit_line] = ("delete", "")
        else:  # the "enter" that has no "exit"
            assert block_id in active_blocks
            assert len(pairs) == 1
            assert pairs[0][1] == "enter"
            needs_update = True
            update_lines[pairs[0][0]] = ("delete", "")

    if needs_update:
        # Second pass - update block IDs
        new_lines = instrumented_code_lines.copy()
        for line_num, (action, content) in update_lines.items():
            # Get original line content
            old_line = new_lines[line_num]
            # Replace block ID
            if action == "update":
                # Use regex to replace block ID in original line
                new_block_id = content
                new_line = re.sub(
                    TRACE_PATTERN,
                    lambda m: m.group(0).replace(
                        f"{m.group(1)} {m.group(2)} {m.group(3)}",
                        f"{m.group(1)} {new_block_id[0]} {new_block_id[1]}",
                    ),
                    old_line,
                )
                new_lines[line_num] = new_line
            elif (
                action == "delete"
            ):  # when deleting, DO NOT directly delete the line, but replace the instrumentation statements (enter/exit func_name bb_id) with a blank content. This ensures that we don't wrongly change the code logic.
                new_line = re.sub(
                    TRACE_PATTERN,
                    lambda m: m.group(0).replace(
                        f"{m.group(1)} {m.group(2)} {m.group(3)}",
                        "",
                    ),
                    old_line,
                )
                new_lines[line_num] = new_line
            else:
                assert False  # should not happen

        return True, "\n".join(new_lines)

    else:
        return True, instrumented_code


def instr_postprocess(instrumented_code: str, mark: str) -> str:
    """
    Postprocess the instrumented code. Add mark (e.g., relative file path) to the instrumented code.
    """
    lines = instrumented_code.split("\n")
    for line_num, line in enumerate(lines):
        match = re.search(TRACE_PATTERN, line)
        if match:
            # extract the matched groups
            action = match.group(1)  # enter or exit
            func_name = match.group(2)  # function name
            bb_id = match.group(3)  # basic block ID

            # replace the matched part, keep the original function call
            replacement = f"[{mark}] {action} {func_name} {bb_id}"
            lines[line_num] = (
                line[: match.start(1)] + replacement + line[match.end(3) :]
            )
    return "\n".join(lines)


def create_chunks(cutoff_points: list[int], chunk_size: int) -> list[tuple[int, int]]:
    """
    cutoff_points: at least 2 elements, sorted in ascending order
    """
    assert len(cutoff_points) >= 2
    assert cutoff_points[0] == 0
    chunks = []
    start_idx = 0

    while start_idx < len(cutoff_points) - 1:
        start = cutoff_points[start_idx]
        end_idx = start_idx + 1

        # if the distance between the next point and the current point is greater than chunk_size, directly form a chunk
        if cutoff_points[end_idx] - start > chunk_size:
            chunks.append((start, cutoff_points[end_idx]))
            start_idx = end_idx
            continue

        while (
            end_idx < len(cutoff_points) - 1
            and cutoff_points[end_idx + 1] - start <= chunk_size
        ):
            end_idx += 1

        chunks.append((start, cutoff_points[end_idx]))
        start_idx = end_idx

    assert len(chunks) >= 1

    assert chunks[-1][1] == cutoff_points[-1]
    assert chunks[0][0] == 0

    return chunks


class InstrumentationAgent:

    # retry times for instrumentation to pass the `check_instrumentation`
    INSTRUMENTATION_RETRY_TIMES = 3

    def __init__(self, model=claude.Claude4_5Sonnet(max_output_token=32768)):
        self.model = model
        self.model.setup()

    def cleanup(self):
        pass

    def __del__(self):
        self.cleanup()

    def split_code(
        self,
        source_code_file: str,
        chunk_size: int,
    ) -> tuple[list[int], bool, Usage]:
        """
        Split code into chunks based on function boundaries and chunk size.
        Returns:
            - list of cutoff lines (0-indexed, do not include the last line and the first line)
            - need_instrument: whether to instrument the code later (If no function implementation is found, we don't need to instrument the code)
            - usage: usage information
        """

        source_code_lines = load_code_from_file(source_code_file)

        source_language = detect_language(source_code_file)

        # Get function signatures
        formatted_code = format_code(
            source_code_lines, source_language, numbered=False, qouted=True
        )

        msg_thread = MessageThread()
        system_prompt = unescape(
            Instructions(instructions=FILE_SPLIT_SYSTEM_PROMPT).to_xml().decode()
        )
        msg_thread.add_system(system_prompt)
        user_prompt = unescape(SourceCode(source_code=formatted_code).to_xml().decode())
        msg_thread.add_user(user_prompt)

        # Define available tools
        available_tools = [ReportFunctionsTool, ReportFuncFinishTool]

        usage = Usage()
        finished = False
        collected_signature_lines = set()

        _no_update_times = 0
        need_instrument = True

        while not finished:
            # Call model with tools support
            response_content, response_tool_calls, call_usage = self.model.call(
                msg_thread.to_msg(),
                temperature=INSTRUMENTATION_TEMPERATURE,
                tools=available_tools,
                tool_choice="any" if available_tools else "auto",
            )

            usage += call_usage

            logger.debug(
                "Model Response for function detection: {}",
                response_content,
            )

            # Add model's response to the message thread
            msg_thread.add_model(response_content, response_tool_calls)

            # Process tool calls if any
            if response_tool_calls:
                for tool_call in response_tool_calls:
                    function_name = tool_call.get("function").get("name")
                    tool_call_id = tool_call.get("id")
                    logger.info("Processing tool call: {}", tool_call)

                    # Parse arguments
                    args = parse_tool_arguments(tool_call)

                    if args is None:
                        observation = "Failed to parse tool call arguments."
                    else:
                        if function_name == ReportFunctionsTool["function"]["name"]:
                            # Collect function signatures
                            observation, signature_lines = process_report_functions(
                                args.get("signatures"),
                                source_code="\n".join(source_code_lines.values()),
                            )
                            pre_size = len(collected_signature_lines)
                            collected_signature_lines.update(signature_lines)
                            post_size = len(collected_signature_lines)
                            if pre_size == post_size:
                                _no_update_times += 1
                                if _no_update_times > 5:
                                    finished = True
                            else:
                                _no_update_times = 0
                        elif function_name == ReportFuncFinishTool["function"]["name"]:
                            # Process finish detection
                            status = args.get("status")
                            observation, is_valid, is_complete = (
                                process_report_func_finish(status)
                            )

                            # If no_functions_list is not None, it means we should use that instead of collected_signatures
                            if is_valid:
                                if (
                                    not is_complete
                                ):  # False means returned "no_functions_found"
                                    assert len(collected_signature_lines) == 0
                                    need_instrument = False
                                # Mark as finished
                                finished = True

                    # Add tool response to message thread
                    msg_thread.add_tool(
                        observation,
                        name=function_name,
                        tool_call_id=tool_call_id,
                    )
            else:
                msg_thread.add_user(
                    f"Please use the provided tools to achieve the goal. First use `{ReportFunctionsTool['function']['name']}` to report function signatures, then use `{ReportFuncFinishTool['function']['name']}` when complete."
                )

        logger.debug(
            "Message thread for function detection:\n{}",
            msg_thread,
        )

        logger.info(
            'Found {} function signature lines in file "{}": {}',
            len(collected_signature_lines),
            source_code_file,
            collected_signature_lines,
        )

        # Sort the start lines
        collected_signature_lines = sorted(list(collected_signature_lines))

        # Adjust function start lines
        max_lookback = 7
        cutoff_lines = []
        for signature_line in collected_signature_lines:
            # Look up for the nearest empty line
            adjusted_start = signature_line
            for i in range(max_lookback):
                line_num = signature_line - i
                if line_num >= 0 and source_code_lines[line_num].strip() == "":
                    adjusted_start = line_num
                    break
            cutoff_lines.append(adjusted_start)

        final_cutoff_lines = sorted(list(set(cutoff_lines)))
        logger.info(
            'Found {} cutoff lines in file "{}": {}',
            len(final_cutoff_lines),
            source_code_file,
            final_cutoff_lines,
        )

        return final_cutoff_lines, need_instrument, usage

    def _instrument_code_snippet(
        self,
        chunk_code_lines: dict[int, str],
        source_code_file: str,
        source_language: str,
        chunk_idx: int,
        all_chunk_num: int,
        base_temperature: float,
    ) -> tuple[str, bool, Usage]:
        """
        Instrument the code in the given chunks.
        Args:
            - chunk_code_lines: line_no -> line_content
            - source_code_file: file name of the source code to be instrumented
            - source_language: language of the source code
            - chunk_idx: index of the chunk
            - all_chunk_num: total number of chunks
            - base_temperature: basetemperature for the model
        Returns:
            - chunk_instrumented_code: instrumented code
            - success: whether the instrumentation is successful
            - total_usage: usage information
        """
        chunk_instrumented_code = ""
        total_usage = Usage()

        formatted_code = format_code(
            chunk_code_lines, source_language, numbered=False, qouted=True
        )

        msg_thread = MessageThread()
        system_prompt = INSTR_SYSTEM_PROMPT.replace(
            "HEADER_REQUIREMENTS_PLACEHOLDER",
            HEADER_SUPPLEMENTAL_REQUIREMENTS if chunk_idx == 0 else "",
        )
        msg_thread.add_system(
            unescape(
                (
                    Instructions(instructions=system_prompt).to_xml()
                    + b"\n"
                    + ExampleUserInput(
                        example_user_input=(
                            wrap_between_tags(
                                FilePath.__xml_tag__,
                                f"{src_example_file} (Part 1/1)",
                            )
                            + "\n"
                            + wrap_between_tags(
                                SourceCode.__xml_tag__, SOURCE_CODE_EXAMPLE
                            )
                        )
                    ).to_xml()
                    + b"\n"
                    + ExampleAssistantOutput(
                        example_assistant_output=wrap_between_tags(
                            InstrumentedCode.__xml_tag__,
                            INSTRUMENTED_CODE_EXAMPLE,
                        )
                    ).to_xml()
                ).decode()
            )
        )

        user_prompt = unescape(
            (
                wrap_between_tags(
                    FilePath.__xml_tag__,
                    f"{source_code_file} (Part {chunk_idx + 1}/{all_chunk_num})",
                ).encode()
                + b"\n"
                + wrap_between_tags(SourceCode.__xml_tag__, formatted_code).encode()
            ).decode()
        )

        msg_thread.add_user(user_prompt)

        # print_ace(user_prompt, "Code Instrumentation")

        conversation_times = 0
        _success = False
        total_usage = Usage()

        while not _success:

            response, _, usage = self.model.call(
                msg_thread.to_msg(),
                temperature=base_temperature + conversation_times * 0.1,
            )
            total_usage += usage
            msg_thread.add_model(message=response)

            try:
                chunk_instrumented_code = extract_between_tags(
                    InstrumentedCode.__xml_tag__, response, use_unescape=False
                )[0]
            except ResponseParseException:
                msg_thread.add_user(
                    f"Output format error: Please output the INSTRUMENTED code IN <{InstrumentedCode.__xml_tag__}> tags.\n"
                )
                continue
            chunk_instrumented_code = strip_qoutes(
                chunk_instrumented_code, source_language
            )

            if chunk_instrumented_code.strip() == NO_INSTRUMENTATION_NEEDED:
                chunk_instrumented_code = "\n".join(chunk_code_lines.values())

            _success, chunk_instrumented_code = check_instrumentation(
                chunk_instrumented_code
            )

            if not _success:
                logger.info(
                    'Instrumentation format error for chunk {}/{} of file "{}": {}',
                    chunk_idx + 1,
                    all_chunk_num,
                    source_code_file,
                    chunk_instrumented_code,
                )
                msg_thread.add_user(
                    f"Instrumentation format error: {chunk_instrumented_code}\n"
                    f"First, please identify the error.\n"
                    f'Then, fix the error (usually this involves adding missing "enter"/"exit" statements or adjusting their positions to match the basic block boundaries) and output the fixed instrumented code in <{InstrumentedCode.__xml_tag__}> tags.\n'
                    f"Finally, review the output code THOROUGHLY to ensure it is correct and complete."
                )
            conversation_times += 1
            if conversation_times > 3:
                break

        # Restore the deleted blocks
        if _success:
            chunk_instrumented_code = restore_deleted_blocks(
                "\n".join(chunk_code_lines.values()), chunk_instrumented_code
            )

        logger.debug(
            "Message thread for instrumenting code: {}",
            msg_thread,
        )

        return chunk_instrumented_code, _success, total_usage

    def instrument(
        self,
        source_code_file: str,
        chunk_size: int,
        mark: str | None = None,
    ) -> tuple[str, bool]:
        """
        Args:
            - source_code_file: file name of the source code to be instrumented
            - mark: mark for the instrumented code (default is file path)
            - chunk_size: chunk size for splitting the code into smaller chunks
        Returns:
            - instrumented_code: instrumented code
            - success: whether the instrumentation is successful
        """

        source_code_lines = open(source_code_file).readlines()

        # Split the code into chunks
        split_usage = Usage()

        source_language = detect_language(source_code_file)

        need_instrument = True

        if len(source_code_lines) > chunk_size:
            cutoff_lines, need_instrument, split_usage = self.split_code(
                source_code_file, chunk_size
            )
            cutoff_lines.append(len(source_code_lines))
            cutoff_lines.append(0)
            cutoff_lines = sorted(list(set(cutoff_lines)))
            chunks = create_chunks(cutoff_lines, chunk_size)
        else:
            chunks = [(0, len(source_code_lines))]

        logger.info(
            "File {} is splited into {} chunks: {}",
            source_code_file,
            len(chunks),
            chunks,
        )

        instr_usage = Usage()

        if need_instrument:

            # Start instrumenting chunks

            instrumented_code = ""  # final instrumented code
            for chunk_idx, chunk in enumerate(chunks):

                logger.info(
                    'Processing chunk #{}/{} of file "{}"{}',
                    (chunk_idx + 1),
                    len(chunks),
                    source_code_file,
                    (
                        f" (exceeded given chunk size: {chunks[chunk_idx][1] - chunks[chunk_idx][0]})"
                        if chunks[chunk_idx][1] - chunks[chunk_idx][0] > chunk_size
                        else ""
                    ),
                )

                current_chunk_lines = {
                    i: line.rstrip("\n")
                    for i, line in enumerate(source_code_lines[chunk[0] : chunk[1]])
                }

                for try_times in range(self.INSTRUMENTATION_RETRY_TIMES):
                    chunk_instrumented_code, _success, usage = (
                        self._instrument_code_snippet(
                            current_chunk_lines,
                            source_code_file,
                            source_language,
                            chunk_idx,
                            len(chunks),
                            INSTRUMENTATION_TEMPERATURE + try_times * 0.3,
                        )
                    )
                    instr_usage += usage
                    if _success:
                        break
                    else:
                        logger.info(
                            f"Instrumentation failed for {source_code_file} chunk {chunk_idx + 1}/{len(chunks)} ({chunk_instrumented_code}), retrying {try_times + 1}/{self.INSTRUMENTATION_RETRY_TIMES}...",
                        )

                if not _success:
                    logger.error(
                        f"Instrumentation failed for {source_code_file} chunk {chunk_idx + 1}, reason: {chunk_instrumented_code}"
                    )
                    return instrumented_code, False

                instrumented_code += chunk_instrumented_code + "\n"

        else:  # No instrumentation needed
            instrumented_code = "\n".join(source_code_lines)

        _success, instrumented_code = check_instrumentation(instrumented_code)
        assert _success
        comment_token = get_comment_token(source_language)
        instrumented_code += (
            f"{comment_token} {TOTAL_COST_FORMAT.format((instr_usage.cost+split_usage.cost))}\n"
            f"{comment_token} {SPLIT_COST_FORMAT_WITH_CHUNKS.format(split_usage.cost, split_usage.input_tokens, split_usage.output_tokens, split_usage.cache_read_tokens, split_usage.cache_write_tokens, chunks)}\n"
            f"{comment_token} {INSTRUMENTED_COST_FORMAT.format(instr_usage.cost, instr_usage.input_tokens, instr_usage.output_tokens, instr_usage.cache_read_tokens, instr_usage.cache_write_tokens)}\n"
        )

        instrumented_code = instr_postprocess(
            instrumented_code, mark if mark else source_code_file
        )

        # print_instrument(instrumented_code, "Instrumentated Code")
        return instrumented_code, True
