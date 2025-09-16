"""
Tests for compress_paths function with mocked filesystem
"""

import os

import pytest

from app.utils.utils import compress_paths, list_all_files


class TestCompressPathsWithMock:
    """Test cases for compress_paths function using mock filesystem"""

    @pytest.fixture
    def mock_filesystem(self, tmp_path):
        """Create a mock filesystem structure for testing"""
        # Create a complex directory structure
        project_root = tmp_path / "project"

        # Create source directory
        src_dir = project_root / "src"
        src_dir.mkdir(parents=True)
        (src_dir / "main.py").write_text("print('Hello, world!')")
        (src_dir / "utils.py").write_text("# Utility functions")

        # Create models directory with subdirectories
        models_dir = src_dir / "models"
        models_dir.mkdir()
        (models_dir / "model1.py").write_text("class Model1: pass")
        (models_dir / "model2.py").write_text("class Model2: pass")

        # Create a deep nested directory
        deep_dir = src_dir / "deep" / "nested" / "directory"
        deep_dir.mkdir(parents=True)
        (deep_dir / "deep_file.py").write_text("# Deep file")

        # Create .git directory with many files (simulating a real .git)
        git_dir = project_root / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]\n\trepositoryformatversion = 0")

        # Create git objects directory with many subdirectories
        for i in range(5):
            obj_dir = git_dir / "objects" / f"{i:02d}"
            obj_dir.mkdir(parents=True)
            # Create some object files
            for j in range(3):
                (obj_dir / f"obj{j}.dat").write_text(f"Object {i}-{j}")

        # Create empty directories with marker files for compression tests
        empty_dir = project_root / "empty"
        empty_dir.mkdir()
        # Add a marker file to the empty directory
        (empty_dir / "README.md").write_text(
            "This directory is for testing empty directory compression"
        )

        for i in range(1, 6):
            subdir = empty_dir / f"subdir{i}"
            subdir.mkdir()
            # Add marker files in each subdirectory to ensure they're listed
            (subdir / "marker.txt").write_text(f"Marker file for subdir{i}")
            # Create deeper empty directories with marker files
            for j in range(1, 3):
                deeper = subdir / f"deeper{j}"
                deeper.mkdir()
                (deeper / "deep_marker.txt").write_text(
                    f"Marker for deeper{j} in subdir{i}"
                )

        # Return the project root path
        return project_root

    def test_compress_paths_with_real_files(self, mock_filesystem):
        """Test compress_paths with a simulated real filesystem"""
        # Get all files in the mock filesystem
        all_files = list_all_files(str(mock_filesystem))

        # Convert paths to be relative to the project root
        relative_files = [os.path.relpath(f, str(mock_filesystem)) for f in all_files]

        # Call the compress_paths function
        result = compress_paths(relative_files)

        # Verify the compressed structure
        assert "src" in result
        assert "src/models" in result
        assert "src/deep/nested/directory" in result

        # Git objects should be compressed
        assert ".git/objects/*" in result
        assert len(result[".git/objects/*"]) == 15  # 5 directories × 3 files

        # Check for empty directory compression
        # The empty dir and subdirs should be compressed due to many subdirectories with similar structure
        assert (
            "empty/subdir1/deeper1" in result
            or "empty/subdir*/deeper*" in result
            or "empty/*" in result
        )

        # Check file counts
        assert len(result["src"]) == 2  # main.py and utils.py
        assert len(result["src/models"]) == 2  # model1.py and model2.py
        assert len(result["src/deep/nested/directory"]) == 1  # deep_file.py

    def test_filter_specific_file_types(self, mock_filesystem):
        """Test compressing paths after filtering for specific file types"""
        # Get all files in the mock filesystem
        all_files = list_all_files(str(mock_filesystem))

        # Convert paths to be relative to the project root
        relative_files = [os.path.relpath(f, str(mock_filesystem)) for f in all_files]

        # Filter to only include Python files
        python_files = [f for f in relative_files if f.endswith(".py")]

        # Call the compress_paths function with just Python files
        result = compress_paths(python_files)

        # Verify the compressed structure has only Python files
        assert "src" in result
        assert "src/models" in result
        assert "src/deep/nested/directory" in result

        # No .git directories should be present (no Python files there)
        assert ".git" not in result
        assert ".git/objects/*" not in result

        # No empty directories should be present (no Python files there)
        assert "empty" not in result
        assert "empty/*" not in result

        # Check file counts for Python files
        assert len(result["src"]) == 2  # main.py and utils.py
        assert len(result["src/models"]) == 2  # model1.py and model2.py
        assert len(result["src/deep/nested/directory"]) == 1  # deep_file.py

    def test_empty_like_directories(self, tmp_path):
        """Test compression behavior with directories containing similar structure"""
        # Create a structure with many similar subdirectories
        root_dir = tmp_path / "similar_structure"
        root_dir.mkdir()

        # Create 10 subdirectories with identical structure
        all_files = []
        for i in range(10):
            subdir = root_dir / f"subdir{i}"
            subdir.mkdir()
            marker_file = subdir / "marker.txt"
            marker_file.write_text(f"Marker for subdir{i}")
            all_files.append(os.path.relpath(str(marker_file), str(tmp_path)))

        # Add a file to the root to prevent total compression
        root_file = root_dir / "root_file.txt"
        root_file.write_text("Root file")
        all_files.append(os.path.relpath(str(root_file), str(tmp_path)))

        # Call compress_paths on this structure
        result = compress_paths(all_files)

        # The subdirectories should be compressed
        compressed_key = None
        for key in result.keys():
            if "*" in key and "similar_structure" in key:
                compressed_key = key
                break

        assert (
            compressed_key is not None
        ), "Expected to find a compressed path for similar_structure"
        assert (
            len(result[compressed_key]) >= 10
        )  # Should contain at least the 10 marker files

    def test_large_directory_structure(self, tmp_path):
        """Test with a large directory structure that should be compressed"""
        # Create a large directory with many files
        large_dir = tmp_path / "large"
        large_dir.mkdir()

        # Create 100 files in 10 subdirectories (1000 files total)
        all_files = []
        for i in range(10):
            subdir = large_dir / f"subdir{i}"
            subdir.mkdir()
            for j in range(100):
                file_path = subdir / f"file{j}.txt"
                file_path.write_text(f"Content {i}-{j}")
                # Collect the relative path
                rel_path = os.path.relpath(str(file_path), str(tmp_path))
                all_files.append(rel_path)

        # Call compress_paths on this large structure
        result = compress_paths(all_files)

        # The large directory should be compressed
        assert "large/*" in result
        assert (
            len(result["large/*"]) == 1000
        )  # All files should be included in the compressed entry
