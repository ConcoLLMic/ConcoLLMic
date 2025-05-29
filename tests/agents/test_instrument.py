from app.agents.agent_instrumentation import (
    check_instrumentation,
    create_chunks,
    instr_postprocess,
)

instrumentation_with_duplicate_block_ids = """#include <stdio.h>
#include <stdlib.h>

int validate_brackets(const char *filename) {
    fprintf(stderr, "enter validate_brackets 1\\n");
    FILE *file = fopen(filename, "r");
    if (!file) {
        fprintf(stderr, "enter validate_brackets 2\\n");
        perror("Failed to open file");
        exit(1);
        fprintf(stderr, "exit validate_brackets 2\\n");
    }

    char buffer[256];
    if (!fgets(buffer, 256, file)) {
        fprintf(stderr, "enter validate_brackets 3\\n");
        fclose(file);
        exit(1);
        fprintf(stderr, "exit validate_brackets 3\\n");
    }
    fclose(file);

    int balance = 0;
    for (int i = 0; buffer[i] != '\\0'; i++) {
        fprintf(stderr, "enter validate_brackets 4\\n");
        if (buffer[i] == '{') {
            fprintf(stderr, "enter validate_brackets 5\\n");
            balance++;
            fprintf(stderr, "exit validate_brackets 5\\n");
        } else if (buffer[i] == '}') {
            fprintf(stderr, "enter validate_brackets 5\\n");  // Duplicate block ID
            balance--;
            fprintf(stderr, "exit validate_brackets 5\\n");   // Duplicate block ID
        }
        
        if (balance < 0) {
            fprintf(stderr, "enter validate_brackets 7\\n");
            return -1;
            fprintf(stderr, "exit validate_brackets 7\\n");
        }
        fprintf(stderr, "exit validate_brackets 4\\n");
    }

    fprintf(stderr, "enter validate_brackets 8\\n");    # test consecutive instrumention pairs
    fprintf(stderr, "exit validate_brackets 8\\n");

    if (balance != 0) {
        fprintf(stderr, "enter validate_brackets 9\\n");
        return -1;
        fprintf(stderr, "exit validate_brackets 9\\n");
    } else {
        fprintf(stderr, "enter validate_brackets 10\\n");
        return 0;
        fprintf(stderr, "exit validate_brackets 10\\n");
    }
    fprintf(stderr, "exit validate_brackets 1\\n");
}

int main(int argc, char *argv[]) {
    fprintf(stderr, "enter main 1\\n");
    if (argc != 2) {
        fprintf(stderr, "enter main 2\\n");
        fprintf(stderr, "Usage: %s <filename>\\n", argv[0]);
        return 1;
        fprintf(stderr, "exit main 2\\n");
    }
    int result = validate_brackets(argv[1]);
    return 0;
    fprintf(stderr, "exit main 1\\n");
}
"""


def test_check_instrumentation_with_duplicate_block_ids():
    """
    Test that check_instrumentation correctly identifies and fixes duplicate block IDs.

    This test creates a sample instrumented code with duplicate block IDs and verifies
    that check_instrumentation correctly identifies and fixes them.
    """
    # Create a sample instrumented code with duplicate block IDs
    # In this example, we have two blocks with the same ID (validate_brackets, 5)
    instrumented_code = instrumentation_with_duplicate_block_ids

    # Call check_instrumentation
    is_correct, result = check_instrumentation(instrumented_code)

    # Verify that check_instrumentation identified the need for an update
    assert is_correct, "The instrumented code can be adjusted to be correct"

    # Verify that the result is a string (updated code)
    assert isinstance(result, str), "Result should be the updated instrumented code"

    assert (
        result != instrumented_code
    ), "Result should be different from the original instrumented code"

    print(result)

    # check again
    is_correct, new_result = check_instrumentation(result)
    assert is_correct, "The refined code should be correct"
    assert new_result == result, "The refined code should not change"

    # postprocess
    postprocessed_result = instr_postprocess(result, "postprocess_mark")

    # count marks' number
    marks_number = postprocessed_result.count("[postprocess_mark]")
    # count enter and exit
    enter_number = (
        instrumentation_with_duplicate_block_ids.count("enter") - 1
    )  # delete consecutive enter/exit pairs
    assert (
        marks_number == enter_number * 2
    ), "Not all instrumention statements are postprocessed"

    assert (
        'fprintf(stderr, "enter validate_brackets 8\\n");' not in result
    ), "The postprocessed code should not contain the consecutive instrumention pairs"

    assert (
        'fprintf(stderr, "\\n");' in result
    ), "The deleted instrumention statements should be replaced with a blank content"


def test_check_instrumentation_with_mismatched_blocks():
    """
    Test that check_instrumentation correctly identifies mismatched blocks.

    This test creates a sample instrumented code with mismatched enter/exit blocks
    and verifies that check_instrumentation correctly identifies the error.
    """
    # Create a sample instrumented code with mismatched blocks
    # In this example, we have an exit for block 6 without a corresponding enter
    instrumented_code = """#include <stdio.h>
#include <stdlib.h>

int validate_brackets(const char *filename) {
    fprintf(stderr, "enter validate_brackets 1\\n");
    FILE *file = fopen(filename, "r");
    if (!file) {
        fprintf(stderr, "enter validate_brackets 2\\n");
        perror("Failed to open file");
        exit(1);
        fprintf(stderr, "exit validate_brackets 2\\n");
    }

    char buffer[256];
    if (!fgets(buffer, 256, file)) {
        fprintf(stderr, "enter validate_brackets 3\\n");
        fclose(file);
        exit(1);
        fprintf(stderr, "exit validate_brackets 3\\n");
    }
    fclose(file);

    int balance = 0;
    for (int i = 0; buffer[i] != '\\0'; i++) {
        fprintf(stderr, "enter validate_brackets 4\\n");
        if (buffer[i] == '{') {
            fprintf(stderr, "enter validate_brackets 5\\n");
            balance++;
            fprintf(stderr, "exit validate_brackets 5\\n");
        } else if (buffer[i] == '}') {
            // Missing enter for block 6
            balance--;
            fprintf(stderr, "exit validate_brackets 6\\n");   // Mismatched block
        }
        
        if (balance < 0) {
            fprintf(stderr, "enter validate_brackets 7\\n");
            return -1;
            fprintf(stderr, "exit validate_brackets 7\\n");
        }
        fprintf(stderr, "exit validate_brackets 4\\n");
    }

    fprintf(stderr, "exit validate_brackets 1\\n");
}
"""

    # Call check_instrumentation
    needs_update, result = check_instrumentation(instrumented_code)

    # Verify that check_instrumentation identified an error
    assert not needs_update, "check_instrumentation should identify mismatched blocks"

    # Verify that the result is an error message
    assert isinstance(result, str), "Result should be an error message"
    assert (
        "Block ID mismatch" in result
    ), "Error message should indicate a block ID mismatch"


instrumentation_with_multiple_exit_statements = """static int
_bc_do_compare ( bc_num n1, bc_num n2, int use_sign, int ignore_last )
{
  fprintf(stderr, "enter _bc_do_compare 1\n");
  char *n1ptr, *n2ptr;
  int  count;

  /* First, compare signs. */
  if (use_sign && n1->n_sign != n2->n_sign)
    {
      fprintf(stderr, "enter _bc_do_compare 2\n");
      if (n1->n_sign == PLUS) {
        fprintf(stderr, "exit _bc_do_compare 2\n");
        fprintf(stderr, "exit _bc_do_compare 1\n");
	return (1);	/* Positive N1 > Negative N2 */
      } else {
        fprintf(stderr, "exit _bc_do_compare 2\n");
        fprintf(stderr, "exit _bc_do_compare 1\n");
	return (-1);	/* Negative N1 < Positive N1 */
      }
    }
}
"""


def test_check_instrumentation_with_multiple_exit_statements():
    """
    Test that check_instrumentation correctly identifies multiple exit statements.
    """
    instrumented_code = instrumentation_with_multiple_exit_statements

    # Call check_instrumentation
    is_correct, _ = check_instrumentation(instrumented_code)

    assert not is_correct, "The instrumented code should be incorrect"


def test_create_chunks_with_consecutive_ranges_greater_than_chunk_size():
    """
    Test that create_chunks correctly creates chunks of code.
    """
    func_starts = [0, 508, 661, 673, 916, 1916, 2067]
    chunk_size = 500
    assert create_chunks(func_starts, chunk_size) == [
        (0, 508),
        (508, 916),
        (916, 1916),
        (1916, 2067),
    ]

    func_starts = [0, 508, 661, 673, 916, 1916]
    chunk_size = 500
    assert create_chunks(func_starts, chunk_size) == [(0, 508), (508, 916), (916, 1916)]

    func_starts = [0, 508, 661, 673, 1200, 1473, 2300]
    chunk_size = 800
    assert create_chunks(func_starts, chunk_size) == [
        (0, 673),
        (673, 1473),
        (1473, 2300),
    ]

    func_starts = [0, 2067]
    chunk_size = 500
    assert create_chunks(func_starts, chunk_size) == [(0, 2067)]
