"""Tests for sandbox dangerous pattern blocking."""

from code_puppy.plugins.universal_constructor.sandbox import check_dangerous_patterns


def test_safe_code_passes():
    code = """
def greet(name: str) -> str:
    return f"Hello, {name}!"
"""
    result = check_dangerous_patterns(code)
    assert result.valid is True
    assert len(result.errors) == 0


def test_os_import_blocked():
    code = """
import os

def list_dir():
    return os.listdir(".")
"""
    result = check_dangerous_patterns(code)
    assert result.valid is False
    assert any("Dangerous patterns blocked" in e for e in result.errors)


def test_subprocess_import_blocked():
    code = """
import subprocess

def run_cmd(cmd):
    return subprocess.run(cmd, capture_output=True)
"""
    result = check_dangerous_patterns(code)
    assert result.valid is False
    assert any("subprocess" in e for e in result.errors)


def test_eval_call_blocked():
    code = """
def dangerous(expr):
    return eval(expr)
"""
    result = check_dangerous_patterns(code)
    assert result.valid is False
    assert any("eval" in e for e in result.errors)


def test_pickle_import_blocked():
    code = """
import pickle

def load_data(path):
    with open(path, "rb") as f:
        return pickle.load(f)
"""
    result = check_dangerous_patterns(code)
    assert result.valid is False
    assert any("pickle" in e for e in result.errors)


def test_from_import_blocked():
    code = """
from subprocess import run

def execute(cmd):
    return run(cmd)
"""
    result = check_dangerous_patterns(code)
    assert result.valid is False


def test_warnings_also_populated():
    """Errors AND warnings should both be present."""
    code = """
import os
def foo():
    pass
"""
    result = check_dangerous_patterns(code)
    assert result.valid is False
    assert len(result.errors) > 0
    assert len(result.warnings) > 0
