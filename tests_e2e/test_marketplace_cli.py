"""E2E tests for ``kimi marketplace`` CLI commands.

Tests use a synthetic plugin structure inspired by official Claude Code plugins
(frontend-design, commit-commands, etc.) to verify end-to-end installation,
validation, and registry behaviour.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from inline_snapshot import snapshot

from tests_e2e.wire_helpers import (
    make_env,
    make_home_dir,
    normalize_value,
    repo_root,
    share_dir,
)


def _run_cli(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # Use ``uv run bhu`` so the test always exercises the current source tree
    # instead of a possibly-stale ``kimi`` binary in the user's PATH.
    cmd = ["uv", "run", "bhu"] + args
    return subprocess.run(
        cmd,
        cwd=repo_root(),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
    )


def _make_official_style_plugin(plugin_dir: Path) -> None:
    """Create a synthetic plugin that mirrors official Claude Code plugins."""
    # plugin.json — inspired by frontend-design / commit-commands
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "demo-plugin",
                "version": "1.0.0",
                "description": "A demo plugin inspired by official Claude Code plugins",
                "author": {"name": "Anthropic", "email": "support@anthropic.com"},
            }
        ),
        encoding="utf-8",
    )

    # Skills — inspired by frontend-design
    skills_dir = plugin_dir / "skills" / "frontend-design"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "---\n"
        "name: frontend-design\n"
        "description: Create distinctive, production-grade frontend interfaces\n"
        "license: MIT\n"
        "---\n\n"
        "## Design Thinking\n\n"
        "Before coding, understand the context and commit to a BOLD aesthetic direction.\n",
        encoding="utf-8",
    )

    # Commands — inspired by commit-commands
    commands_dir = plugin_dir / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "commit.md").write_text(
        "---\ndescription: Create a git commit\n---\n\n"
        "## Your task\n\n"
        "Based on the changes, create a single git commit.\n",
        encoding="utf-8",
    )
    (commands_dir / "review.md").write_text(
        "---\ndescription: Review a pull request\n---\n\n"
        "## Your task\n\n"
        "Provide a code review for the given pull request.\n",
        encoding="utf-8",
    )

    # MCP servers — inspired by chrome-devtools-mcp
    (plugin_dir / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_marketplace_install_validates_and_installs(tmp_path: Path) -> None:
    """Install a plugin directly from a local directory."""
    home_dir = make_home_dir(tmp_path)
    env = make_env(home_dir)

    plugin_dir = tmp_path / "demo-plugin"
    _make_official_style_plugin(plugin_dir)

    result = _run_cli(
        ["marketplace", "install", str(plugin_dir), "--yes"],
        env,
    )
    assert result.returncode == 0, result.stderr
    normalized = normalize_value(result.stdout)
    assert normalized == snapshot(
        "Plugin: demo-plugin v1.0.0\n"
        "  A demo plugin inspired by official Claude Code plugins\n"
        "\n"
        "  ✅ Skills: 1\n"
        "      - frontend-design\n"
        "  ✅ Commands: 2\n"
        "      - commit.md\n"
        "      - review.md\n"
        "  ✅ MCP Servers: 1\n"
        "      - .mcp.json\n"
        "\n"
        "Installed 1 skill(s):\n"
        "  - demo-plugin--frontend-design\n"
        "\n"
        "Registered MCP server(s) from 'demo-plugin':\n"
        "  - demo-plugin--filesystem\n"
        "\n"
        "Installed 2 command(s):\n"
        "  - commit\n"
        "  - review\n"
    )

    # Verify skills landed in ~/.kimi/skills/
    skills_target = share_dir(home_dir) / "skills" / "demo-plugin"
    assert skills_target.is_dir()
    skill_md = skills_target / "frontend-design" / "SKILL.md"
    assert skill_md.exists()
    assert "name: demo-plugin--frontend-design" in skill_md.read_text(encoding="utf-8")

    # Verify commands landed in ~/.kimi/commands/
    commands_dir = share_dir(home_dir) / "commands"
    assert (commands_dir / "commit.md").exists()
    assert (commands_dir / "review.md").exists()

    # Verify MCP servers landed in plugin-mcp.json
    plugin_mcp = share_dir(home_dir) / "plugin-mcp.json"
    assert plugin_mcp.exists()
    mcp_data = json.loads(plugin_mcp.read_text(encoding="utf-8"))
    assert mcp_data == snapshot(
        {
            "mcpServers": {
                "demo-plugin--filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                    "env": {},
                    "transport": "stdio",
                }
            }
        }
    )


def test_marketplace_add_and_list(tmp_path: Path) -> None:
    """Add a marketplace from a local directory and list it."""
    home_dir = make_home_dir(tmp_path)
    env = make_env(home_dir)

    marketplace_dir = tmp_path / "official-marketplace"
    marketplace_dir.mkdir()
    (marketplace_dir / ".claude-plugin").mkdir()
    (marketplace_dir / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "official-marketplace",
                "plugins": [
                    {
                        "name": "frontend-design",
                        "description": "Frontend design skill",
                        "source": "./plugins/frontend-design",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run_cli(["marketplace", "add", str(marketplace_dir)], env)
    assert result.returncode == 0, result.stderr
    assert "Added marketplace 'official-marketplace'" in result.stdout

    result = _run_cli(["marketplace", "list"], env)
    assert result.returncode == 0, result.stderr
    normalized = normalize_value(result.stdout)
    assert normalized == snapshot(
        "official-marketplace\n"
        "  Status:   cached\n"
        "  Plugins:  1 plugin(s)\n"
        "  Source:   <tmp>/official-marketplace\n"
        "  Inspect:  bhu marketplace list official-marketplace\n"
    )


def test_marketplace_remove_clears_cache(tmp_path: Path) -> None:
    """Remove a marketplace and verify cache is gone."""
    home_dir = make_home_dir(tmp_path)
    env = make_env(home_dir)

    marketplace_dir = tmp_path / "tmp-marketplace"
    marketplace_dir.mkdir()
    (marketplace_dir / ".claude-plugin").mkdir()
    (marketplace_dir / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "tmp-marketplace", "plugins": []}),
        encoding="utf-8",
    )

    _run_cli(["marketplace", "add", str(marketplace_dir)], env)

    result = _run_cli(["marketplace", "remove", "tmp-marketplace"], env)
    assert result.returncode == 0, result.stderr
    assert "Removed marketplace 'tmp-marketplace'" in result.stdout

    cache = share_dir(home_dir) / "marketplaces" / "tmp-marketplace"
    assert not cache.exists()
