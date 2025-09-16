"""
Tool for providing function signatures for code instrumentation.
"""

import re

from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
from loguru import logger

_FUNCTION_SIGNATURES_DESCRIPTION = """Use this tool to report function signatures that you have identified in the code file.

You must:
1. Scan the ENTIRE file line by line to ensure no function implementations are missed
2. INCLUDE all types of function IMPLEMENTATIONS while DISCARDING function declarations
3. For each function, identify the most distinctive LINE of the function signature (ONLY one line, typically the function name and the beginning of its parameter list). You should output the identified line EXACTLY as it appears in the original code.
4. Do NOT modify or reformat the signatures - they must be EXACTLY as they appear in the original code

## Examples
### Code snippet 1
```
static void print_packets_captured (void) {
    ...
}
```

Correct output: 
    - "static void print_packets_captured (void) {"
    - "static void print_packets_captured (void)"

Wrong output:
    - "static void" # This is not distinctive. It's hard to use this line to precisely identify this function signature using exact string matching.

### Code snippet 2
```
static void CALLBACK verbose_stats_dump(PVOID param _U_,
                                       BOOLEAN timer_fired _U_)
{
    ...
}
```
Correct output: 
    - "static void CALLBACK verbose_stats_dump(PVOID param _U_, BOOLEAN timer_fired _U_)"
    - "static void CALLBACK verbose_stats_dump(PVOID param _U_,"    # one line with incomplete signature is also acceptable

Wrong output:
    - "static void CALLBACK verbose_stats_dump(PVOID param _U_,\nBOOLEAN timer_fired _U_)"   # DONOT add "\n" to include multiple lines, just concatenate the lines

### Code snippet 3
```
DIAG_OFF_DEPRECATION
static void
print_version(FILE *f)
{
    ...
}
```
Correct output: 
    - "print_version(FILE *f)"
    - "static void print_version(FILE *f)"
    - "DIAG_OFF_DEPRECATION static void print_version(FILE *f)"

Wrong output:
    - "static void" # This is also not distinctive

### Code snippet 4
```
def load_input(file_path):
    ...
```
Correct output:
    - "def load_input(file_path)"

Wrong output:
    - "load_input(file_path)" # `def` SHOULD ALSO BE INCLUDED



IMPORTANT: Your output will be used for exact string matching in the original file, so accuracy is EXTREMELY important."""

# Define the function signatures tool
ReportFunctionsTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="report_functions",
        description=_FUNCTION_SIGNATURES_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "signatures": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of exact function signature strings found in the file",
                },
            },
            "required": ["signatures"],
        },
    ),
)


def normalize_spaces(text):
    return re.sub(r"\s+", " ", text)


def process_report_functions(signatures, source_code: str) -> tuple[str, list[int]]:
    """
    Process the function signatures provided by the model.

    Args:
        signatures: List of function signature strings
        source_code: source code to verify matches exist

    Returns:
        observation message
        found_funcs_signature_lines: List of function signature lines (0-indexed)
    """
    if signatures is None:
        return (
            "Error: No `signatures` provided. Please provide a list of function signatures if there are function implementations in the file.",
            [],
        )

    # Check if we have a valid list of signatures
    if not isinstance(signatures, list):
        return (
            "Error: `signatures` must be a list of strings.",
            [],
        )

    # Filter out any empty strings
    signature_list = [sig.strip() for sig in signatures if sig and sig.strip()]

    if not signature_list:
        return (
            "Error: No valid function signatures found. Please provide valid function signatures.",
            [],
        )

    # If source code is provided, verify each signature can be found
    not_found_signatures = []
    found_funcs_signature_lines = []  # 0-indexed line numbers
    source_code_lines = source_code.splitlines()
    for signature in signature_list:
        found = False
        _signature = normalize_spaces(signature.strip())
        for line_idx, line in enumerate(source_code_lines):
            if len(line.strip()) == 0:
                continue
            if _signature.startswith(line.strip()):
                _real_signature = line.strip()
                for i in range(1, 10):
                    if line_idx + i >= len(source_code_lines):
                        break
                    _real_signature += source_code_lines[line_idx + i].strip()

                if _signature.replace(" ", "") in _real_signature.replace(
                    " ", ""
                ):  # relax the matching condition
                    logger.debug(
                        'Found signature: "{}" at line: {}',
                        signature,
                        line_idx,
                    )
                    found_funcs_signature_lines.append(line_idx)
                    found = True

        if not found:
            logger.debug(
                'Signature not found: "{}"',
                signature,
            )
            not_found_signatures.append(signature)

    logger.info("Function signatures processed: {}", signature_list)

    if not_found_signatures:
        not_found_signatures_str = ""
        for cnt, signature in enumerate(not_found_signatures):
            not_found_signatures_str += f'{cnt+1}. "{signature}"\n'
        logger.info(
            "The following signatures could not be found in the source code:\n{}",
            not_found_signatures_str,
        )
        return (
            f"Error: The following signatures could not be found in the source code (ensure signatures match EXACTLY. To reduce the possibility of a mismatch, you can try to reduce the content by outputting only the return type and function name):\n{not_found_signatures_str}",
            found_funcs_signature_lines,
        )
    else:
        return (
            f"Successfully identified {len(signature_list)} function signatures. Continue reporting functions or finish if all functions have been reported.",
            found_funcs_signature_lines,
        )
