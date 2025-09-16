from app.agents.tools.smt_solver import process_smt_solver


def test_solve_simple_integer_constraint():
    """Test simple integer constraint"""
    constraint = "z3.Int('x') > 5"
    result, success = process_smt_solver(constraint)

    assert success
    assert "x =" in result
    # Solution should be greater than 5
    x_val = int(result.split("=")[1].strip())
    assert x_val > 5


def test_solve_multiple_constraints():
    """Test multiple variables and constraints"""
    constraint = (
        "z3.And(z3.Int('x') > 0, z3.Int('y') < 10, z3.Int('x') + z3.Int('y') == 7)"
    )
    result, success = process_smt_solver(constraint)

    assert success
    # Parse results
    values = {}
    for line in result.split("\n"):
        var, val = line.split("=")
        values[var.strip()] = int(val.strip())

    assert values["x"] > 0
    assert values["y"] < 10
    assert values["x"] + values["y"] == 7


def test_solve_boolean_constraint():
    """Test boolean constraints"""
    constraint = "z3.And(z3.Bool('a'), z3.Not(z3.Bool('b')))"
    result, success = process_smt_solver(constraint)

    assert success
    assert "a = True" in result
    assert "b = False" in result


def test_solve_unsatisfiable():
    """Test unsatisfiable constraints"""
    constraint = "z3.And(z3.Int('x') > 0, z3.Int('x') < 0)"
    result, success = process_smt_solver(constraint)

    print(result)

    assert not success
    assert "Constraints unsatisfiable" in result


def test_solve_real_numbers():
    """Test real number constraints"""
    constraint = (
        "z3.And(z3.Real('x') > z3.RealVal('1.5'), z3.Real('x') < z3.RealVal('2.5'))"
    )
    result, success = process_smt_solver(constraint)

    assert success
    x_val = float(result.split("=")[1].strip())
    assert 1.5 < x_val < 2.5


def test_invalid_syntax():
    """Test invalid syntax handling"""
    constraint = "z3.Int('x' >"  # Syntax error
    result, success = process_smt_solver(constraint)

    print(result)

    assert not success
    assert "error" in result.lower()


def test_complex_arithmetic():
    """Test complex arithmetic constraints"""
    constraint = "z3.And(z3.Int('x') * 2 + z3.Int('y') == 10, z3.Int('x') >= 0, z3.Int('y') >= 0)"
    result, success = process_smt_solver(constraint)

    assert success
    values = {}
    for line in result.split("\n"):
        var, val = line.split("=")
        values[var.strip()] = int(val.strip())

    assert values["x"] * 2 + values["y"] == 10
    assert values["x"] >= 0
    assert values["y"] >= 0


def test_string_variables():
    """Test variables with special characters"""
    constraint = "z3.Int('test_var_1') > 0"
    result, success = process_smt_solver(constraint)

    assert success
    assert "test_var_1 =" in result
    val = int(result.split("=")[1].strip())
    assert val > 0


def test_balanced_brackets():
    """Test balanced brackets problem with SMT solver"""
    constraint = """z3.And(
        z3.Or(z3.Int('pos0') == 1, z3.Int('pos0') == -1),
        z3.Or(z3.Int('pos1') == 1, z3.Int('pos1') == -1),
        z3.Or(z3.Int('pos2') == 1, z3.Int('pos2') == -1),
        z3.Or(z3.Int('pos3') == 1, z3.Int('pos3') == -1),
        z3.Int('pos0') >= 0,
        z3.Int('pos0') + z3.Int('pos1') >= 0,
        z3.Int('pos0') + z3.Int('pos1') + z3.Int('pos2') >= 0,
        z3.Int('pos0') + z3.Int('pos1') + z3.Int('pos2') + z3.Int('pos3') >= 0,
        z3.Int('pos0') + z3.Int('pos1') + z3.Int('pos2') + z3.Int('pos3') == 0
    )"""
    result, success = process_smt_solver(constraint)

    # print(result)
    assert success
    # Parse results
    values = {}
    for line in result.split("\n"):
        var, val = line.split("=")
        values[var.strip()] = int(val.strip())

    # Verify each position is either 1 or -1
    for i in range(4):
        assert values[f"pos{i}"] in [1, -1]

    # Verify running balance is never negative
    assert values["pos0"] >= 0
    assert values["pos0"] + values["pos1"] >= 0
    assert values["pos0"] + values["pos1"] + values["pos2"] >= 0
    assert values["pos0"] + values["pos1"] + values["pos2"] + values["pos3"] >= 0

    # Verify final balance is 0
    assert values["pos0"] + values["pos1"] + values["pos2"] + values["pos3"] == 0


# FORMAT 1: Multi-line expression tests
def test_multiline_format1_expression():
    """Test multi-line Format 1 expression with complex formatting"""
    constraint = """z3.And(
        z3.Int('x') > 5,
        z3.Int('y') < 10,
        z3.Int('x') + z3.Int('y') == 15
    )"""
    result, success = process_smt_solver(constraint)

    assert success
    values = {}
    for line in result.split("\n"):
        var, val = line.split("=")
        values[var.strip()] = int(val.strip())

    assert values["x"] > 5
    assert values["y"] < 10
    assert values["x"] + values["y"] == 15


def test_multiline_format1_with_operators():
    """Test multi-line Format 1 expression with operators at line starts"""
    constraint = """z3.And(
        z3.Int('a') > 0,
        z3.Int('b') > 0,
        z3.Int('a') * z3.Int('b') 
            == 24
    )"""
    result, success = process_smt_solver(constraint)

    assert success
    values = {}
    for line in result.split("\n"):
        var, val = line.split("=")
        values[var.strip()] = int(val.strip())

    assert values["a"] > 0
    assert values["b"] > 0
    assert values["a"] * values["b"] == 24


# FORMAT 2: Code block tests
def test_format2_with_final_constraint():
    """Test Format 2 with explicit final_constraint variable"""
    constraint = """
    ```
    # Define variables
    x = z3.Int('x')
    y = z3.Int('y')
    
    # Build constraints
    constraints = []
    constraints.append(x > 0)
    constraints.append(y < 10)
    constraints.append(x + y == 7)
    
    # Final constraint
    final_constraint = z3.And(*constraints)
    ```
    """
    result, success = process_smt_solver(constraint)

    assert success
    values = {}
    for line in result.split("\n"):
        var, val = line.split("=")
        values[var.strip()] = int(val.strip())

    assert values["x"] > 0
    assert values["y"] < 10
    assert values["x"] + values["y"] == 7


def test_format2_with_direct_constraint_building():
    """Test Format 2 with direct constraint building without a list"""
    constraint = """
```
# Define the problem directly
x = z3.Int('x')
y = z3.Int('y')
z = z3.Int('z')

# Build constraint directly
final_constraint = z3.And(
    x >= 1, 
    y >= 1,
    z >= 1,
    x + y + z == 10,
    x < y,
    y < z
)
```
    """
    result, success = process_smt_solver(constraint)

    assert success
    values = {}
    for line in result.split("\n"):
        var, val = line.split("=")
        values[var.strip()] = int(val.strip())

    assert values["x"] >= 1
    assert values["y"] >= 1
    assert values["z"] >= 1
    assert values["x"] + values["y"] + values["z"] == 10
    assert values["x"] < values["y"]
    assert values["y"] < values["z"]


def test_format2_complex_constraints():
    """Test Format 2 with more complex constraint building logic"""
    constraint = """```
    # Sudoku-like constraint for a 2x2 grid
    # We'll use variables: a b
    #                      c d
    a = z3.Int('a')
    b = z3.Int('b')
    c = z3.Int('c')
    d = z3.Int('d')
    
    # Each value must be between 1 and 2
    domain_constraints = []
    for var in [a, b, c, d]:
        domain_constraints.append(z3.And(var >= 1, var <= 2))
    
    # Each row must have different values
    row_constraints = []
    row_constraints.append(a != b)
    row_constraints.append(c != d)
    
    # Each column must have different values
    col_constraints = []
    col_constraints.append(a != c)
    col_constraints.append(b != d)
    
    # Combine all constraints
    final_constraint = z3.And(
        *domain_constraints,
        *row_constraints,
        *col_constraints
    )
    ```
    """
    result, success = process_smt_solver(constraint)

    assert success
    values = {}
    for line in result.split("\n"):
        var, val = line.split("=")
        values[var.strip()] = int(val.strip())

    # Check domain constraints
    for var in ["a", "b", "c", "d"]:
        assert 1 <= values[var] <= 2

    # Check row constraints
    assert values["a"] != values["b"]
    assert values["c"] != values["d"]

    # Check column constraints
    assert values["a"] != values["c"]
    assert values["b"] != values["d"]


# Edge cases and error handling tests
def test_format2_missing_final_constraint():
    """Test Format 2 with missing final_constraint variable"""
    constraint = """
    x = z3.Int('x')
    y = z3.Int('y')
    
    # No final_constraint defined
    result = z3.And(x > 0, y > 0)
    """
    result, success = process_smt_solver(constraint)

    assert not success
    assert "Missing required 'final_constraint'" in result


def test_format2_invalid_final_constraint():
    """Test Format 2 with invalid final_constraint (not a Z3 boolean expression)"""
    constraint = """
    x = z3.Int('x')
    
    # Final constraint is not a boolean expression
    final_constraint = x + 5
    """
    result, success = process_smt_solver(constraint)

    assert not success
    assert "must be a Z3 boolean expression" in result


def test_format2_with_empty_lines():
    """Test Format 2 with many empty lines"""
    constraint = """```python

# blank lines


x = z3.Int('x')


y = z3.Int('y')



# multiple blank lines
final_constraint = z3.And(x > 0, y > 0, x * y == 12)


```"""
    result, success = process_smt_solver(constraint)

    assert success
    values = {}
    for line in result.split("\n"):
        var, val = line.split("=")
        values[var.strip()] = int(val.strip())

    assert values["x"] > 0
    assert values["y"] > 0
    assert values["x"] * values["y"] == 12


# test variants of code block markers
def test_format2_without_python_hint():
    """Test Format 2 with code block markers but without 'python' hint"""
    constraint = """```
x = z3.Int('x')
y = z3.Int('y')

final_constraint = z3.And(x >= 1, y >= 1, x + y == 5)```"""
    result, success = process_smt_solver(constraint)

    assert success
    values = {}
    for line in result.split("\n"):
        var, val = line.split("=")
        values[var.strip()] = int(val.strip())

    assert values["x"] >= 1
    assert values["y"] >= 1
    assert values["x"] + values["y"] == 5


def test_format1_complex_nested_constraints():
    """Test Format 1 with complex nested constraints"""
    constraint = """z3.And(
        z3.ForAll([z3.Int('i')], 
            z3.Implies(
                z3.And(z3.Int('i') >= 0, z3.Int('i') < 5),
                z3.Int('x') > z3.Int('i')
            )
        ),
        z3.Int('x') < 10
    )"""
    result, success = process_smt_solver(constraint)

    # This should be satisfiable with x = 5 or higher (but less than 10)
    assert success
    x_val = int(result.split("=")[1].strip())
    assert 5 <= x_val < 10
