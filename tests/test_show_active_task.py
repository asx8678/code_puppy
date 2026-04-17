"""Tests for show-active-task.sh — source accuracy and project-type consistency.

Covers the critic-blocking items:
  - source is ``env/git`` when PUP_TASK_ID is set but ``bd show`` fails
  - source is ``bd`` when bd data is actually returned
  - project-type consistency for a Java marker (pom.xml) between JSON and text
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "code_puppy"
    / "plugins"
    / "proactive_guidance"
    / "show-active-task.sh"
)


@pytest.fixture()
def tmp_git_repo(tmp_path: Path):
    """Create a temporary git repo so the script doesn't fail on git commands.

    Configures a local user.name/user.email so commits work without any
    global git identity — keeps the test hermetic on bare CI runners.
    """
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    # Hermetic: set identity locally (not global) so commits never depend
    # on the runner's ~/.gitconfig.
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    return tmp_path


def _run_script(
    repo: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the shell script in *repo* with optional extra env vars."""
    env = dict(os.environ)
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=env,
        timeout=15,
    )


# ---------------------------------------------------------------------------
# Source accuracy
# ---------------------------------------------------------------------------


class TestSourceAccuracy:
    """Verify that tasks.source reflects the actual data source."""

    def test_source_env_git_when_bd_show_fails(self, tmp_git_repo: Path):
        """source must be 'env/git' when PUP_TASK_ID is set but bd show fails."""
        # bd-999999 almost certainly doesn't exist
        result = _run_script(tmp_git_repo, {"PUP_TASK_ID": "bd-999999"})
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["tasks"]["source"] == "env/git", (
            "source should be 'env/git' when bd show fails, "
            f"got: {data['tasks']['source']!r}"
        )

    def test_source_bd_when_bd_returns_data(self, tmp_git_repo: Path):
        """source must be 'bd' when bd show actually returns data.

        Runs in the actual project dir (which has .bd configured) to ensure
        bd can resolve the issue.
        """
        # First check that bd show actually works for bd-136
        probe = subprocess.run(
            ["bd", "show", "bd-136"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(SCRIPT.parent.parent.parent.parent),  # project root
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            pytest.skip("bd-136 not available in this environment")

        # Run in the actual project root so bd can find .bd/
        project_root = str(SCRIPT.parent.parent.parent.parent)
        env = dict(os.environ, PUP_TASK_ID="bd-136")
        result = subprocess.run(
            ["bash", str(SCRIPT), "--json"],
            capture_output=True,
            text=True,
            cwd=project_root,
            env=env,
            timeout=15,
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["tasks"]["source"] == "bd", (
            "source should be 'bd' when bd show succeeds, "
            f"got: {data['tasks']['source']!r}"
        )


# ---------------------------------------------------------------------------
# Project-type consistency
# ---------------------------------------------------------------------------


class TestProjectTypeConsistency:
    """Verify JSON and text modes report the same project type."""

    def test_java_project_type_json_vs_text(self, tmp_git_repo: Path):
        """Both JSON and text must agree on 'java' for a pom.xml project."""
        # Create a Java marker file
        (tmp_git_repo / "pom.xml").write_text("<project></project>\n")

        # JSON output
        json_result = subprocess.run(
            ["bash", str(SCRIPT), "--json"],
            capture_output=True,
            text=True,
            cwd=str(tmp_git_repo),
            timeout=15,
        )
        assert json_result.returncode == 0, f"JSON mode failed: {json_result.stderr}"
        data = json.loads(json_result.stdout)
        json_type = data["project"]["type"]

        # Text output
        text_result = subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            cwd=str(tmp_git_repo),
            timeout=15,
        )
        assert text_result.returncode == 0, f"Text mode failed: {text_result.stderr}"
        # Extract the "Type:" line from text output
        type_line = ""
        for line in text_result.stdout.splitlines():
            if "Type:" in line:
                type_line = line.strip()
                break
        assert type_line, (
            f"Could not find 'Type:' line in text output:\n{text_result.stdout}"
        )

        # Both should report Java
        assert json_type == "java", (
            f"JSON project type should be 'java', got {json_type!r}"
        )
        assert "Java" in type_line, (
            f"Text type line should contain 'Java', got: {type_line!r}"
        )

    @pytest.mark.parametrize(
        "marker_file,expected_json_type,expected_text_label",
        [
            ("pyproject.toml", "python", "Python"),
            ("package.json", "nodejs", "Node.js"),
            ("Cargo.toml", "rust", "Rust"),
            ("go.mod", "go", "Go"),
            ("CMakeLists.txt", "c/c++", "C/C++"),
        ],
    )
    def test_project_type_variants(
        self,
        tmp_git_repo: Path,
        marker_file: str,
        expected_json_type: str,
        expected_text_label: str,
    ):
        """Parametrized check that JSON and text modes agree on project type."""
        (tmp_git_repo / marker_file).write_text("")

        json_result = subprocess.run(
            ["bash", str(SCRIPT), "--json"],
            capture_output=True,
            text=True,
            cwd=str(tmp_git_repo),
            timeout=15,
        )
        assert json_result.returncode == 0
        data = json.loads(json_result.stdout)
        assert data["project"]["type"] == expected_json_type

        text_result = subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            cwd=str(tmp_git_repo),
            timeout=15,
        )
        assert text_result.returncode == 0
        type_lines = [
            line for line in text_result.stdout.splitlines() if "Type:" in line
        ]
        assert type_lines, "No 'Type:' line found in text output"
        assert expected_text_label in type_lines[0]


# ---------------------------------------------------------------------------
# JSON escaping for dynamic values (regression tests)
# ---------------------------------------------------------------------------


def _make_bd_script(tmp_path: Path, title: str) -> Path:
    """Create a fake ``bd`` wrapper that returns a crafted Title line.

    This lets us test special-character titles without needing a real bd issue.
    The title is persisted to a sidecar file so the script can output it
    faithfully without bash quoting pitfalls.
    """
    title_file = tmp_path / "_bd_title.txt"
    title_file.write_text(f"Title: {title}")
    bd_fake = tmp_path / "bd"
    bd_fake.write_text(
        "#!/usr/bin/env bash\n"
        'echo "Issue: $1"\n'
        f'cat "{title_file}"\n'
        'echo ""\n'
        'echo "Status: open"\n'
    )
    bd_fake.chmod(0o755)
    return bd_fake


class TestJsonEscaping:
    """Regression tests — dynamic values must produce valid, decodable JSON.

    Covers the critic item: quoted / special-character task titles in --json.
    """

    @pytest.mark.parametrize(
        "title",
        [
            "Simple task",
            'Fix "the" bug',
            "It's a test",
            "Task with a slash /",
            "Task with backslash \\",
        ],
        ids=[
            "plain",
            "double-quotes",
            "single-quote",
            "slash",
            "backslash",
        ],
    )
    def test_special_title_produces_valid_json(self, tmp_git_repo: Path, title: str):
        """show-active-task.sh --json must emit valid JSON even with tricky titles."""
        bd_fake = _make_bd_script(tmp_git_repo, title)
        env = dict(
            os.environ,
            PUP_TASK_ID="bd-1",
            PATH=f"{bd_fake.parent}:{os.environ['PATH']}",
        )
        result = subprocess.run(
            ["bash", str(SCRIPT), "--json"],
            capture_output=True,
            text=True,
            cwd=str(tmp_git_repo),
            env=env,
            timeout=15,
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        data = json.loads(result.stdout)  # must not raise
        assert data["tasks"]["current_task"]["id"] == "bd-1"
        # The title in the JSON must round-trip cleanly
        assert data["tasks"]["current_task"]["name"] == title
        assert data["tasks"]["source"] == "bd"

    def test_special_title_backslash_in_json(self, tmp_git_repo: Path):
        """Regression: backslash in title must not corrupt JSON structure."""
        title = "C:\\Users\\test"
        bd_fake = _make_bd_script(tmp_git_repo, title)
        env = dict(
            os.environ,
            PUP_TASK_ID="bd-2",
            PATH=f"{bd_fake.parent}:{os.environ['PATH']}",
        )
        result = subprocess.run(
            ["bash", str(SCRIPT), "--json"],
            capture_output=True,
            text=True,
            cwd=str(tmp_git_repo),
            env=env,
            timeout=15,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["tasks"]["current_task"]["name"] == title


# ---------------------------------------------------------------------------
# Env-var normalization for plugin.enabled / plugin.guidance_count
# Regression tests — bd-136 Shepherd blocker
# ---------------------------------------------------------------------------


class TestEnvVarNormalization:
    """Verify that --json normalizes env-var values to strict JSON types.

    Previously ``PUP_GUIDANCE_ENABLED=yes`` would emit bare ``yes`` (invalid
    JSON) and ``PUP_GUIDANCE_COUNT=abc`` would emit bare ``abc`` (also invalid).
    The ``normalize_bool`` and ``normalize_int`` helpers must prevent this.
    """

    # --- enabled (boolean) ---------------------------------------------------

    @pytest.mark.parametrize(
        "env_val,expected",
        [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("YES", True),
            ("on", True),
            ("ON", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("0", False),
            ("no", False),
            ("NO", False),
            ("off", False),
            ("OFF", False),
        ],
        ids=lambda v: str(v),
    )
    def test_enabled_known_truthy_falsy(
        self, tmp_git_repo: Path, env_val: str, expected: bool
    ):
        """Recognised boolean-ish strings must produce strict JSON bools."""
        result = _run_script(tmp_git_repo, {"PUP_GUIDANCE_ENABLED": env_val})
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["plugin"]["enabled"] is expected, (
            f"PUP_GUIDANCE_ENABLED={env_val!r} → expected {expected}, "
            f"got {data['plugin']['enabled']!r}"
        )

    @pytest.mark.parametrize(
        "env_val",
        ["maybe", "sure", "2", "enabled", "random"],
        ids=lambda v: v,
    )
    def test_enabled_unrecognised_falls_back_to_true(
        self, tmp_git_repo: Path, env_val: str
    ):
        """Unrecognised values must fall back to the default (true)."""
        result = _run_script(tmp_git_repo, {"PUP_GUIDANCE_ENABLED": env_val})
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["plugin"]["enabled"] is True, (
            f"PUP_GUIDANCE_ENABLED={env_val!r} → expected True (fallback), "
            f"got {data['plugin']['enabled']!r}"
        )

    def test_enabled_empty_defaults_to_true(self, tmp_git_repo: Path):
        """Empty/missing PUP_GUIDANCE_ENABLED must default to true."""
        result = _run_script(tmp_git_repo, {"PUP_GUIDANCE_ENABLED": ""})
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["plugin"]["enabled"] is True

    def test_enabled_puppy_legacy_var(self, tmp_git_repo: Path):
        """PUPPY_GUIDANCE_ENABLED (legacy) must also be normalised."""
        env = {"PUPPY_GUIDANCE_ENABLED": "no"}
        # Ensure PUP_ variant is NOT set so legacy is used
        env["PUP_GUIDANCE_ENABLED"] = ""
        result = _run_script(tmp_git_repo, env)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["plugin"]["enabled"] is False

    # --- guidance_count (integer) -------------------------------------------

    @pytest.mark.parametrize(
        "env_val,expected",
        [
            ("0", 0),
            ("1", 1),
            ("42", 42),
            ("999", 999),
        ],
        ids=lambda v: str(v),
    )
    def test_count_valid_integer(self, tmp_git_repo: Path, env_val: str, expected: int):
        """Valid integer strings must parse cleanly."""
        result = _run_script(tmp_git_repo, {"PUP_GUIDANCE_COUNT": env_val})
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["plugin"]["guidance_count"] == expected, (
            f"PUP_GUIDANCE_COUNT={env_val!r} → expected {expected}, "
            f"got {data['plugin']['guidance_count']!r}"
        )

    @pytest.mark.parametrize(
        "env_val",
        ["abc", "twelve", "!@#", "  ", "--"],
        ids=lambda v: repr(v),
    )
    def test_count_invalid_falls_back_to_zero(self, tmp_git_repo: Path, env_val: str):
        """Non-numeric values must fall back to 0 (safe default)."""
        result = _run_script(tmp_git_repo, {"PUP_GUIDANCE_COUNT": env_val})
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["plugin"]["guidance_count"] == 0, (
            f"PUP_GUIDANCE_COUNT={env_val!r} → expected 0 (fallback), "
            f"got {data['plugin']['guidance_count']!r}"
        )

    def test_count_empty_defaults_to_zero(self, tmp_git_repo: Path):
        """Empty/missing PUP_GUIDANCE_COUNT must default to 0."""
        result = _run_script(tmp_git_repo, {"PUP_GUIDANCE_COUNT": ""})
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["plugin"]["guidance_count"] == 0

    def test_count_strips_leading_zeros(self, tmp_git_repo: Path):
        """Leading zeros (e.g. '007') must not produce octal-like output."""
        result = _run_script(tmp_git_repo, {"PUP_GUIDANCE_COUNT": "007"})
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["plugin"]["guidance_count"] == 7

    def test_count_puppy_legacy_var(self, tmp_git_repo: Path):
        """PUPPY_GUIDANCE_COUNT (legacy) must also be normalised."""
        env = {"PUPPY_GUIDANCE_COUNT": "15"}
        env["PUP_GUIDANCE_COUNT"] = ""
        result = _run_script(tmp_git_repo, env)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["plugin"]["guidance_count"] == 15

    # --- combined: both invalid at once -------------------------------------

    def test_both_invalid_produces_valid_json(self, tmp_git_repo: Path):
        """When both env vars are garbage, --json must still emit valid JSON."""
        result = _run_script(
            tmp_git_repo,
            {"PUP_GUIDANCE_ENABLED": "yes", "PUP_GUIDANCE_COUNT": "abc"},
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)  # must not raise
        assert data["plugin"]["enabled"] is True
        assert data["plugin"]["guidance_count"] == 0
