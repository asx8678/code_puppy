"""Tests for enhanced cleanup functionality in the clean command plugin."""

from pathlib import Path
from unittest import mock

from code_puppy import config

from ._disk_usage import _check_disk_usage, _dir_stats, _file_stats, _human_size
from ._orphan_detection import (
    _find_orphans,
    _count_orphans_in_dirs,
    _KNOWN_DATA_FILES,
    _KNOWN_CONFIG_FILES,
)
from ._auto_cleanup import _load_cleanup_config


class TestHumanSize:
    """Tests for _human_size function."""

    def test_bytes(self):
        """Test formatting of small byte values."""
        assert _human_size(0) == "0 B"
        assert _human_size(512) == "512 B"
        assert _human_size(1023) == "1023 B"

    def test_kilobytes(self):
        """Test formatting of KB values."""
        assert _human_size(1024) == "1.0 KB"
        assert _human_size(1536) == "1.5 KB"
        assert _human_size(1024 * 512) == "512.0 KB"

    def test_megabytes(self):
        """Test formatting of MB values."""
        assert _human_size(1024 * 1024) == "1.0 MB"
        assert _human_size(1024 * 1024 * 100) == "100.0 MB"
        assert _human_size(1024 * 1024 * 500) == "500.0 MB"

    def test_gigabytes(self):
        """Test formatting of GB values."""
        assert _human_size(1024 * 1024 * 1024) == "1.0 GB"
        assert _human_size(1024 * 1024 * 1024 * 5) == "5.0 GB"


class TestDirStats:
    """Tests for _dir_stats function."""

    def test_normal_directory(self, tmp_path: Path):
        """Test stats for a directory with files."""
        # Create test files
        (tmp_path / "file1.txt").write_text("a" * 100)
        (tmp_path / "file2.txt").write_text("b" * 200)
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file3.txt").write_text("c" * 300)

        count, total = _dir_stats(tmp_path)
        assert count == 3
        assert total == 600

    def test_empty_directory(self, tmp_path: Path):
        """Test stats for an empty directory."""
        count, total = _dir_stats(tmp_path)
        assert count == 0
        assert total == 0

    def test_nonexistent_directory(self):
        """Test stats for a non-existent directory."""
        count, total = _dir_stats(Path("/nonexistent/path"))
        assert count == 0
        assert total == 0


class TestFileStats:
    """Tests for _file_stats function."""

    def test_existing_file(self, tmp_path: Path):
        """Test stats for an existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("a" * 500)

        count, total = _file_stats(test_file)
        assert count == 1
        assert total == 500

    def test_nonexistent_file(self, tmp_path: Path):
        """Test stats for a non-existent file."""
        count, total = _file_stats(tmp_path / "nonexistent.txt")
        assert count == 0
        assert total == 0

    def test_directory_not_file(self, tmp_path: Path):
        """Test that directories return 0 stats."""
        count, total = _file_stats(tmp_path)
        assert count == 0
        assert total == 0


class TestCheckDiskUsage:
    """Tests for _check_disk_usage function."""

    def test_normal_directory(self, tmp_path: Path):
        """Test disk usage check for normal sized directory."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("a" * 1000)

        total, warning = _check_disk_usage(tmp_path)
        assert total == 1000
        assert warning is None  # Below 100MB threshold

    def test_large_directory_warning(self, tmp_path: Path):
        """Test warning for large directory (>100MB)."""
        # Mock _dir_stats to return large size
        with mock.patch(
            "code_puppy.plugins.clean_command._disk_usage._dir_stats",
            return_value=(1, 150 * 1024 * 1024),
        ):
            total, warning = _check_disk_usage(tmp_path)
            assert total == 150 * 1024 * 1024
            assert warning is not None
            assert "Warning" in warning
            assert "150.0 MB" in warning

    def test_critical_directory_warning(self, tmp_path: Path):
        """Test critical warning for very large directory (>500MB)."""
        with mock.patch(
            "code_puppy.plugins.clean_command._disk_usage._dir_stats",
            return_value=(1, 600 * 1024 * 1024),
        ):
            total, warning = _check_disk_usage(tmp_path)
            assert total == 600 * 1024 * 1024
            assert warning is not None
            assert "CRITICAL" in warning
            assert "600.0 MB" in warning

    def test_nonexistent_path(self):
        """Test disk usage check for non-existent path."""
        total, warning = _check_disk_usage(Path("/nonexistent/path"))
        assert total == 0
        assert warning is None


class TestFindOrphans:
    """Tests for _find_orphans function."""

    def test_broken_symlink(self, tmp_path: Path):
        """Test that broken symlinks are detected."""
        # Create a file and a symlink to it
        target = tmp_path / "target.txt"
        target.write_text("content")
        symlink = tmp_path / "link.txt"
        symlink.symlink_to(target)

        # Remove target to break the symlink
        target.unlink()

        orphans = _find_orphans(tmp_path)
        assert len(orphans) == 1
        assert orphans[0] == symlink

    def test_backup_files(self, tmp_path: Path):
        """Test that backup files (ending with ~) are detected."""
        (tmp_path / "file.txt").write_text("content")
        backup = tmp_path / "file.txt~"
        backup.write_text("backup content")

        orphans = _find_orphans(tmp_path)
        assert backup in orphans

    def test_temp_files(self, tmp_path: Path):
        """Test that temp files (.tmp, .temp) are detected."""
        tmp_file = tmp_path / "temp.tmp"
        temp_file = tmp_path / "data.temp"
        tmp_file.write_text("temp")
        temp_file.write_text("temp2")

        orphans = _find_orphans(tmp_path)
        assert tmp_file in orphans
        assert temp_file in orphans

    def test_known_bad_hidden_files(self, tmp_path: Path):
        """Test that known bad hidden files are detected."""
        ds_store = tmp_path / ".DS_Store"
        tmp_hidden = tmp_path / ".tmp_12345"
        ds_store.write_text("mac metadata")
        tmp_hidden.write_text("temp data")

        orphans = _find_orphans(tmp_path)
        assert ds_store in orphans
        assert tmp_hidden in orphans

    def test_legitimate_hidden_files_not_flagged(self, tmp_path: Path):
        """Test that legitimate hidden files (.gitignore, .gitkeep) are NOT flagged."""
        gitignore = tmp_path / ".gitignore"
        gitkeep = tmp_path / ".gitkeep"
        gitignore.write_text("*.pyc")
        gitkeep.write_text("")

        orphans = _find_orphans(tmp_path)
        assert gitignore not in orphans
        assert gitkeep not in orphans

    def test_unknown_extensions(self, tmp_path: Path):
        """Test that files with unknown extensions are detected."""
        unknown = tmp_path / "file.xyz"
        unknown.write_text("unknown")

        orphans = _find_orphans(tmp_path)
        assert unknown in orphans

    def test_known_extensions_not_flagged(self, tmp_path: Path):
        """Test that files with known extensions are NOT flagged."""
        json_file = tmp_path / "data.json"
        json_file.write_text('{"key": "value"}')

        orphans = _find_orphans(tmp_path)
        assert json_file not in orphans

    def test_known_db_files_not_flagged(self, tmp_path: Path):
        """Test that legitimate DB files are NOT flagged as orphans."""
        # These are the known legitimate DB files
        db_file = tmp_path / "dbos_store.sqlite"
        db_shm = tmp_path / "dbos_store.sqlite-shm"
        db_wal = tmp_path / "dbos_store.sqlite-wal"
        db_file.write_bytes(b"sqlite data")
        db_shm.write_bytes(b"shm data")
        db_wal.write_bytes(b"wal data")

        orphans = _find_orphans(tmp_path)
        assert db_file not in orphans
        assert db_shm not in orphans
        assert db_wal not in orphans

    def test_unknown_db_files_flagged(self, tmp_path: Path):
        """Test that unknown/unreferenced DB files ARE flagged as orphans."""
        # Generic DB files not in the known list should be orphans
        sqlite_file = tmp_path / "data.sqlite"
        db_file = tmp_path / "code_puppy_dev.db"
        db_shm = tmp_path / "code_puppy_dev.db-shm"
        db_wal = tmp_path / "code_puppy_dev.db-wal"
        sqlite_file.write_bytes(b"sqlite data")
        db_file.write_bytes(b"db data")
        db_shm.write_bytes(b"shm data")
        db_wal.write_bytes(b"wal data")

        orphans = _find_orphans(tmp_path)
        assert sqlite_file in orphans
        assert db_file in orphans
        assert db_shm in orphans
        assert db_wal in orphans

    def test_empty_directory(self, tmp_path: Path):
        """Test that empty directories return empty orphan list."""
        orphans = _find_orphans(tmp_path)
        assert orphans == []

    def test_nonexistent_directory(self):
        """Test that non-existent directories return empty orphan list."""
        orphans = _find_orphans(Path("/nonexistent/path"))
        assert orphans == []


class TestLoadCleanupConfig:
    """Tests for _load_cleanup_config function."""

    def test_valid_config(self, tmp_path: Path):
        """Test loading a valid config file."""
        config_file = tmp_path / "puppy.cfg"
        config_file.write_text("""
[cleanup]
auto_clean_on_startup = true
auto_clean_max_age_days = 7
auto_clean_categories = cache,logs,orphans
""")

        with mock.patch.object(config, "CONFIG_FILE", config_file):
            cfg = _load_cleanup_config()
            assert cfg["enabled"] is True
            assert cfg["max_age_days"] == 7
            assert cfg["categories"] == ["cache", "logs", "orphans"]

    def test_missing_config(self, tmp_path: Path):
        """Test loading when config file doesn't exist."""
        nonexistent = tmp_path / "nonexistent.cfg"

        with mock.patch.object(config, "CONFIG_FILE", nonexistent):
            cfg = _load_cleanup_config()
            assert cfg["enabled"] is False
            assert cfg["max_age_days"] == 30
            assert cfg["categories"] == ["cache", "logs"]

    def test_no_cleanup_section(self, tmp_path: Path):
        """Test loading config without [cleanup] section."""
        config_file = tmp_path / "puppy.cfg"
        config_file.write_text("""
[general]
model = claude
""")

        with mock.patch.object(config, "CONFIG_FILE", config_file):
            cfg = _load_cleanup_config()
            assert cfg["enabled"] is False
            assert cfg["max_age_days"] == 30
            assert cfg["categories"] == ["cache", "logs"]

    def test_invalid_values(self, tmp_path: Path):
        """Test handling of invalid config values."""
        config_file = tmp_path / "puppy.cfg"
        config_file.write_text("""
[cleanup]
auto_clean_on_startup = invalid_bool
auto_clean_max_age_days = not_a_number
""")

        with mock.patch.object(config, "CONFIG_FILE", config_file):
            cfg = _load_cleanup_config()
            # Should use defaults for invalid values
            assert cfg["enabled"] is False
            assert cfg["max_age_days"] == 30
            assert cfg["categories"] == ["cache", "logs"]

    def test_empty_categories(self, tmp_path: Path):
        """Test that empty categories string results in empty list."""
        config_file = tmp_path / "puppy.cfg"
        config_file.write_text("""
[cleanup]
auto_clean_categories =
""")

        with mock.patch.object(config, "CONFIG_FILE", config_file):
            cfg = _load_cleanup_config()
            # Empty string should result in empty list (no auto-cleanup categories)
            assert cfg["categories"] == []

    def test_various_boolean_strings(self, tmp_path: Path):
        """Test various boolean string formats for enabled flag."""
        config_file = tmp_path / "puppy.cfg"

        for value in ["true", "True", "1", "yes", "on"]:
            config_file.write_text(f"""
[cleanup]
auto_clean_on_startup = {value}
""")
            with mock.patch.object(config, "CONFIG_FILE", config_file):
                cfg = _load_cleanup_config()
                assert cfg["enabled"] is True, f"Failed for value: {value}"

        for value in ["false", "False", "0", "no", "off", "random"]:
            config_file.write_text(f"""
[cleanup]
auto_clean_on_startup = {value}
""")
            with mock.patch.object(config, "CONFIG_FILE", config_file):
                cfg = _load_cleanup_config()
                assert cfg["enabled"] is False, f"Failed for value: {value}"


class TestCountOrphansInDirs:
    """Tests for _count_orphans_in_dirs function."""

    def test_counts_orphans_across_dirs(self, tmp_path: Path):
        """Test that orphans are counted across all XDG directories."""
        # Create temp dirs to simulate XDG dirs
        cache_dir = tmp_path / "cache"
        data_dir = tmp_path / "data"
        state_dir = tmp_path / "state"
        config_dir = tmp_path / "config"
        cache_dir.mkdir()
        data_dir.mkdir()
        state_dir.mkdir()
        config_dir.mkdir()

        # Create some orphans
        (cache_dir / "temp.tmp").write_text("temp")
        (data_dir / "file.txt~").write_text("backup")
        (state_dir / "broken").symlink_to("/nonexistent")

        with (
            mock.patch.object(config, "CACHE_DIR", str(cache_dir)),
            mock.patch.object(config, "DATA_DIR", str(data_dir)),
            mock.patch.object(config, "STATE_DIR", str(state_dir)),
            mock.patch.object(config, "CONFIG_DIR", str(config_dir)),
        ):
            count = _count_orphans_in_dirs()
            assert count == 3

    def test_no_orphans(self, tmp_path: Path):
        """Test counting when no orphans exist."""
        cache_dir = tmp_path / "cache"
        config_dir = tmp_path / "config"
        cache_dir.mkdir()
        config_dir.mkdir()

        with mock.patch.object(config, "CACHE_DIR", str(cache_dir)):
            with mock.patch.object(config, "DATA_DIR", str(cache_dir)):
                with mock.patch.object(config, "STATE_DIR", str(cache_dir)):
                    with mock.patch.object(config, "CONFIG_DIR", str(config_dir)):
                        count = _count_orphans_in_dirs()
                        assert count == 0

    def test_missing_directories(self):
        """Test counting when XDG directories don't exist."""
        with (
            mock.patch.object(config, "CACHE_DIR", "/nonexistent/cache"),
            mock.patch.object(config, "DATA_DIR", "/nonexistent/data"),
            mock.patch.object(config, "STATE_DIR", "/nonexistent/state"),
            mock.patch.object(config, "CONFIG_DIR", "/nonexistent/config"),
        ):
            count = _count_orphans_in_dirs()
            assert count == 0


class TestKnownFilesNotOrphans:
    """Tests for cost_tracker.json and motd.txt not being flagged as orphans."""

    def test_cost_tracker_json_not_orphan_in_data_dir(self, tmp_path: Path):
        """Test that cost_tracker.json in DATA_DIR is NOT flagged as orphan."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "cost_tracker.json").write_text('{"daily_cost_usd": 1.23}')

        orphans = _find_orphans(data_dir, known_files=_KNOWN_DATA_FILES)
        assert len(orphans) == 0

    def test_motd_txt_not_orphan_in_config_dir(self, tmp_path: Path):
        """Test that motd.txt in CONFIG_DIR is NOT flagged as orphan."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "motd.txt").write_text("2026-01-01\n")

        orphans = _find_orphans(config_dir, known_files=_KNOWN_CONFIG_FILES)
        assert len(orphans) == 0

    def test_cost_tracker_json_not_orphan_anywhere(self, tmp_path: Path):
        """Test that cost_tracker.json is never flagged as orphan (json is known extension)."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "cost_tracker.json").write_text('{"daily_cost_usd": 1.23}')

        # JSON files are in _KNOWN_EXTENSIONS, so never flagged as orphans by extension
        orphans = _find_orphans(cache_dir, known_files=set())
        assert len(orphans) == 0

    def test_motd_txt_not_orphan_anywhere(self, tmp_path: Path):
        """Test that motd.txt is never flagged as orphan (txt is known extension)."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "motd.txt").write_text("2026-01-01\n")

        # TXT files are in _KNOWN_EXTENSIONS, so never flagged as orphans by extension
        orphans = _find_orphans(cache_dir, known_files=set())
        assert len(orphans) == 0

    def test_unknown_extensions_still_flagged(self, tmp_path: Path):
        """Test that files with unknown extensions are still flagged as orphans."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "unknown_file.xyz").write_text("some data")

        orphans = _find_orphans(data_dir, known_files=_KNOWN_DATA_FILES)
        assert len(orphans) == 1
        assert orphans[0].name == "unknown_file.xyz"

    def test_known_files_list_is_used(self, tmp_path: Path):
        """Test that known_files parameter is used to filter out specific files."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Create a file that would be flagged (no known extension, but in known_files)
        (data_dir / "my_custom_file").write_text("some content")

        # Without known_files, this would be flagged as unknown extension (no extension)
        orphans = _find_orphans(data_dir, known_files={"my_custom_file"})
        assert len(orphans) == 0

        # Without the known_files entry, it would be flagged (files without extension)
        orphans = _find_orphans(data_dir, known_files=set())
        # Files without extensions are NOT flagged (empty ext check)
        assert len(orphans) == 0
