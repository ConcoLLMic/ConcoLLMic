## Project Structure

* `agents/`: Core logic of ConcoLLMic agent
* `agents/tools/`: Tool use support for agents
* `commands/`: Entry points of different subcommands
* `model/`: Wrapper for LLM API invocation

## Commands and Options

For detailed documentation, please check out our [website](https://concollmic.github.io/docs.html).

```
python3 ACE.py [subcommand] [options]
```

1. `instrument`: instrument the source code
    * `src_dir`: Required. The directory of the source code
    * `out_dir`: Required. The directory of the instrumented code
    * `instr_languages`: Required. Comma-separated list of languages to instrument (e.g. 'python,java,c,cpp')
    * `exclude_dirs`: Optional. Comma-separated list of directories to exclude from instrumentation (e.g. 'deps,tests,examples')
    * `parallel_num`: Optional. The number of parallel instrumentation. Default is `10`
    * `chunk_size`: Optional. The chunk size for splitting one source file. Default is `800`
2. `run`: run the concolic execution with the instrumented code
    * `project_dir`: Required. The directory of the instrumented project
    * input: one of the following is required
        - `execution`: The initial execution file. **Note: In this file, you can use (1) file path relative to `project_dir`, or (2) absolute file path.**
        - `resume_in`: The output directory of one previous concolic execution (if you want to resume from previous concolic execution)
    * `out`: Required. The directory of the output, including the execution files, trace files, and summary files
    * `rounds`: Optional. The number of rounds to run
    * `selection`: Optional. The selection method for test cases. Default is `random`.
    * `timeout`: Optional. The timeout for each execution of the under-test-program. Default is `3` seconds.
    * `plateau_slot`: Optional. The plateau slot in minutes. The concolic execution will stop if the code coverage does not improve for this period of time (only used when `rounds` is not specified).
    * `parallel_num`: Optional. The number of parallel testcase generation. Default is `5`.
3. `replay`: replay the test cases
    * `out_dir`: Required. The output directory that contains the test cases for replay
    * `project_dir`: Required. The directory of the project with coverage instrumentation
    * `output_file`: Required. The file to save coverage data
    * `cov_script`: Optional. The script to collect (1) overall coverage data (including l_per, l_abs, b_per, b_abs) and (2) the number of times a specific line has been covered. The script should take three arguments: (i) relative file path, (ii) line number, and (iii) line content.
    * `timeout`: Optional. The timeout for the under-test-program execution. Default is `3` seconds.
4. `instrument_data`: collect and analyze instrumentation data
    * `directory`: Required. The directory to search for instrumentation data
    * `--extensions`: Optional. List of file extensions to search for
    * `--output`: Optional. Output CSV file path for saving instrumentation data
5. `run_data`: collect and analyze cost statistics
    * `out_dir`: Required. The directory to search for cost statistics
    * `--print-tokens`: Optional. Whether to print the tokens of the testcase. Default is `True`.

