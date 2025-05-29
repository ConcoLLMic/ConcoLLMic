import os
import shutil
import tempfile

import pytest

from app.agents.coverage import Coverage


class TestCoverage:
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def sample_file_path(self, temp_dir):
        """Create a sample file for testing."""
        file_path = os.path.join(temp_dir, "test_file.py")
        with open(file_path, "w") as f:
            f.write(
                "import sys\n\ndef test_function():\n    sys.stderr.write('enter test_function 1')\n    print('Hello, World!')\n    sys.stderr.write('exit test_function 1')\n"
            )
        return file_path

    @pytest.fixture
    def coverage_instance(self, sample_file_path):
        """Get a coverage instance with some data."""
        # Reset singleton instance for tests
        Coverage._instance = None

        # Get a fresh instance
        coverage = Coverage.get_instance()

        # Generate a sample trace
        sample_trace = "enter test_function 1\nexit test_function 1\n"

        # Collect trace information
        new_covered_lines, is_target_lines_covered, execution_summary = (
            coverage.collect_trace(sample_file_path, sample_trace, target_lines=(4, 4))
        )
        assert new_covered_lines == 1, "New covered lines should be 1"
        assert is_target_lines_covered, "Target lines should be covered"
        assert execution_summary.__contains__(
            "import sys\n\ndef test_function():\n    print('Hello, World!')\n"
        ), "Execution summary should be correct"

        return coverage

    def test_save_and_load(self, temp_dir, coverage_instance, sample_file_path):
        """Test saving and loading coverage data."""
        # Define save path
        save_path = os.path.join(temp_dir, "coverage_data.dill")

        # Save coverage data
        success = coverage_instance.save_to_file(
            save_path, async_save=False
        )  # sync save
        assert success, "Failed to save coverage data"
        assert os.path.exists(save_path), "Save file was not created"

        # Get a list of files and other data before loading
        original_files = coverage_instance.get_all_files()
        original_has_coverage = coverage_instance.has_coverage_for(sample_file_path)

        # Reset singleton instance to simulate application restart
        Coverage._instance = None

        # Load coverage data
        loaded_coverage = Coverage.load_from_file(save_path)

        # Check if the loaded instance is properly set as singleton
        assert Coverage.get_instance() is loaded_coverage

        # Verify loaded data
        loaded_files = loaded_coverage.get_all_files()
        loaded_has_coverage = loaded_coverage.has_coverage_for(sample_file_path)

        # Assert data integrity
        assert loaded_files == original_files, "Files list doesn't match after loading"
        assert (
            loaded_has_coverage == original_has_coverage
        ), "Coverage status doesn't match after loading"

        # Get trace collectors and verify they are properly loaded
        original_tc = coverage_instance.get_file_coverage(sample_file_path)
        loaded_tc = loaded_coverage.get_file_coverage(sample_file_path)

        # Verify TraceCollector objects
        assert loaded_tc is not None, "TraceCollector not loaded properly"
        assert (
            loaded_tc.file_path == original_tc.file_path
        ), "TraceCollector file_path doesn't match"
        assert (
            loaded_tc.language == original_tc.language
        ), "TraceCollector language doesn't match"

        # Verify internal data structures
        assert loaded_tc.line2code, "TraceCollector line2code is empty"
        assert loaded_tc.block2cov, "TraceCollector block2cov is empty"
        assert (
            loaded_tc.line2code == original_tc.line2code
        ), "TraceCollector line2code doesn't match"

    def test_async_save(self, temp_dir, coverage_instance):
        """Test asynchronous save functionality."""
        save_path = os.path.join(temp_dir, "coverage_async.dill")

        # Start async save
        success = coverage_instance.save_to_file(save_path, async_save=True)
        assert success, "Failed to start async save"

        # Wait for save process to complete
        if Coverage._save_process is not None:
            Coverage._save_process.join()

        # Verify file exists after save process completes
        assert os.path.exists(save_path), "Save file was not created after async save"

    def test_error_handling(self, temp_dir):
        """Test error handling during save and load."""
        # Initialize coverage
        Coverage._instance = None
        coverage = Coverage.get_instance()

        # Try to save to invalid location with sync save
        invalid_path = os.path.join(temp_dir, "non_existent_dir", "coverage.dill")
        success = coverage.save_to_file(invalid_path, async_save=False)
        assert not success, "Save to invalid location should fail with sync save"

        # Try async save to invalid location
        success = coverage.save_to_file(invalid_path, async_save=True)
        assert success, "Async save should return success immediately"

        # Wait for save process to complete
        if Coverage._save_process is not None:
            Coverage._save_process.join()

        # Verify file doesn't exist after failed async save
        assert not os.path.exists(
            invalid_path
        ), "File should not exist after failed async save"

        # Try to load from non-existent file
        non_existent_file = os.path.join(temp_dir, "non_existent.dill")
        loaded = Coverage.load_from_file(non_existent_file)
        assert (
            loaded is Coverage.get_instance()
        ), "Should return default instance on load failure"
