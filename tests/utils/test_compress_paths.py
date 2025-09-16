"""
Tests for compress_paths function in utils.py
"""

import os

from app.utils.utils import compress_paths


class TestCompressPaths:
    """Test cases for compress_paths function"""

    def test_empty_list(self):
        """Test with empty list input"""
        result = compress_paths([])
        assert result == {}

    def test_single_file(self):
        """Test with a single file input"""
        result = compress_paths(["file.txt"])
        # Single file with no directory should be handled correctly
        assert len(result) == 1
        assert "" in result  # Root directory
        assert "file.txt" in result[""]

    def test_flat_directory(self):
        """Test with files in a flat directory structure"""
        files = [
            "dir/file1.txt",
            "dir/file2.txt",
            "dir/file3.txt",
        ]
        result = compress_paths(files)
        assert "dir" in result
        assert len(result["dir"]) == 3
        assert "file1.txt" in result["dir"]
        assert "file2.txt" in result["dir"]
        assert "file3.txt" in result["dir"]

    def test_nested_directory(self):
        """Test with files in nested directories"""
        files = [
            "root/dir1/file1.txt",
            "root/dir1/file2.txt",
            "root/dir2/file3.txt",
        ]
        result = compress_paths(files)
        # Should not compress because both dir1 and dir2 have files
        assert "root/dir1" in result
        assert "root/dir2" in result
        assert len(result["root/dir1"]) == 2
        assert len(result["root/dir2"]) == 1

    def test_compression_empty_dirs(self):
        """Test compression of empty directories"""
        files = [
            "root/dir1/sub1/sub2/file1.txt",
        ]
        result = compress_paths(files)
        # Should not compress because the directory has files
        assert "root/dir1/sub1/sub2" in result
        assert len(result["root/dir1/sub1/sub2"]) == 1

    def test_compression_multiple_empty_subdirs(self):
        """Test compression of directories with empty subdirectories"""
        # This is an empty directory structure without files
        files = []
        for i in range(1, 6):  # Create paths without files
            files.append(f"empty/sub{i}/")

        # Add one actual file to validate the structure
        files.append("empty/marker.txt")

        result = compress_paths(files)
        # The empty directories should be compressed, but the file should remain
        assert "empty/*" not in result  # Not compressed because it has a direct file
        assert "empty" in result  # The directory with the file is kept

    def test_complex_directory_structure(self):
        """Test with a complex directory structure"""
        files = [
            # .git directory with many files - should be compressed
            ".git/objects/00/file1.dat",
            ".git/objects/00/file2.dat",
            ".git/objects/01/file1.dat",
            ".git/objects/01/file2.dat",
            ".git/objects/02/file1.dat",
            # Multiple subdirectories with many files
            ".git/refs/heads/main.txt",
            ".git/refs/tags/v1.txt",
            ".git/refs/tags/v2.txt",
            # A file in the .git directory
            ".git/config",
            # Regular source code
            "src/main.py",
            "src/utils.py",
            "src/models/model1.py",
            "src/models/model2.py",
            # Test directory
            "tests/test_main.py",
            "tests/test_utils.py",
        ]

        result = compress_paths(files)

        # Check for .git/objects compression - it might be compressed in different ways
        git_objects_compressed = False
        for key in result:
            if ".git/objects" in key and "*" in key:
                git_objects_compressed = True
                break

        assert git_objects_compressed, "Expected some form of .git/objects compression"

        # .git directory itself should not be compressed because it has direct files
        assert ".git" in result
        # Source files should be organized by directory
        assert "src" in result
        assert "src/models" in result
        assert "tests" in result

        # Check file counts for non-compressed directories
        assert len(result[".git"]) == 1  # Just the config file
        assert len(result["src"]) == 2  # main.py and utils.py

    def test_absolute_paths(self):
        """Test with absolute paths"""
        # OS-agnostic way to create absolute paths for testing
        base = os.path.abspath(os.sep)
        files = [
            os.path.join(base, "tmp", "file1.txt"),
            os.path.join(base, "tmp", "file2.txt"),
            os.path.join(base, "var", "log", "syslog"),
        ]

        result = compress_paths(files)

        # Get actual keys for paths with /tmp and /var/log
        tmp_path_key = None
        var_log_key = None
        for key in result:
            if key.endswith("tmp"):
                tmp_path_key = key
            elif key.endswith("var/log"):
                var_log_key = key

        assert tmp_path_key is not None, "Expected some form of /tmp path"
        assert var_log_key is not None, "Expected some form of /var/log path"
        assert len(result[tmp_path_key]) == 2
        assert len(result[var_log_key]) == 1

    def test_path_with_spaces(self):
        """Test paths containing spaces"""
        files = [
            "My Documents/file1.txt",
            "My Documents/file2.txt",
            "Program Files/App/config.ini",
        ]

        result = compress_paths(files)

        assert "My Documents" in result
        assert "Program Files/App" in result
        assert len(result["My Documents"]) == 2
        assert len(result["Program Files/App"]) == 1
