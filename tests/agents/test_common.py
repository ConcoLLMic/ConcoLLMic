from app.agents.trace import trace_compress


def test_trace_compress():
    """Test the trace_compress function"""
    # Test case 1: Basic functionality test
    trace_input = """[validate_brackets.cpp] enter main 1
[validate_brackets.cpp] exit main 1
[validate_brackets.cpp] enter main 3
[validate_brackets.cpp] enter validate_brackets 1
[validate_brackets.cpp] exit validate_brackets 1
[validate_brackets.cpp] enter validate_brackets 3
[validate_brackets.cpp] exit validate_brackets 3
[validate_brackets.cpp] enter validate_brackets 5
[validate_brackets.cpp] exit validate_brackets 5
[validate_brackets.cpp] enter validate_brackets 6
[validate_brackets.cpp] enter validate_brackets 8
[validate_brackets.cpp] exit validate_brackets 8
[validate_brackets.cpp] enter validate_brackets 9
"""

    # Note: In the original implementation, the statistics for the last function might be lost
    # and need to be manually added at the end
    expected_output = [
        ("validate_brackets.cpp", "main", [1, 3]),  # main entered 2 times
        (
            "validate_brackets.cpp",
            "validate_brackets",
            [1, 3, 5, 6, 8, 9],
        ),  # validate_brackets entered 6 times
    ]

    result = trace_compress(trace_input)
    assert result == expected_output

    # Test case 2: Empty input test
    empty_trace = ""
    empty_result = trace_compress(empty_trace)
    assert empty_result == []

    # Test case 3: No matching lines test
    no_match_trace = "This is a non-matching line\nThis is another non-matching line"
    no_match_result = trace_compress(no_match_trace)
    assert no_match_result == []

    # Test case 4: Incomplete format test
    incomplete_trace = "[file.cpp] something else\n[another_file.cpp] enter func"
    incomplete_result = trace_compress(incomplete_trace)
    assert incomplete_result == []

    # Test case 5: Multiple function call chain test
    multi_func_trace = """[file1.cpp] enter main 1
[file1.cpp] exit main 1
[file1.cpp] enter main 2
[file1.cpp] enter func1 1
[file1.cpp] exit func1 1
[file1.cpp] enter func2 1
[file1.cpp] exit func2 1
[file1.cpp] enter func3 1
[file1.cpp] exit func3 1
"""

    expected_multi_func = [
        ("file1.cpp", "main", [1, 2]),
        ("file1.cpp", "func1", [1]),
        ("file1.cpp", "func2", [1]),
        ("file1.cpp", "func3", [1]),
    ]

    multi_func_result = trace_compress(multi_func_trace)
    assert multi_func_result == expected_multi_func

    # Test case 6: Multiple files test
    multi_file_trace = """[file1.cpp] enter main 1
[file1.cpp] exit main 1
[file1.cpp] enter main 2
[file1.cpp] enter func1 1
[file1.cpp] exit func1 1
[file2.cpp] enter func2 1
[file2.cpp] exit func2 1
[file3.cpp] enter func3 1
[file3.cpp] exit func3 1
"""

    expected_multi_file = [
        ("file1.cpp", "main", [1, 2]),
        ("file1.cpp", "func1", [1]),
        ("file2.cpp", "func2", [1]),
        ("file3.cpp", "func3", [1]),
    ]

    multi_file_result = trace_compress(multi_file_trace)
    assert multi_file_result == expected_multi_file

    # Test case 7: Single function test to ensure the last function is processed correctly
    single_func_trace = """[file1.cpp] enter main 1
[file1.cpp] exit main 1
[file1.cpp] enter main 2
[file1.cpp] exit main 2
"""

    expected_single_func = [("file1.cpp", "main", [1, 2])]

    single_func_result = trace_compress(single_func_trace)
    assert single_func_result == expected_single_func

    # Test case 8: Call chain pattern file1=>file2=>file1 test
    cycle_trace = """[file1.cpp] enter main 1
[file1.cpp] exit main 1
[file1.cpp] enter main 2
[file1.cpp] enter function1 1
[file1.cpp] exit function1 1
[file2.cpp] enter function2 1
[file2.cpp] exit function2 1
[file2.cpp] enter function3 1
[file2.cpp] exit function3 1
[file1.cpp] enter main 1
[file1.cpp] exit main 1
[file1.cpp] enter function5 1
"""

    expected_cycle = [
        ("file1.cpp", "main", [1, 2]),
        ("file1.cpp", "function1", [1]),
        ("file2.cpp", "function2", [1]),
        ("file2.cpp", "function3", [1]),
        ("file1.cpp", "main", [1]),
        ("file1.cpp", "function5", [1]),
    ]

    cycle_result = trace_compress(cycle_trace)
    assert cycle_result == expected_cycle
