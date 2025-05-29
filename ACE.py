"""

ConcoLLMic - Agentic Concolic Execution

For more details, visit
https://github.com/ConcoLLMic/ConcoLLMic

=================================================

ACE.py: Main entry point for the ConcoLLMic tool.

"""

import argparse
import atexit
import os
import signal
import sys
import time

from loguru import logger

from app.commands.instrument import instrument_code, setup_instrument_parser
from app.commands.instrument_data import (
    collect_instrument_data,
    setup_instrument_data_parser,
)
from app.commands.replay import replay_test_case, setup_replay_parser
from app.commands.run import TestCaseSelection, run_concolic_execution, setup_run_parser
from app.commands.run_data import collect_run_data, setup_run_data_parser
from app.model.common import get_total_retry_attempts, set_model
from app.model.register import register_all_models

# Global variables for logging
LOG_DIR = "logs"


def setup_logging(log_dir: str) -> str:

    LOG_FILE_PREFIX = "ConcoLLMic"
    LOG_TIMESTAMP = time.strftime("%Y%m%d_%H%M%S")
    LOG_FILENAME = f"{LOG_FILE_PREFIX}_{LOG_TIMESTAMP}.log"
    """Setup logging configuration"""
    logger.configure(
        handlers=[
            {
                "sink": sys.stdout,
                "level": "INFO",
            }  # Modified the default log output level to INFO
        ]
    )

    log_file_path = os.path.abspath(os.path.join(log_dir, LOG_FILENAME))

    # Add file handler
    logger.add(
        log_file_path,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level="DEBUG",
        encoding="utf-8",
    )

    return log_file_path


def print_log_summary(log_file_path: str):
    """Print summary of warnings and errors from current log file and total retries"""
    warning_count = 0
    error_count = 0
    warning_lines = []
    error_lines = []

    TOKEN = " LOG SUMMARY "

    logger.info("=" * 25 + TOKEN + "=" * 25)
    # Use the current session's log file directly
    if os.path.exists(log_file_path):
        try:
            with open(log_file_path, encoding="utf-8") as f:
                for line_no, line in enumerate(f):
                    if "| WARNING |" in line:
                        warning_count += 1
                        warning_lines.append(
                            (line_no, line.split("| WARNING |")[1].strip())
                        )
                    elif "| ERROR |" in line:
                        error_count += 1
                        error_lines.append(
                            (line_no, line.split("| ERROR |")[1].strip())
                        )
        except Exception as e:
            logger.error(f"Error reading log file {log_file_path}: {e}")

        # Print actual warning and error lines
        if warning_lines:
            logger.info("\033[33mWARNINGS:\033[0m")
            for line_no, line in warning_lines:
                logger.info(f"\t\033[33m{line_no}: {line}\033[0m")

        if error_lines:
            logger.info("\033[31mERRORS:\033[0m")
            for line_no, line in error_lines:
                logger.info(f"\t\033[31m{line_no}: {line}\033[0m")

        logger.info("-" * (50 + len(TOKEN)))

        # Print summary with colored output

        logger.info(f"Log file: \033[36m{log_file_path}\033[0m")

        if warning_count > 0:
            logger.info(
                f"\tWarnings: \033[33m{warning_count}\033[0m"
            )  # Yellow for warnings
        else:
            logger.info("\tWarnings: \033[32m0\033[0m")  # Green for zero warnings

        if error_count > 0:
            logger.info(f"\tErrors: \033[31m{error_count}\033[0m")  # Red for errors
        else:
            logger.info("\tErrors: \033[32m0\033[0m")  # Green for zero errors

        # Print total retry attempts
        if get_total_retry_attempts() > 0:
            logger.info(
                f"Total LLM Retry Attempts: \033[35m{get_total_retry_attempts()}\033[0m"
            )  # Magenta for retries
        else:
            logger.info(
                f"Total LLM Retry Attempts: \033[32m{get_total_retry_attempts()}\033[0m"
            )  # Green for zero retries

    else:
        logger.info("Log Summary: No log file found")

    logger.info("=" * (50 + len(TOKEN)))


def signal_handler(signum, frame, log_file_path: str):
    """Handle termination signals"""
    logger.info(
        "\033[1;34mReceived termination signal, exiting...\033[0m"
    )  # Bold blue for termination message
    print_log_summary(log_file_path)
    sys.exit(0)


def setup_model():
    """Setup and initialize model"""
    register_all_models()
    set_model("claude-3-7-sonnet-20250219")


def initialize_settings(log_dir: str = LOG_DIR):
    """Initialize settings"""

    # Setup model
    setup_model()

    # Setup logging
    log_file_path = setup_logging(log_dir)

    # Setup exception hook to log uncaught exceptions
    def exception_handler(exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions and log them"""
        logger.opt(exception=(exc_type, exc_value, exc_traceback)).error(
            "Uncaught exception:"
        )
        # Call the default exception handler
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    # Register the exception hook
    sys.excepthook = exception_handler

    # Register signal/exit handler
    signal.signal(
        signal.SIGINT,
        lambda signum, frame: signal_handler(signum, frame, log_file_path),
    )
    signal.signal(
        signal.SIGTERM,
        lambda signum, frame: signal_handler(signum, frame, log_file_path),
    )
    atexit.register(lambda: print_log_summary(log_file_path))


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="ConcoLLMic - Agentic Concolic Execution")

    # Create subparsers for commands
    subparsers = parser.add_subparsers(dest="command", help="command to execute")

    # Setup subcommand parsers
    setup_instrument_parser(subparsers)
    setup_run_parser(subparsers)
    setup_instrument_data_parser(subparsers)
    setup_run_data_parser(subparsers)
    setup_replay_parser(subparsers)
    return parser.parse_args()


def main():
    """Main entry point"""
    args = parse_arguments()

    if args.command == "instrument":
        initialize_settings()

        # Perform instrumentation phase
        instrument_code(
            src_dir=os.path.normpath(args.src_dir),
            out_dir=os.path.normpath(args.out_dir),
            instr_languages=args.instr_languages,
            exclude_dirs=args.exclude_dirs,
            parallel_num=args.parallel_num,
            chunk_size=args.chunk_size,
        )

    elif args.command == "run":

        out_dir = os.path.normpath(args.out)

        try:
            os.makedirs(out_dir, exist_ok=False)
        except FileExistsError:
            # check if the directory is empty (ignore empty subdirectories)
            if os.path.exists(out_dir):
                is_empty = True
                for root, dirs, files in os.walk(out_dir):
                    if files:  # if there are files, the directory is not empty
                        is_empty = False
                        break
                if not is_empty:
                    raise Exception("Output directory is not empty")

        initialize_settings(log_dir=out_dir)

        logger.info(f'Concolic execution command: {" ".join(sys.argv)}')

        # Perform concolic execution phase
        run_concolic_execution(
            project_dir=os.path.normpath(args.project_dir),
            out_dir=out_dir,
            test_selection=TestCaseSelection(args.selection),
            timeout=args.timeout,
            initial_execution_file=(
                os.path.normpath(args.execution) if args.execution else None
            ),
            rounds=args.rounds,
            resume_in=(os.path.normpath(args.resume_in) if args.resume_in else None),
            plateau_slot=args.plateau_slot,
            parallel_num=args.parallel_num,
        )

    elif args.command == "instrument_data":
        # Collect and analyze cost statistics
        collect_instrument_data(
            directory=os.path.normpath(args.directory),
            extensions=args.extensions,
            output=os.path.normpath(args.output) if args.output else None,
        )

    elif args.command == "run_data":
        # Collect and analyze cost statistics
        collect_run_data(
            out_dir=os.path.normpath(args.out_dir),
            print_tokens=args.print_tokens,
        )

    elif args.command == "replay":
        # Replay test cases
        replay_test_case(
            out_dir=os.path.normpath(args.out_dir),
            project_dir=os.path.normpath(args.project_dir),
            timeout=args.timeout,
            cov_script=os.path.normpath(args.cov_script) if args.cov_script else None,
            output_file=(
                os.path.normpath(args.output_file) if args.output_file else None
            ),
        )

    else:
        logger.error(
            "Please specify a command: instrument, run, instrument_data, run_data, or replay"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
