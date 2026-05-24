"""Tests for Claude Code-compatible marketplace support."""

import json
from pathlib import Path

import pytest

from kimi_cli.marketplace import (
    MarketplaceError,
    PluginSource,
    load_marketplace_registry,
    parse_claude_plugin_json,
    parse_marketplace_json,
    save_marketplace_registry,
)
from kimi_cli.marketplace.installer import install_plugin_skills, validate_plugin


class TestMarketplaceModels:
    def test_parse_marketplace_json(self, tmp_path: Path) -> None:
        marketplace_json = tmp_path / "marketplace.json"
        marketplace_json.write_text(
            json.dumps(
                {
                    "name": "test-marketplace",
                    "owner": {"name": "Test Owner", "email": "test@example.com"},
                    "metadata": {"description": "A test marketplace", "pluginRoot": "./plugins"},
                    "plugins": [
                        {
                            "name": "plugin-a",
                            "source": "./plugins/plugin-a",
                            "description": "Plugin A",
                            "version": "1.0.0",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        spec = parse_marketplace_json(marketplace_json)
        assert spec.name == "test-marketplace"
        assert spec.owner is not None
        assert spec.owner.name == "Test Owner"
        assert spec.metadata is not None
        assert spec.metadata.pluginRoot == "./plugins"
        assert len(spec.plugins) == 1
        assert spec.plugins[0].name == "plugin-a"

    def test_parse_marketplace_json_github_source(self, tmp_path: Path) -> None:
        marketplace_json = tmp_path / "marketplace.json"
        marketplace_json.write_text(
            json.dumps(
                {
                    "name": "test-marketplace",
                    "plugins": [
                        {
                            "name": "plugin-b",
                            "source": {"source": "github", "repo": "owner/repo"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        spec = parse_marketplace_json(marketplace_json)
        resolved = spec.plugins[0].resolved_source()
        assert resolved.source == "github"
        assert resolved.repo == "owner/repo"
        assert resolved.to_url() == "https://github.com/owner/repo.git"

    def test_parse_invalid_marketplace_json(self, tmp_path: Path) -> None:
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("not json", encoding="utf-8")
        with pytest.raises(MarketplaceError):
            parse_marketplace_json(bad_json)


class TestPluginModels:
    def test_parse_claude_plugin_json(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / ".claude-plugin"
        plugin_dir.mkdir()
        plugin_json = plugin_dir / "plugin.json"
        plugin_json.write_text(
            json.dumps(
                {
                    "name": "my-plugin",
                    "version": "1.0.0",
                    "description": "A test plugin",
                    "skills": "./skills",
                    "mcpServers": "./mcp.json",
                }
            ),
            encoding="utf-8",
        )

        spec = parse_claude_plugin_json(plugin_json)
        assert spec.name == "my-plugin"
        assert spec.skills == "./skills"
        assert spec.mcpServers == "./mcp.json"


class TestPluginSource:
    def test_from_string(self) -> None:
        src = PluginSource.from_value("./local/path")
        assert src.source == "directory"
        assert src.path == "./local/path"

    def test_from_github_dict(self) -> None:
        src = PluginSource.from_value({"source": "github", "repo": "owner/repo"})
        assert src.source == "github"
        assert src.repo == "owner/repo"
        assert src.to_url() == "https://github.com/owner/repo.git"

    def test_from_git_dict(self) -> None:
        src = PluginSource.from_value({"source": "git", "url": "https://gitlab.com/a/b.git"})
        assert src.source == "git"
        assert src.url == "https://gitlab.com/a/b.git"


class TestMarketplaceRegistry:
    def test_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        registry_path = tmp_path / "marketplaces.json"
        monkeypatch.setattr(
            "kimi_cli.marketplace.get_marketplace_registry_path", lambda: registry_path
        )

        save_marketplace_registry({"foo": "https://github.com/foo/bar"})
        loaded = load_marketplace_registry()
        assert loaded == {"foo": "https://github.com/foo/bar"}

    def test_load_missing_registry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        registry_path = tmp_path / "marketplaces.json"
        monkeypatch.setattr(
            "kimi_cli.marketplace.get_marketplace_registry_path", lambda: registry_path
        )

        loaded = load_marketplace_registry()
        assert loaded == {}


class TestInstallPluginSkills:
    def test_install_skills(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        share_dir = tmp_path / "share"
        monkeypatch.setattr("kimi_cli.marketplace.installer.get_share_dir", lambda: share_dir)

        plugin_dir = tmp_path / "plugin"
        skills_dir = plugin_dir / "skills"
        skill_dir = skills_dir / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: A test skill\n---\n\n# Test\n",
            encoding="utf-8",
        )

        installed, mcp = install_plugin_skills(
            plugin_dir, plugin_name="my-plugin", marketplace_name="mp"
        )
        assert installed == ["my-plugin--test-skill"]
        assert mcp is None

        target = share_dir / "skills" / "mp-my-plugin" / "test-skill" / "SKILL.md"
        assert target.exists()

        # Verify frontmatter was rewritten with prefixed name
        text = target.read_text(encoding="utf-8")
        assert "name: my-plugin--test-skill" in text

    def test_install_skills_from_plugin_json_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        share_dir = tmp_path / "share"
        monkeypatch.setattr("kimi_cli.marketplace.installer.get_share_dir", lambda: share_dir)

        plugin_dir = tmp_path / "plugin"
        custom_skills = plugin_dir / "custom" / "skills"
        skill_dir = custom_skills / "custom-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: custom-skill\ndescription: Custom\n---\n",
            encoding="utf-8",
        )

        plugin_json_dir = plugin_dir / ".claude-plugin"
        plugin_json_dir.mkdir()
        (plugin_json_dir / "plugin.json").write_text(
            json.dumps({"name": "my-plugin", "skills": "./custom/skills"}),
            encoding="utf-8",
        )

        installed, _ = install_plugin_skills(plugin_dir, plugin_name="my-plugin")
        assert "my-plugin--custom-skill" in installed

    def test_no_skills_found(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        with pytest.raises(MarketplaceError):
            install_plugin_skills(plugin_dir, plugin_name="empty-plugin")


class TestValidatePlugin:
    def test_validate_with_skills_only(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "plugin"
        skills_dir = plugin_dir / "skills"
        (skills_dir / "skill-a").mkdir(parents=True)
        (skills_dir / "skill-a" / "SKILL.md").write_text(
            "---\nname: skill-a\n---\n", encoding="utf-8"
        )
        (skills_dir / "skill-b").mkdir(parents=True)
        (skills_dir / "skill-b" / "SKILL.md").write_text(
            "---\nname: skill-b\n---\n", encoding="utf-8"
        )

        report = validate_plugin(plugin_dir, "my-plugin")
        assert report.plugin_name == "my-plugin"
        assert report.skills == ["skill-a", "skill-b"]
        assert not report.has_unsupported()

    def test_validate_with_unsupported(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "plugin"
        (plugin_dir / "skills" / "s1").mkdir(parents=True)
        (plugin_dir / "skills" / "s1" / "SKILL.md").write_text("---\nname: s1\n---\n")
        (plugin_dir / "commands").mkdir(parents=True, exist_ok=True)
        (plugin_dir / "commands" / "cmd.md").write_text("# cmd", encoding="utf-8")
        (plugin_dir / "agents").mkdir(parents=True, exist_ok=True)
        (plugin_dir / "agents" / "agent.md").write_text("---\nname: a\n---\n", encoding="utf-8")
        (plugin_dir / "hooks").mkdir(parents=True, exist_ok=True)
        (plugin_dir / "hooks" / "hooks.json").write_text("{}", encoding="utf-8")

        report = validate_plugin(plugin_dir, "my-plugin")
        assert report.skills == ["s1"]
        assert report.commands == ["cmd.md"]
        assert report.agents == ["agent.md"]
        assert report.hooks == ["hooks.json"]
        assert report.has_unsupported()

    def test_validate_summary(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "plugin"
        (plugin_dir / "skills" / "s1").mkdir(parents=True)
        (plugin_dir / "skills" / "s1" / "SKILL.md").write_text("---\nname: s1\n---\n")

        report = validate_plugin(plugin_dir, "my-plugin")
        summary = report.summary()
        assert "Plugin: my-plugin" in summary
        assert "Skills: 1" in summary
        assert "s1" in summary
