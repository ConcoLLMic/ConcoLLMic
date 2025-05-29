"""
Tool for solving SMT constraints in concolic execution.
"""

import z3
from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
from loguru import logger

_SMT_SOLVER_DESCRIPTION = """Use this tool to solve SMT (Satisfiability Modulo Theories) constraints using Z3 solver.

This tool supports two input formats:

FORMAT 1: DIRECT Z3 Python API expression (RECOMMENDED)
- DIRECTLY provide the Z3 expression without any code block markers (no triple backticks)
- All Z3 functions must be prefixed with 'z3.' (e.g., z3.Int, z3.And, z3.Or)
- Can be single-line or multi-line expression
- Must be a direct Z3 expression that can be evaluated directly, not a sequence of assignments
- Examples:
  - Simple constraint: z3.Int('x') > 0
  - Multi-line constraints: 
    z3.And(
        z3.Int('x') > 0, 
        z3.Int('y') < 10,
        z3.Int('x') + z3.Int('y') == 7
    )
    ```
  - Complex constraints: 
    z3.And(
        z3.Or(z3.Int('x') == 1, z3.Int('x') == -1),
        z3.Int('x') >= 0
    )

FORMAT 2: Code Block with Final Constraint (FOR COMPLEX CONSTRAINT BUILDING)
- MUST be wrapped in triple backticks (``` ```) as code block markers. Ensure proper indentation within the code block
- DO NOT include any import statements - the z3 module is already available
- You MUST assign your final constraint to a variable named 'final_constraint', which must be a Z3 boolean expression
- Example:
  ```
  # Define variables using z3 module (already imported)
  x = z3.Int('x')
  y = z3.Int('y')
  
  # Build constraints
  constraints = []
  constraints.append(x > 0)
  constraints.append(y < 10)
  constraints.append(x + y == 7)
  
  # REQUIRED: assign final constraint to the variable named 'final_constraint'
  final_constraint = z3.And(*constraints)
  ```

The solver will return:
- If satisfiable: variable assignments that satisfy the constraints (one valid solution)
- If unsatisfiable: an error message indicating the constraints cannot be satisfied
- If timeout/unknown: an error message with the reason

The solver has a 10-second timeout. For complex constraints, consider simplifying or decomposing them.
"""

# Define the SMT solver tool
SMTSolverTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="solve_with_smt",
        description=_SMT_SOLVER_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "smt_constraints": {
                    "type": "string",
                    "description": "The SMT constraints in Z3 Python API format",
                }
            },
            "required": ["smt_constraints"],
        },
    ),
)


def process_smt_solver(smt_constraints: str | None) -> tuple[str, bool]:
    """
    Process SMT solver tool by calling Z3 to solve constraints.

    Args:
        smt_constraints: The constraints in Z3 Python API format or a structured code block

    Returns:
        Tuple of (result message, satisfiable && execution_succeeded)
    """
    logger.info(f"Solving SMT constraints:\n{smt_constraints}")
    if not smt_constraints or not smt_constraints.strip():
        logger.warning("`smt_constraints` is not provided or it is empty.")
        return (
            "Error: `smt_constraints` is not provided or it is empty. Please provide a valid `smt_constraints`.",
            False,
        )

    result_str = ""
    err_msg = ""
    try:
        # Create Z3 solver and set timeout
        solver = z3.Solver()
        solver.set("timeout", 10000)  # Set 10 second timeout (in milliseconds)

        # Clean up the constraints - strip any code block markers
        smt_constraints = smt_constraints.strip()

        # Remove possible markdown code block markers
        if smt_constraints.startswith("```"):
            # Find the end of the first line to remove language hint if present
            first_line_end = smt_constraints.find("\n")
            if first_line_end > 0:
                smt_constraints = smt_constraints[first_line_end + 1 :]

            # Find and remove ending triple backticks
            end_marker = smt_constraints.rfind("```")
            if end_marker > 0:
                smt_constraints = smt_constraints[:end_marker]

        # Ensure the string is stripped again after removing markers
        smt_constraints = smt_constraints.strip()

        # Determine which format is being used
        # FORMAT 1: Any expression that doesn't contain variable assignments and starts with z3.
        # FORMAT 2: Code block with assignments ending with final_constraint assignment

        # Check if it's likely to be FORMAT 1 (direct Z3 expression)
        is_format1 = False
        lines = smt_constraints.split("\n")
        non_empty_lines = [
            line.strip()
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        ]

        # If every non-empty line either starts with z3. or is continuation of expression (starts with operators/brackets)
        if non_empty_lines and (
            all(
                line.strip().startswith("z3.")
                or line.strip().startswith("(")
                or line.strip().startswith(")")
                or line.strip().startswith(",")
                or line.strip().startswith("&&")
                or line.strip().startswith("||")
                or line.strip().startswith("and ")
                or line.strip().startswith("or ")
                or line.strip().startswith("+")
                or line.strip().startswith("-")
                or line.strip().startswith("*")
                or line.strip().startswith("/")
                or line.strip().startswith("==")
                or line.strip().startswith("!=")
                or line.strip().startswith("<")
                or line.strip().startswith(">")
                for line in non_empty_lines
            )
        ):
            is_format1 = True

        if is_format1:
            # Direct Z3 expression (FORMAT 1) - use standard eval
            # Join all lines to handle multi-line expressions
            constraint = eval(smt_constraints, {"z3": z3})
        else:
            # Multi-line code block (FORMAT 2) - execute it in a controlled environment
            # Remove any import statements for security and fix indentation
            code_lines = []
            for line in lines:
                if line.strip().startswith("import") or line.strip().startswith("from"):
                    # Skip all import statements
                    continue
                code_lines.append(line)

            # Fix indentation using a more robust approach
            if code_lines:
                # Only consider lines that have content and aren't just comments
                non_empty_lines = []
                for line in code_lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        non_empty_lines.append(line)

                if non_empty_lines:
                    # Calculate leading spaces for each non-empty line
                    leading_spaces = []
                    for line in non_empty_lines:
                        spaces = len(line) - len(line.lstrip())
                        leading_spaces.append(spaces)

                    # Get the minimum non-zero indent level
                    min_indent = (
                        min(spaces for spaces in leading_spaces if spaces > 0)
                        if any(spaces > 0 for spaces in leading_spaces)
                        else 0
                    )

                    # If we found a minimum indent, remove it from all lines
                    if min_indent > 0:
                        fixed_lines = []
                        for line in code_lines:
                            if line.strip():  # only process non-empty lines
                                current_indent = len(line) - len(line.lstrip())
                                if current_indent >= min_indent:
                                    fixed_lines.append(line[min_indent:])
                                else:
                                    fixed_lines.append(
                                        line
                                    )  # keep original if indentation is less
                            else:
                                fixed_lines.append(line)  # keep empty lines as is
                        code_lines = fixed_lines

            # Join lines and execute
            code = "\n".join(code_lines)

            # Execute the code with limited global namespace
            global_vars = {"z3": z3}
            local_vars = {}

            try:
                exec(code, global_vars, local_vars)

                # Get the constraint from the required variable name
                if "final_constraint" not in local_vars:
                    err_msg = "Missing required 'final_constraint' variable in code block. You must assign your final constraint to 'final_constraint'."

                else:
                    constraint = local_vars["final_constraint"]
                    if not isinstance(constraint, z3.BoolRef):
                        err_msg = "The 'final_constraint' variable must be a Z3 boolean expression."

            except Exception as e:
                err_msg = f"Error executing provided code block: {str(e)}"

        if err_msg:
            logger.info(f"SMT solver error:\n{err_msg}")
            return err_msg, False

        # Add constraints
        solver.add(constraint)

        # Check satisfiability
        result = solver.check()

        if result == z3.sat:
            model = solver.model()
            solution = []
            # Collect all variables
            variables = {}
            for decl in model:
                var_name = decl.name()
                var_value = model[decl]
                # Handle different value types
                if z3.is_int_value(var_value):
                    variables[var_name] = var_value.as_long()
                elif z3.is_algebraic_value(var_value):
                    variables[var_name] = float(
                        var_value.approx(10)
                    )  # Get real number approximation
                elif z3.is_true(var_value):
                    variables[var_name] = True
                elif z3.is_false(var_value):
                    variables[var_name] = False
                else:
                    variables[var_name] = var_value

            # Sort output by variable name
            for var in sorted(variables.keys()):
                solution.append(f"{var} = {variables[var]}")

            result_str = "\n".join(solution)
            logger.info(f"SMT solver found solution:\n{result_str}")

        elif result == z3.unsat:
            err_msg = "Constraints unsatisfiable."
            logger.info("SMT solver result: unsatisfiable")
        else:  # unknown
            reason = solver.reason_unknown()
            # Enhanced timeout detection logic
            if "timeout" in reason.lower() or "canceled" in reason.lower():
                err_msg = "Solver timeout (10 seconds)."
            else:
                err_msg = f"Solver could not determine result. Reason: {reason}"
            logger.info(f"SMT solver result: unknown - {reason}")

    except Exception as e:
        err_msg = f"Z3 solving error:\n {str(e)}"
        logger.warning(f"Exception in SMT solver: {e}")

    if result_str:
        assert err_msg == ""
        return result_str, True
    else:
        assert result_str == ""
        return err_msg, False
