"""
Coverage management for the concolic execution.
"""

import copy
import multiprocessing
import os
import time

import dill
from loguru import logger

from app.agents.trace import TraceCollector


class Coverage:
    """Global coverage manager that tracks file coverage information."""

    _instance = None
    _save_process: multiprocessing.Process | None = None

    @classmethod
    def get_instance(cls):
        """Get singleton instance of Coverage."""
        if cls._instance is None:
            cls._instance = Coverage()
        return cls._instance

    def __init__(self):
        """Initialize the coverage manager."""
        if Coverage._instance is not None:
            raise RuntimeError("Use Coverage.get_instance() instead of constructor")
        self.file2cov: dict[str, TraceCollector] = (
            {}
        )  # relative file path (containing project dir) -> trace collector

    def get_file_coverage(self, file_path) -> TraceCollector | None:
        """Get a TraceCollector for a specific file.

        Args:
            file_path (str): The (relative) file path to get coverage for

        Returns:
            TraceCollector: The trace collector for the file
        """
        file_path = os.path.normpath(file_path)
        if file_path not in self.file2cov:
            self.file2cov[file_path] = TraceCollector(file_path)
        return self.file2cov.get(file_path)

    def collect_trace(
        self,
        file_path,
        trace,
        target_lines: tuple[int, int] | tuple[None, None] = (None, None),
        add_coverage: bool = True,
    ) -> tuple[int, bool, str]:
        """Collect trace information for a file.

        Args:
            file_path (str): The (relative) file path to collect trace for
            trace (str): The trace information
            target_lines (tuple[int, int] | tuple[None, None]): The target line range (of file_path) to reach
            add_coverage (bool): Whether to add coverage information

        Returns:
            - The number of new covered lines,
            - Whether the target lines are covered (return True if target_lines is None),
            - The execution summary
        """
        assert not (
            target_lines != (None, None) and not add_coverage
        ), "add_coverage should be True if target_lines is specified"
        file_path = os.path.normpath(file_path)
        tc = self.get_file_coverage(file_path)
        if tc:
            return tc.collect_trace(trace, target_lines, add_coverage)
        else:
            logger.error(f"Coverage information not available for file: {file_path}")
            return 0, False, ""

    def has_coverage_for(self, file_path):
        """Check if we have coverage information for a file.

        Args:
            file_path (str): The file to check

        Returns:
            bool: Whether we have coverage information
        """
        return os.path.normpath(file_path) in self.file2cov

    def get_all_files(self):
        """Get all files with coverage information.

        Returns:
            list: List of file paths
        """
        return list(self.file2cov.keys())

    def _save_to_file_process(self, file_path: str, data: dict) -> None:
        """Save coverage data in a separate process.

        Args:
            file_path (str): Path to save the coverage data
            data (dict): Data to save
        """
        try:
            start_time = time.time()

            with open(file_path, "wb") as f:
                dill.dump(
                    data,
                    f,
                    protocol=dill.HIGHEST_PROTOCOL,
                    recurse=True,
                    byref=False,
                )

            elapsed_time = time.time() - start_time
            logger.info(
                f"Coverage data saved to {file_path} in {elapsed_time:.2f} seconds"
            )
        except Exception as e:
            logger.error(f"Failed to save coverage data: {e}")

    def save_to_file(self, file_path: str, async_save: bool = True) -> bool:
        """Save the coverage data to a file using dill.

        Args:
            file_path (str): Path to save the coverage data
            async_save (bool): Whether to save in a separate process

        Returns:
            bool: Whether the save was successful
        """
        try:
            # Prepare data to save with deep copy
            data_to_save = {
                "file2cov": copy.deepcopy(self.file2cov),
            }

            if async_save:
                # Wait for previous save process to complete if it exists
                if (
                    Coverage._save_process is not None
                    and Coverage._save_process.is_alive()
                ):
                    Coverage._save_process.join()

                # Start new save process with current data
                Coverage._save_process = multiprocessing.Process(
                    target=self._save_to_file_process, args=(file_path, data_to_save)
                )
                Coverage._save_process.start()
                logger.info(f"Started async save process for {file_path}")
                return True
            else:
                # Synchronous save
                start_time = time.time()

                with open(file_path, "wb") as f:
                    dill.dump(
                        data_to_save,
                        f,
                        protocol=dill.HIGHEST_PROTOCOL,
                        recurse=True,
                        byref=False,
                    )

                elapsed_time = time.time() - start_time
                logger.info(
                    f"Coverage data saved to {file_path} in {elapsed_time:.2f} seconds"
                )
                return True
        except Exception as e:
            logger.error(f"Failed to save coverage data: {e}")
            return False

    @classmethod
    def load_from_file(cls, file_path):
        """Load coverage data from a file using dill.

        Args:
            file_path (str): Path to load the coverage data from

        Returns:
            Coverage: A new Coverage instance with the loaded data
        """
        try:
            start_time = time.time()

            with open(file_path, "rb") as f:
                loaded_data = dill.load(f)
                instance = cls.get_instance()
                instance.file2cov = loaded_data["file2cov"]
                cls._instance = instance

            elapsed_time = time.time() - start_time
            logger.info(
                f"Coverage data loaded from {file_path} in {elapsed_time:.2f} seconds"
            )
            return cls._instance
        except Exception as e:
            logger.error(f"Failed to load coverage data: {e}")
            return cls.get_instance()
