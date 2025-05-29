def execute_program(timeout: int) -> tuple[str, int]:
    import signal
    import subprocess
    import tempfile

    # Create a temporary file
    with tempfile.NamedTemporaryFile(mode="w") as temp_file:
        temp_file.write(
            '{"k1": 1, "k2": 2, "k3": 325222552522.111111111112222111, "k4": 4}'
        )
        temp_file.flush()
        temp_file_path = temp_file.name

        try:
            result = subprocess.run(
                [
                    "python3",
                    "ujson_app.py",
                    "encode",
                    temp_file_path,
                ],  # `ujson_app.py` is the test harness and DO NOT MODIFY this file
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            # return stderr and the returncode
            return result.stderr, result.returncode
        except subprocess.TimeoutExpired as e:
            # Timeout occurred, also ensure to return stderr captured before timeout and return code -signal.SIGKILL
            return e.stderr, -signal.SIGKILL
        except Exception as e:
            # ensure to raise the error if run failed
            raise e
