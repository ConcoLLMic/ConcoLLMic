def execute_program(timeout: int) -> tuple[str, int]:
    import binascii
    import signal
    import subprocess
    import tempfile

    hex_data = [
        "774f 4632 0001 0000 0000 0248 000d 0000",
        "0000 05f0 0000 01f6 0001 0000 0000 0000",
        "0000 0000 0000 0000 0000 0000 0000 0000",
        "3f46 4654 4d1c 0656 0082 4208 0411 080a",
        "5071 0b0a 0001 3602 2403 1004 2005 843a",
        "072a 1b1e 05c8 9e05 76cb 476a 3157 7a0c",
        "0fb1 21fa 1c7e e3e1 fff7 fbb6 cf7d f7ab",
        "a699 8124 2259 9388 370d 9144 22fd 1268",
        "7f4a a004 160d aafa b36a db3e 5a1a 9e35",
        "923c 8547 f560 8652 6809 d8ee d08a 8779",
        "ea26 ff26 1a05 606b 81b4 3dcd c32c d08c",
        "e2ed 6160 51d6 6561 a01e 08b5 3b93 e2a0",
        "7d2e 8f38 d68e 7d0e abc1 a3d8 1901 afb6",
        "7d7c 0a00 6fcf 10b6 c573 1575 570d 6002",
        "b71f a65a 4552 29c0 818e dd29 6ac4 0c2b",
        "cdd0 3103 0128 5060 4180 030a 8105 d94a",
        "6459 6065 59c6 df33 e51b 0051 2500 9190",
        "0000 41c1 9ca5 e22a 88b2 9440 0675 24d4",
        "d100 646c 9280 9c5b d1b2 ab15 cdca ad35",
        "b5a3 5dd0 5c98 4736 1f58 fef3 6edb bcbe",
        "3eb0 bce3 dd36 f3a2 04d5 2a51 e36f 40bc",
        "3910 fc74 f6bb daf3 adde 32eb 9aaf 2236",
        "ba05 ea12 08cc d0b1 0d6c 1400 806c 9b0a",
        "d886 6d08 6475 0924 3435 51da 04e8 7b09",
        "101a c602 2435 9b04 2834 1cc5 40d6 700f",
        "0315 2dcf 04a8 6a78 2140 d3fa 680b d032",
        "8a6b 4491 1bc2 90cc 93ae 255e 18da 0532",
        "39c5 2ba6 1ef1 aaa1 196f 3ae3 5fdf b22a",
        "f6b8 afb2 595d 5a9b 1581 1c04 d7c0 1a06",
        "4e68 746e 33ee 8497 62ed 8168 d428 cf68",
        "9c0e 0d75 c356 9b6c 6125 e914 6cda 8206",
        "87c2 9540 cd91 46bd fd86 97e1 b147 27f4",
        "0469 19ee 386d 1686 83be af31 9b6d 0c0f",
        "ec95 51a3 425c 4eda d5eb e942 a276 8f31",
        "ae37 0d3d e1fc b97d 0eee 2164 17d9 6cb3",
        "3bc4 a1cb 3d5f 4067 1a9c 8d79 c490 e911",
        "2001 0289 29c8 1311",
    ]

    # merge hex strings and convert to binary data
    hex_str = "".join(line.replace(" ", "") for line in hex_data)
    binary_data = binascii.unhexlify(hex_str)

    # create a temporary file
    with tempfile.NamedTemporaryFile(mode="wb") as temp_file:
        # write binary data to file
        temp_file.write(binary_data)
        temp_file.flush()
        temp_file_path = temp_file.name
        try:
            result = subprocess.run(
                ["./woff2_decompress", temp_file_path],
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
