import os

from app.agents.trace import TraceCollector


def test_init():
    # get the absolute path of the project root
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    # build the path relative to the project root
    code_example_dir = os.path.join(project_root, "code_example/")

    # get all the files in the code_example_dir
    files = os.listdir(code_example_dir)
    for file in files:
        file_path = os.path.join(code_example_dir, file)
        if os.path.isfile(file_path):
            trace_collector = TraceCollector(file_path)
            assert trace_collector is not None
