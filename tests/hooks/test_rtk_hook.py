"""Tests for the RTK (Rust Token Killer) default PreToolUse hook.

Uses a fake ``rtk`` binary (see ``fake_rtk.py``) so no real Rust binary is needed.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from kimi_cli.hooks import get_default_hooks
from kimi_cli.hooks.config import HookDef
from kimi_cli.hooks.engine import HookEngine

FAKE_RTK_SOURCE = Path(__file__).parent / "fake_rtk.py"


@pytest.fixture
def fake_rtk_dir(tmp_path: Path):
    """Create a temporary directory containing an executable ``rtk`` on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_rtk = bin_dir / "rtk"
    fake_rtk.write_text(FAKE_RTK_SOURCE.read_text(), encoding="utf-8")
    fake_rtk.chmod(0o755)

    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old_path}"
    yield bin_dir
    os.environ["PATH"] = old_path


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_rtk_default_hook_registered_when_rtk_available(fake_rtk_dir: Path):
    """When 'rtk' is on PATH, get_default_hooks() returns a PreToolUse Shell hook."""
    hooks = get_default_hooks()

    assert len(hooks) == 1
    h = hooks[0]
    assert isinstance(h, HookDef)
    assert h.event == "PreToolUse"
    assert h.matcher == "Shell"
    assert "rtk.py" in h.command
    assert h.timeout == 5


def test_rtk_default_hook_not_registered_when_rtk_missing():
    """When 'rtk' is absent, get_default_hooks() returns nothing."""
    with patch("kimi_cli.hooks.__init__.shutil.which", return_value=None):
        hooks = get_default_hooks()
    assert hooks == []


# ---------------------------------------------------------------------------
# rtk.py script (drives the real fake rtk binary)
# ---------------------------------------------------------------------------


def _invoke_rtk_main(stdin_data: dict):
    """Import and run rtk.main() with mocked stdin/stdout."""
    from kimi_cli.hooks.defaults import rtk

    old_stdin = sys.stdin
    old_stdout = sys.stdout
    captured = io.StringIO()
    try:
        sys.stdin = io.StringIO(json.dumps(stdin_data))
        sys.stdout = captured
        rtk.main()
        return captured.getvalue(), 0
    except SystemExit as exc:
        return captured.getvalue(), exc.code if isinstance(exc.code, int) else 0
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout


def test_rtk_script_rewrites_shell_command(fake_rtk_dir: Path):
    """rtk.py should output updatedInput when fake rtk returns exit 3."""
    stdout, rc = _invoke_rtk_main({"tool_name": "Shell", "tool_input": {"command": "ls -la"}})

    assert rc == 0
    assert stdout.strip()
    parsed = json.loads(stdout)
    assert parsed["hookSpecificOutput"]["updatedInput"]["command"] == "rtk ls -la"


def test_rtk_script_ignores_non_shell_tool(fake_rtk_dir: Path):
    """rtk.py should exit 0 with no output for non-Shell tools."""
    stdout, rc = _invoke_rtk_main({"tool_name": "ReadFile", "tool_input": {"path": "foo.txt"}})

    assert rc == 0
    assert stdout.strip() == ""


def test_rtk_script_fails_open_on_unsupported_command(fake_rtk_dir: Path):
    """If rtk rewrite exits 1 (unsupported), rtk.py should exit 0 and produce no output."""
    stdout, rc = _invoke_rtk_main({"tool_name": "Shell", "tool_input": {"command": "npm install"}})

    assert rc == 0
    assert stdout.strip() == ""


def test_rtk_script_fails_open_on_rtk_error():
    """If rtk rewrite exits with an unexpected code (e.g. 2), rtk.py should exit 0."""
    with patch("kimi_cli.hooks.defaults.rtk.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["rtk", "rewrite", "echo hello"],
            returncode=2,
            stdout="",
            stderr="rtk error",
        )
        stdout, rc = _invoke_rtk_main(
            {"tool_name": "Shell", "tool_input": {"command": "echo hello"}}
        )

    assert rc == 0
    assert stdout.strip() == ""


# ---------------------------------------------------------------------------
# Integration: HookEngine with the real rtk.py + fake rtk binary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rtk_hook_execution_in_engine(fake_rtk_dir: Path):
    """HookEngine triggers the default RTK hook and receives updatedInput."""
    hooks = get_default_hooks()
    engine = HookEngine(hooks, include_defaults=False)

    results = await engine.trigger(
        "PreToolUse",
        matcher_value="Shell",
        input_data={"tool_name": "Shell", "tool_input": {"command": "ls -la"}},
    )

    assert len(results) == 1
    assert results[0].action == "allow"
    assert results[0].updated_input is not None
    assert results[0].updated_input.get("command") == "rtk ls -la"


@pytest.mark.asyncio
async def test_rtk_hook_not_loaded_when_rtk_missing():
    """When rtk is absent, HookEngine has no default RTK hook to trigger."""
    with patch("kimi_cli.hooks.__init__.shutil.which", return_value=None):
        engine = HookEngine([], include_defaults=True)

    results = await engine.trigger(
        "PreToolUse",
        matcher_value="Shell",
        input_data={"tool_name": "Shell", "tool_input": {"command": "ls"}},
    )
    assert results == []
