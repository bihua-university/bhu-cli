"""Install Claude Code plugin components into bhu-cli."""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from kimi_cli import logger
from kimi_cli.marketplace import (
    MarketplaceError,
    get_share_dir,
    parse_claude_plugin_json,
)
from kimi_cli.utils.frontmatter import parse_frontmatter, strip_frontmatter


@dataclass
class PluginValidationReport:
    """Report of what a plugin contains and what bhu-cli can use."""

    plugin_name: str
    version: str | None = None
    description: str | None = None

    skills: list[str] = field(default_factory=list[str])
    commands: list[str] = field(default_factory=list[str])
    agents: list[str] = field(default_factory=list[str])
    hooks: list[str] = field(default_factory=list[str])
    mcp_servers: list[str] = field(default_factory=list[str])
    lsp_servers: list[str] = field(default_factory=list[str])
    output_styles: list[str] = field(default_factory=list[str])
    monitors: list[str] = field(default_factory=list[str])

    def has_unsupported(self) -> bool:
        return any(
            [
                self.agents,
                self.hooks,
                self.lsp_servers,
                self.output_styles,
                self.monitors,
            ]
        )

    def summary(self) -> str:
        lines: list[str] = [f"Plugin: {self.plugin_name}"]
        if self.version:
            lines[-1] += f" v{self.version}"
        if self.description:
            lines.append(f"  {self.description}")
        lines.append("")

        def _item(label: str, items: list[str], icon: str) -> None:
            if items:
                lines.append(f"  {icon} {label}: {len(items)}")
                for item in items:
                    lines.append(f"      - {item}")

        _item("Skills", self.skills, "✅")
        _item("Commands", self.commands, "✅")
        _item("Agents", self.agents, "❌")
        _item("Hooks", self.hooks, "❌")
        _item("MCP Servers", self.mcp_servers, "✅")
        _item("LSP Servers", self.lsp_servers, "❌")
        _item("Output Styles", self.output_styles, "❌")
        _item("Monitors", self.monitors, "❌")

        if self.has_unsupported():
            lines.append("")
            lines.append("  Unsupported components will be ignored.")
        return "\n".join(lines)


def _find_skills_dir(plugin_dir: Path, spec_skills: str | list[str] | None) -> Path | None:
    """Locate the skills directory inside a plugin."""
    if spec_skills is not None:
        paths: list[str] = [spec_skills] if isinstance(spec_skills, str) else spec_skills
        for p in paths:
            candidate = (plugin_dir / p).resolve()
            if candidate.is_dir() and candidate.is_relative_to(plugin_dir.resolve()):
                return candidate
        return None

    default = plugin_dir / "skills"
    if default.is_dir():
        return default
    return None


def validate_plugin(plugin_dir: Path, plugin_name: str) -> PluginValidationReport:
    """Scan a Claude Code plugin and report what bhu-cli can and cannot use."""
    plugin_json = plugin_dir / ".claude-plugin" / "plugin.json"
    if not plugin_json.exists():
        plugin_json = plugin_dir / "plugin.json"

    spec: dict[str, object] = {}
    if plugin_json.exists():
        try:
            parsed = parse_claude_plugin_json(plugin_json)
            spec = parsed.model_dump(exclude_none=True)
        except MarketplaceError:
            pass

    report = PluginValidationReport(
        plugin_name=spec.get("name", plugin_name),  # type: ignore[arg-type]
        version=spec.get("version"),  # type: ignore[arg-type]
        description=spec.get("description"),  # type: ignore[arg-type]
    )

    # Skills (supported)
    skills_dir = _find_skills_dir(plugin_dir, spec.get("skills"))  # type: ignore[arg-type]
    if skills_dir is not None and skills_dir.is_dir():
        report.skills = sorted(
            p.name for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()
        )

    # Helper to resolve a component path from spec or default
    def _resolve(spec_field: str | list[str] | None, default_name: str) -> Path | None:
        if spec_field is not None:
            paths: list[str] = [spec_field] if isinstance(spec_field, str) else spec_field
            for p in paths:
                candidate = (plugin_dir / p).resolve()
                if candidate.exists() and candidate.is_relative_to(plugin_dir.resolve()):
                    return candidate
            return None
        default = plugin_dir / default_name
        return default if default.exists() else None

    # Helper to list items in a component path
    def _items(path: Path | None) -> list[str]:
        if path is None:
            return []
        if path.is_dir():
            return sorted(p.name for p in path.iterdir() if not p.name.startswith("."))
        if path.is_file():
            return [path.name]
        return []

    report.commands = _items(_resolve(spec.get("commands"), "commands"))  # type: ignore[arg-type]
    report.agents = _items(_resolve(spec.get("agents"), "agents"))  # type: ignore[arg-type]
    report.hooks = _items(_resolve(spec.get("hooks"), "hooks"))  # type: ignore[arg-type]

    # MCP servers
    spec_mcp: str | None = spec.get("mcpServers")  # type: ignore[assignment]
    mcp_path: Path | None = None
    if spec_mcp is not None:
        candidate = (plugin_dir / spec_mcp).resolve()
        if candidate.is_file() and candidate.is_relative_to(plugin_dir.resolve()):
            mcp_path = candidate
    else:
        for mcp_name in ("mcp-servers.json", "mcp.json", ".mcp.json"):
            candidate = plugin_dir / mcp_name
            if candidate.is_file():
                mcp_path = candidate
                break
    if mcp_path is not None:
        report.mcp_servers = [mcp_path.name]

    for _field, _default_dir, _target in [
        ("lspServers", "lsp-servers", "lsp_servers"),
        ("outputStyles", "output-styles", "output_styles"),
        ("monitors", "monitors", "monitors"),
    ]:
        getattr(report, _target).extend(_items(_resolve(spec.get(_field), _default_dir)))  # type: ignore[arg-type]

    return report


def install_plugin_commands(
    plugin_dir: Path,
    plugin_name: str,
    marketplace_name: str | None = None,
) -> list[str]:
    """Extract commands from a Claude Code plugin into bhu-cli's commands directory.

    Commands are markdown files with frontmatter, installed as flat ``.md`` skills
    under ``~/.kimi/commands/``.  Each command name is prefixed with the plugin
    name to avoid collisions.

    Returns the list of installed command names.
    """
    plugin_json = plugin_dir / ".claude-plugin" / "plugin.json"
    if not plugin_json.exists():
        plugin_json = plugin_dir / "plugin.json"

    spec_commands: str | list[str] | None = None
    if plugin_json.exists():
        try:
            spec = parse_claude_plugin_json(plugin_json)
            spec_commands = spec.commands
            if spec.name:
                plugin_name = spec.name
        except MarketplaceError:
            pass

    commands_dir: Path | None = None
    if spec_commands is not None:
        paths: list[str] = [spec_commands] if isinstance(spec_commands, str) else spec_commands
        for p in paths:
            candidate = (plugin_dir / p).resolve()
            if candidate.is_dir() and candidate.is_relative_to(plugin_dir.resolve()):
                commands_dir = candidate
                break
    else:
        default = plugin_dir / "commands"
        if default.is_dir():
            commands_dir = default

    if commands_dir is None:
        return []

    target_dir = get_share_dir() / "commands"
    target_dir.mkdir(parents=True, exist_ok=True)

    installed: list[str] = []
    for cmd_file in commands_dir.iterdir():
        if not cmd_file.is_file() or not cmd_file.name.lower().endswith(".md"):
            continue

        original_name = cmd_file.stem
        content = cmd_file.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(content)

        # Use the original name when there is no collision; fall back to a
        # prefixed name when another plugin already owns the command.
        plain_target = target_dir / f"{original_name}.md"
        new_name = f"{plugin_name}--{original_name}" if plain_target.exists() else original_name

        if frontmatter is not None:
            frontmatter["name"] = new_name
            dumped = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
            body = strip_frontmatter(content)
            content = f"---\n{dumped}---\n{body}"

        target_file = target_dir / f"{new_name}.md"
        target_file.write_text(content, encoding="utf-8")
        installed.append(new_name)

    if installed:
        logger.info(
            "Installed {count} command(s) from '{plugin}' to {path}",
            count=len(installed),
            plugin=plugin_name,
            path=target_dir,
        )

    return installed


def install_plugin_skills(
    plugin_dir: Path,
    plugin_name: str,
    marketplace_name: str | None = None,
    *,
    prefix_skills: bool = True,
) -> tuple[list[str], Path | None]:
    """Extract skills from a Claude Code plugin into bhu-cli's skill directory."""
    plugin_json = plugin_dir / ".claude-plugin" / "plugin.json"
    if not plugin_json.exists():
        plugin_json = plugin_dir / "plugin.json"

    spec_skills: str | list[str] | None = None
    spec_mcp: str | None = None
    if plugin_json.exists():
        try:
            spec = parse_claude_plugin_json(plugin_json)
            spec_skills = spec.skills
            spec_mcp = spec.mcpServers
            if spec.name:
                plugin_name = spec.name
        except MarketplaceError:
            pass

    skills_dir = _find_skills_dir(plugin_dir, spec_skills)
    if skills_dir is None:
        raise MarketplaceError(f"No skills directory found in plugin at {plugin_dir}")

    target_name = f"{marketplace_name}-{plugin_name}" if marketplace_name else plugin_name
    target_dir = get_share_dir() / "skills" / target_name

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if target_dir.exists():
        logger.info("Removing existing skill installation at {path}", path=target_dir)
        shutil.rmtree(target_dir)

    shutil.copytree(skills_dir, target_dir)

    installed: list[str] = []
    for skill_dir in target_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue

        original_name = skill_dir.name
        if prefix_skills:
            new_name = f"{plugin_name}--{original_name}"
            # Rewrite the 'name' field in SKILL.md frontmatter
            content = skill_md.read_text(encoding="utf-8")
            frontmatter = parse_frontmatter(content)
            if frontmatter is not None:
                frontmatter["name"] = new_name
                dumped = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
                new_content = f"---\n{dumped}---\n{strip_frontmatter(content)}"
                skill_md.write_text(new_content, encoding="utf-8")
            installed.append(new_name)
        else:
            installed.append(original_name)

    logger.info(
        "Installed {count} skill(s) from '{plugin}' to {path}",
        count=len(installed),
        plugin=plugin_name,
        path=target_dir,
    )

    # Locate MCP server config
    mcp_config: Path | None = None
    if spec_mcp is not None:
        candidate = (plugin_dir / spec_mcp).resolve()
        if candidate.is_file() and candidate.is_relative_to(plugin_dir.resolve()):
            mcp_config = candidate
    else:
        for name in ("mcp-servers.json", "mcp.json", ".mcp.json"):
            candidate = plugin_dir / name
            if candidate.is_file():
                mcp_config = candidate
                break

    return installed, mcp_config


def install_plugin_mcp_servers(
    plugin_dir: Path,
    plugin_name: str,
) -> list[str]:
    """Merge MCP servers from a plugin into ~/.kimi/plugin-mcp.json.

    Server names are prefixed with the plugin name to avoid collisions.
    Returns the list of server names that were added.
    """
    import json

    from fastmcp.mcp_config import MCPConfig

    # Locate MCP config file (same logic as install_plugin_skills)
    plugin_json = plugin_dir / ".claude-plugin" / "plugin.json"
    if not plugin_json.exists():
        plugin_json = plugin_dir / "plugin.json"

    spec_mcp: str | None = None
    if plugin_json.exists():
        try:
            spec = parse_claude_plugin_json(plugin_json)
            spec_mcp = spec.mcpServers
            if spec.name:
                plugin_name = spec.name
        except MarketplaceError:
            pass

    mcp_file: Path | None = None
    if spec_mcp is not None:
        candidate = (plugin_dir / spec_mcp).resolve()
        if candidate.is_file() and candidate.is_relative_to(plugin_dir.resolve()):
            mcp_file = candidate
    else:
        for name in ("mcp-servers.json", "mcp.json", ".mcp.json"):
            candidate = plugin_dir / name
            if candidate.is_file():
                mcp_file = candidate
                break

    if mcp_file is None:
        return []

    try:
        raw = json.loads(mcp_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Failed to read plugin MCP config from {path}: {exc}",
            path=mcp_file,
            exc=exc,
        )
        return []

    try:
        parsed = MCPConfig.model_validate(raw)
    except Exception as exc:
        logger.warning("Invalid MCP config in plugin {plugin}: {exc}", plugin=plugin_name, exc=exc)
        return []

    if not parsed.mcpServers:
        return []

    plugin_mcp_path = get_share_dir() / "plugin-mcp.json"
    plugin_mcp_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if plugin_mcp_path.exists():
        try:
            existing = json.loads(plugin_mcp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}

    if "mcpServers" not in existing:
        existing["mcpServers"] = {}

    added: list[str] = []
    for server_name, server_config in parsed.mcpServers.items():
        prefixed = f"{plugin_name}--{server_name}"
        if prefixed in existing["mcpServers"]:
            logger.warning(
                "MCP server '{name}' from plugin '{plugin}' already exists in "
                "plugin-mcp.json, skipping",
                name=prefixed,
                plugin=plugin_name,
            )
            continue
        existing["mcpServers"][prefixed] = server_config.model_dump(exclude_none=True)
        added.append(prefixed)

    if added:
        plugin_mcp_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(
            "Registered {count} MCP server(s) from '{plugin}' to {path}",
            count=len(added),
            plugin=plugin_name,
            path=plugin_mcp_path,
        )

    return added
