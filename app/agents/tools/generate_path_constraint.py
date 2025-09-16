"""
Tool for generating path constraints in concolic execution.
"""

from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
from loguru import logger

_GENERATE_PATH_CONSTRAINT_DESCRIPTION = """Use this tool to generate the symbolic constraints required to reach the CURRENTLY selected target branch.

Your constraints should:
1. Focus on program inputs and environment conditions 
    - Specify what values or conditions must be true for inputs
    - Avoid intermediate program states or internal variables
2. Be expressed clearly - Use natural language, code snippets, SMT formulas, or a combination as appropriate
3. Follow chronological execution order - Present constraints in the sequence they would be encountered during execution
4. Be complete - Cover all conditions that must be satisfied to reach the target branch
5. Be CONCISE - AVOID unnecessary complexity and AVOID providing concrete examples or test cases
6. Be SELF-CONTAINED - The constraints will be read by someone who has NEVER SEEN THE SOURCE CODE
    - DO NOT reference internal functions or variables without explanation
    - EXPLICITLY describe file format requirements (exact byte positions, values, meanings), especially for uncommonly used formats
    - Avoid jargon or function names without providing context about what they validate

Some common constraints:
- Input file format requirements (structure, headers, fields)
- Specific values or ranges for command-line arguments
- Environmental conditions (file existence, permissions, environment variables)
- Mathematical relationships between input values
- String properties (length, content, encoding)
- Relationships between multiple inputs

IMPORTANT:
- Focus on symbolic analysis rather than concrete execution. Hence, DO NOT provide concrete examples or test cases.
- DO NOT attempt to solve the constraints or suggest inputs that would satisfy them
- Your role is ONLY to identify and state the constraints clearly enough that someone without code access can understand them
- Constraint solving will be handled by a separate tool in a later step

The constraints you generate will be used by other tools to create test cases that explore the target branch.
"""

# Define the path constraint generation tool
GeneratePathConstraintTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="generate_path_constraint",
        description=_GENERATE_PATH_CONSTRAINT_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "path_constraint": {
                    "type": "string",
                    "description": "The symbolic constraints required to reach the target branch",
                }
            },
            "required": ["path_constraint"],
        },
    ),
)


def process_path_constraint_generation(
    path_constraint: str | None, selected_branch: str | None
) -> tuple[str, bool]:
    """
    Process path constraint generation.

    Args:
        path_constraint: The generated path constraint
        branch_already_selected: Whether a branch has been selected
    Returns:
        Tuple of (observation message, is_valid)
    """
    if selected_branch is None:
        return (
            "Please select an new target branch first before generating path constraints.",
            False,
        )

    if path_constraint is None or not path_constraint.strip():
        logger.warning("`path_constraint` is not provided or it is empty.")
        return (
            "Error: `path_constraint` is not provided or it is empty. Please provide a valid `path_constraint`.",
            False,
        )

    else:
        logger.info(f"Path constraint generated: {path_constraint}")

        return (
            f'Path constraint for "{selected_branch}" successfully generated and recorded.',
            True,
        )
