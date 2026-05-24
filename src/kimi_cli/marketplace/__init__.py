"""Claude Code-compatible marketplace discovery and installation."""

import json
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from kimi_cli.share import get_share_dir


class MarketplaceError(Exception):
    """Raised when marketplace operations fail."""


class MarketplaceOwner(BaseModel):
    name: str
    email: str | None = None
    url: str | None = None


class MarketplaceMetadata(BaseModel):
    description: str | None = None
    version: str | None = None
    pluginRoot: str | None = None


class PluginSource(BaseModel):
    """Parsed plugin source reference."""

    source: Literal["github", "git", "directory"] = "directory"
    repo: str | None = None
    url: str | None = None
    path: str | None = None

    @classmethod
    def from_value(cls, value: str | dict[str, Any]) -> Self:
        if isinstance(value, str):
            return cls(source="directory", path=value)
        return cls.model_validate(value)

    def to_url(self) -> str | None:
        if self.source == "github" and self.repo:
            return f"https://github.com/{self.repo}.git"
        if self.source == "git":
            return self.url
        return None


class MarketplacePluginEntry(BaseModel):
    name: str
    source: str | dict[str, Any]
    description: str | None = None
    version: str | None = None
    author: MarketplaceOwner | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    def resolved_source(self) -> PluginSource:
        return PluginSource.from_value(self.source)


class MarketplaceSpec(BaseModel):
    """Parsed marketplace.json content."""

    model_config = ConfigDict(extra="ignore")

    name: str
    owner: MarketplaceOwner | None = None
    metadata: MarketplaceMetadata | None = None
    plugins: list[MarketplacePluginEntry] = Field(default_factory=list[MarketplacePluginEntry])


class PluginAuthor(BaseModel):
    name: str | None = None
    email: str | None = None
    url: str | None = None


class PluginSpec(BaseModel):
    """Parsed .claude-plugin/plugin.json content."""

    model_config = ConfigDict(extra="ignore")

    name: str
    version: str | None = None
    description: str | None = None
    author: PluginAuthor | None = None
    homepage: str | None = None
    repository: str | None = None
    license: str | None = None
    keywords: list[str] = Field(default_factory=list)
    skills: str | list[str] | None = None
    commands: str | list[str] | None = None
    agents: str | list[str] | None = None
    hooks: str | None = None
    mcpServers: str | None = None
    outputStyles: str | None = None
    lspServers: str | None = None
    monitors: str | None = None


def get_marketplaces_dir() -> Path:
    """Return the directory where marketplace repos are cached."""
    return get_share_dir() / "marketplaces"


def get_marketplace_registry_path() -> Path:
    """Return the path to the marketplace registry JSON file."""
    return get_share_dir() / "marketplaces.json"


def load_marketplace_registry() -> dict[str, str]:
    """Load the marketplace registry as a mapping of name -> source URL/path."""
    path = get_marketplace_registry_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketplaceError(f"Failed to read marketplace registry: {exc}") from exc
    if not isinstance(data, dict):
        return {}
    result: dict[str, str] = {}
    items: list[tuple[str, Any]] = list(data.items())  # type: ignore[arg-type]
    for raw_key, raw_val in items:
        if isinstance(raw_val, str):
            result[raw_key] = raw_val
    return result


def save_marketplace_registry(registry: dict[str, str]) -> None:
    """Save the marketplace registry."""
    path = get_marketplace_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def parse_marketplace_json(path: Path) -> MarketplaceSpec:
    """Parse a marketplace.json file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketplaceError(f"Failed to read marketplace.json at {path}: {exc}") from exc
    try:
        return MarketplaceSpec.model_validate(data)
    except Exception as exc:
        raise MarketplaceError(f"Invalid marketplace.json at {path}: {exc}") from exc


def parse_claude_plugin_json(path: Path) -> PluginSpec:
    """Parse a .claude-plugin/plugin.json file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketplaceError(f"Failed to read plugin.json at {path}: {exc}") from exc
    try:
        return PluginSpec.model_validate(data)
    except Exception as exc:
        raise MarketplaceError(f"Invalid plugin.json at {path}: {exc}") from exc
