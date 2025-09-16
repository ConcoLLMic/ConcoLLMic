import re

from app.agents.common import FILE_TRACE_PATTERN, filter_instr_print
from app.agents.trace import trace_compress
from app.commands.run import split_trace_by_file


def test_filter_instr_print():

    stderr = """
    [oggenc/encode.c] enter update_statistics_notime 1
    [oggenc/encode.c] exit update_statistics_notime 1
    """
    assert filter_instr_print(stderr) == ""

    stderr = """
    [][oggenc/encode.c] enter update_statistics_notime 1
    [oggenc/encode.c] exit update_statistics_notime 1
    """
    assert filter_instr_print(stderr) == "[]\n"

    stderr = """
    [aaa][oggenc/encode.c] enter update_statistics_notime 1[bbb]
    [ccc] enter update_statistics_notime
    [ddd] exit update_statistics_notime 1
    """
    assert (
        filter_instr_print(stderr)
        == "[aaa][bbb]\n[ccc] enter update_statistics_notime\n"
    )

    stderr = """
    [aaa][oggenc/encode.c] enter update_statistics_notime_1 [bbb]
    [ccc] enter update_statistics_notime
    [ddd] exit update_statistics_notime 1
    """
    assert (
        filter_instr_print(stderr)
        == "[aaa][oggenc/encode.c] enter update_statistics_notime_1 [bbb]\n[ccc] enter update_statistics_notime\n"
    )


def test_trace_matching():
    trace_str = "xxx[oggenc/encode.c] exit update_statistics_notime 1[oggenc/encode.c] exit update_statistics_notime 1"

    matches = re.findall(FILE_TRACE_PATTERN, trace_str)
    assert len(matches) == 2
    assert matches[0] == ("oggenc/encode.c", "exit", "update_statistics_notime", "1")
    assert matches[1] == ("oggenc/encode.c", "exit", "update_statistics_notime", "1")

    trace_str = "[xxx][oggenc/encode.c] exit update_statistics_notime 1"
    matches = re.findall(FILE_TRACE_PATTERN, trace_str)
    assert len(matches) == 1
    assert matches[0] == ("oggenc/encode.c", "exit", "update_statistics_notime", "1")

    trace_str = (
        "Encoding [ 0m00s so far] | [oggenc/encode.c] exit update_statistics_notime 1"
    )
    matches = re.findall(FILE_TRACE_PATTERN, trace_str)
    assert len(matches) == 1
    assert matches[0] == ("oggenc/encode.c", "exit", "update_statistics_notime", "1")

    trace_str = "Encoding [ 0m00s so far] | [oggenc/encode.c] exit update_statistics_notime 1[aaa] enter update_statistics_notime 1"
    matches = re.findall(FILE_TRACE_PATTERN, trace_str)
    assert len(matches) == 2
    assert matches[0] == ("oggenc/encode.c", "exit", "update_statistics_notime", "1")
    assert matches[1] == ("aaa", "enter", "update_statistics_notime", "1")

    trace_str = "Encoding [ 0m00s so far] | [oggenc/encode.c] exit update_statistics_notime 1[aaa][] enter update_statistics_notime 1"
    matches = re.findall(FILE_TRACE_PATTERN, trace_str)
    assert len(matches) == 1
    assert matches[0] == ("oggenc/encode.c", "exit", "update_statistics_notime", "1")

    trace_str = "Encoding [ 0m00s so far] | [oggenc/encode.c] exit update_statistics_notime 1[aaa][bbb] enter update_statistics_notime 1"
    matches = re.findall(FILE_TRACE_PATTERN, trace_str)
    assert len(matches) == 2
    assert matches[0] == ("oggenc/encode.c", "exit", "update_statistics_notime", "1")
    assert matches[1] == ("bbb", "enter", "update_statistics_notime", "1")


def test_trace_compress():
    trace_str = """
    Encoding [ 0m00s so far] | [oggenc/encode.c] enter update_statistics_notime 2[oggenc/encode.c] enter update_statistics_notime 1
    [oggenc/encode.c] exit update_statistics_notime 3
    [oggenc/encode.c] enter update 1
    [aaa][bbb] enter update_statistics_notime 2
    """
    compressed_trace = trace_compress(trace_str)
    assert compressed_trace == [
        ("oggenc/encode.c", "update_statistics_notime", [1, 2]),
        ("oggenc/encode.c", "update", [1]),
        ("bbb", "update_statistics_notime", [2]),
    ]


def test_split_trace_by_file():
    trace_str = """
Encoding [ 0m00s so far] | [oggenc/encode.c] enter update_statistics_notime 2[oggenc/encode.c] enter update_statistics_notime 1
[oggenc/encode.c] exit update_statistics_notime 3
[oggenc/encode.c] enter update 1
"""
    result = split_trace_by_file(trace_str)
    print(result)
    assert result == {
        "oggenc/encode.c": "[oggenc/encode.c] enter update_statistics_notime 2\n[oggenc/encode.c] enter update_statistics_notime 1\n[oggenc/encode.c] exit update_statistics_notime 3\n[oggenc/encode.c] enter update 1"
    }
