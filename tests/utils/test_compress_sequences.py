from app.utils.utils import compress_repeating_sequences


def test_compress_array():
    array1 = ["a", "b", "c", "b", "c", "b", "c", "d"]
    assert compress_repeating_sequences(array1) == [("a", 1), (["b", "c"], 3), ("d", 1)]

    array2 = ["x", "x", "y", "z", "y", "z", "w", "w", "w", "w"]
    assert compress_repeating_sequences(array2) == [("x", 2), (["y", "z"], 2), ("w", 4)]

    array3 = ["a", "b", "a", "b", "a", "b"]
    assert compress_repeating_sequences(array3) == [(["a", "b"], 3)]

    array4 = ["a", "a", "a", "a"]
    assert compress_repeating_sequences(array4) == [("a", 4)]

    array5 = ["a", "b", "c", "d"]
    assert compress_repeating_sequences(array5) == [
        ("a", 1),
        ("b", 1),
        ("c", 1),
        ("d", 1),
    ]

    array6 = []
    assert compress_repeating_sequences(array6) == []

    long_arr = ["a"] * 100 + ["b", "c"] * 200 + ["d"] * 5 + ["e"] * 100 + ["d"] * 50
    assert compress_repeating_sequences(long_arr) == [
        ("a", 100),
        (["b", "c"], 200),
        ("d", 5),
        ("e", 100),
        ("d", 50),
    ]

    func_arr = [
        ("file1", "func1"),
        ("file1", "func2"),
        ("file1", "func3"),
        ("file2", "func3"),
        ("file1", "func2"),
        ("file1", "func3"),
        ("file2", "func3"),
        ("file2", "func1"),
        ("file2", "func2"),
        ("file2", "func3"),
    ]

    func_arr_compressed = compress_repeating_sequences(func_arr)
    assert len(func_arr_compressed) == 5
    assert func_arr_compressed[0] == (("file1", "func1"), 1)
    assert func_arr_compressed[1] == (
        [("file1", "func2"), ("file1", "func3"), ("file2", "func3")],
        2,
    )
    assert func_arr_compressed[2] == (("file2", "func1"), 1)
    assert func_arr_compressed[3] == (("file2", "func2"), 1)
    assert func_arr_compressed[4] == (("file2", "func3"), 1)
