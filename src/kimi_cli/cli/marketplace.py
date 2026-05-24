"""CLI commands for Claude Code-compatible marketplace management."""

from pathlib import Path
from typing import Annotated

import typer

from kimi_cli import logger
from kimi_cli.marketplace import (
    MarketplaceError,
    MarketplaceSpec,
    get_marketplaces_dir,
    load_marketplace_registry,
    parse_marketplace_json,
    save_marketplace_registry,
)
from kimi_cli.marketplace.installer import (
    install_plugin_commands,
    install_plugin_mcp_servers,
    install_plugin_skills,
    validate_plugin,
)
from kimi_cli.marketplace.resolver import resolve_marketplace_source, resolve_plugin_source

cli = typer.Typer(help="Manage Claude Code-compatible skill marketplaces.")


def _print_plugins(spec: MarketplaceSpec) -> None:
    """Print plugin list for a marketplace spec."""
    typer.echo(f"Marketplace: {spec.name}")
    if not spec.plugins:
        typer.echo("  No plugins available.")
        return

    for plugin in spec.plugins:
        typer.echo(f"  - {plugin.name}")
        if plugin.description:
            typer.echo(f"      Description: {plugin.description}")
        source_hint = ""
        if isinstance(plugin.source, dict):
            src_type = plugin.source.get("source", "directory")
            if src_type == "github":
                source_hint = f" (github: {plugin.source.get('repo', '')})"
            elif src_type == "git":
                source_hint = f" (git: {plugin.source.get('url', '')})"
            elif src_type == "directory":
                source_hint = f" (dir: {plugin.source.get('path', '')})"
        install_cmd_text = f"kimi marketplace install {plugin.name}@{spec.name}{source_hint}"
        typer.echo(f"      Install: {install_cmd_text}")


def _get_marketplace_dir(name: str) -> Path:
    """Return the cache directory for a named marketplace."""
    return get_marketplaces_dir() / name


def _ensure_marketplace_spec(name: str) -> tuple[Path, MarketplaceSpec]:
    """Load the marketplace.json for a registered marketplace.

    Returns ``(plugin_base_dir, spec)`` where *plugin_base_dir* accounts for
    ``metadata.pluginRoot`` if present.
    """
    registry = load_marketplace_registry()
    if name not in registry:
        raise MarketplaceError(
            f"Marketplace '{name}' is not registered. Run 'kimi marketplace add <source>' first."
        )

    marketplace_dir = _get_marketplace_dir(name)
    if not marketplace_dir.exists():
        raise MarketplaceError(
            f"Marketplace '{name}' cache is missing. "
            f"Run 'kimi marketplace update {name}' to re-fetch."
        )

    candidates = [
        marketplace_dir / ".claude-plugin" / "marketplace.json",
        marketplace_dir / "marketplace.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            spec = parse_marketplace_json(candidate)
            plugin_root = (
                marketplace_dir / spec.metadata.pluginRoot
                if spec.metadata and spec.metadata.pluginRoot
                else marketplace_dir
            )
            return plugin_root, spec

    raise MarketplaceError(f"No marketplace.json found for '{name}'")


@cli.command("add")
def add_cmd(
    source: Annotated[
        str,
        typer.Argument(help="Marketplace source: GitHub owner/repo, git URL, or local path"),
    ],
    name: Annotated[
        str | None,
        typer.Option(help="Custom name for the marketplace. Defaults to repo name."),
    ] = None,
) -> None:
    """Add a Claude Code-compatible marketplace."""
    import shutil

    try:
        local_dir, tmp_dir = resolve_marketplace_source(source)
    except MarketplaceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    try:
        # Find marketplace.json
        candidates = [
            local_dir / ".claude-plugin" / "marketplace.json",
            local_dir / "marketplace.json",
        ]
        marketplace_json: Path | None = None
        for candidate in candidates:
            if candidate.exists():
                marketplace_json = candidate
                break

        if marketplace_json is None:
            typer.echo(
                "Error: No marketplace.json found in source. "
                "Expected .claude-plugin/marketplace.json or marketplace.json",
                err=True,
            )
            raise typer.Exit(1)

        spec = parse_marketplace_json(marketplace_json)
        marketplace_name = name or spec.name
        if not marketplace_name:
            typer.echo("Error: Marketplace has no name and none was provided.", err=True)
            raise typer.Exit(1)

        # Move/copy to cache dir
        cache_dir = _get_marketplace_dir(marketplace_name)
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        shutil.copytree(local_dir, cache_dir)

        # Update registry
        registry = load_marketplace_registry()
        registry[marketplace_name] = source
        save_marketplace_registry(registry)

        typer.echo(f"Added marketplace '{marketplace_name}' ({len(spec.plugins)} plugin(s))")
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)


@cli.command("list")
def list_cmd(
    name: Annotated[
        str | None,
        typer.Argument(help="Marketplace name to inspect. Omit to list all marketplaces."),
    ] = None,
) -> None:
    """List registered marketplaces and their plugins."""
    registry = load_marketplace_registry()
    if not registry:
        typer.echo("No marketplaces registered.")
        return

    if name is not None:
        # Name might be a registered marketplace or a raw source (GitHub shorthand, URL, path).
        if name in registry:
            try:
                _, spec = _ensure_marketplace_spec(name)
            except MarketplaceError as exc:
                typer.echo(f"Error: {exc}", err=True)
                raise typer.Exit(1) from exc
            _print_plugins(spec)
            return

        # Try resolving as a raw source without registering.
        import shutil

        try:
            local_dir, tmp_dir = resolve_marketplace_source(name)
        except MarketplaceError:
            typer.echo(f"Error: Marketplace '{name}' not found.", err=True)
            raise typer.Exit(1) from None

        try:
            candidates = [
                local_dir / ".claude-plugin" / "marketplace.json",
                local_dir / "marketplace.json",
            ]
            marketplace_json: Path | None = None
            for candidate in candidates:
                if candidate.exists():
                    marketplace_json = candidate
                    break

            if marketplace_json is None:
                typer.echo(
                    "Error: No marketplace.json found in source. "
                    "Expected .claude-plugin/marketplace.json or marketplace.json",
                    err=True,
                )
                raise typer.Exit(1)

            spec = parse_marketplace_json(marketplace_json)
            _print_plugins(spec)
        finally:
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        return

    # List all marketplaces with plugin counts
    for mp_name, source in sorted(registry.items()):
        cache_dir = _get_marketplace_dir(mp_name)
        status = "cached" if cache_dir.exists() else "missing"

        count = 0
        if cache_dir.exists():
            try:
                _, spec = _ensure_marketplace_spec(mp_name)
                count = len(spec.plugins)
            except MarketplaceError:
                pass

        count_text = f"{count} plugin(s)" if count else "no plugins"
        typer.echo(f"{mp_name}")
        typer.echo(f"  Status:   {status}")
        typer.echo(f"  Plugins:  {count_text}")
        typer.echo(f"  Source:   {source}")
        typer.echo(f"  Inspect:  bhu marketplace list {mp_name}")


@cli.command("remove")
def remove_cmd(
    name: Annotated[str, typer.Argument(help="Marketplace name to remove")],
) -> None:
    """Remove a marketplace registration and its cache."""
    import shutil

    registry = load_marketplace_registry()
    if name not in registry:
        typer.echo(f"Error: Marketplace '{name}' not found.", err=True)
        raise typer.Exit(1)

    del registry[name]
    save_marketplace_registry(registry)

    cache_dir = _get_marketplace_dir(name)
    if cache_dir.exists():
        shutil.rmtree(cache_dir)

    typer.echo(f"Removed marketplace '{name}'")


@cli.command("update")
def update_cmd(
    name: Annotated[
        str | None,
        typer.Argument(help="Marketplace name to update. Omit to update all."),
    ] = None,
) -> None:
    """Re-fetch marketplace data from source."""
    import shutil

    registry = load_marketplace_registry()
    if not registry:
        typer.echo("No marketplaces registered.")
        return

    targets = [name] if name else list(registry.keys())
    for n in targets:
        if n not in registry:
            typer.echo(f"Error: Marketplace '{n}' not found.", err=True)
            raise typer.Exit(1)

        source = registry[n]
        try:
            local_dir, tmp_dir = resolve_marketplace_source(source)
        except MarketplaceError as exc:
            typer.echo(f"Error updating '{n}': {exc}", err=True)
            continue

        try:
            cache_dir = _get_marketplace_dir(n)
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            shutil.copytree(local_dir, cache_dir)
            typer.echo(f"Updated marketplace '{n}'")
        finally:
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)


@cli.command("install")
def install_cmd(
    plugin_ref: Annotated[
        str,
        typer.Argument(help="Plugin reference: 'name@marketplace' or direct source URL/path"),
    ],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt"),
    ] = False,
) -> None:
    """Install a plugin from a marketplace or direct source."""
    import shutil

    # Parse plugin@marketplace syntax
    if "@" in plugin_ref:
        plugin_name, marketplace_name = plugin_ref.rsplit("@", 1)
        plugin_name = plugin_name.strip()
        marketplace_name = marketplace_name.strip()

        if not plugin_name or not marketplace_name:
            typer.echo("Error: Invalid plugin reference. Use 'name@marketplace'.", err=True)
            raise typer.Exit(1)

        try:
            marketplace_dir, spec = _ensure_marketplace_spec(marketplace_name)
        except MarketplaceError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc

        entry = next((p for p in spec.plugins if p.name == plugin_name), None)
        if entry is None:
            available = ", ".join(p.name for p in spec.plugins)
            typer.echo(
                f"Error: Plugin '{plugin_name}' not found in marketplace '{marketplace_name}'.\n"
                f"Available: {available or '(none)'}",
                err=True,
            )
            raise typer.Exit(1)

        source = entry.resolved_source()
        try:
            plugin_dir, tmp_dir = resolve_plugin_source(
                source.model_dump(exclude_none=True),
                marketplace_dir=marketplace_dir,
            )
        except MarketplaceError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc
    else:
        # Direct source install
        marketplace_name = None
        plugin_name = Path(plugin_ref).name
        try:
            plugin_dir, tmp_dir = resolve_plugin_source(plugin_ref)
        except MarketplaceError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc

    # Pre-install validation
    report = validate_plugin(plugin_dir, plugin_name)
    typer.echo(report.summary())

    if not report.skills:
        typer.echo("Error: No supported skills found in this plugin.", err=True)
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise typer.Exit(1)

    if not yes:
        if report.has_unsupported():
            typer.echo("")
        confirmed = typer.confirm("Proceed with installation?")
        if not confirmed:
            typer.echo("Installation cancelled.")
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            raise typer.Exit(0)

    try:
        installed, _mcp_config = install_plugin_skills(
            plugin_dir,
            plugin_name=plugin_ref.split("@")[0] if "@" in plugin_ref else plugin_ref,
            marketplace_name=marketplace_name,
        )

        if installed:
            typer.echo(f"\nInstalled {len(installed)} skill(s):")
            for skill_name in installed:
                typer.echo(f"  - {skill_name}")
        else:
            typer.echo("Warning: No valid skills found in plugin.", err=True)

        # Merge plugin MCP servers into plugin-mcp.json
        try:
            mcp_added = install_plugin_mcp_servers(plugin_dir, plugin_name)
            if mcp_added:
                typer.echo(f"\nRegistered MCP server(s) from '{plugin_name}':")
                for server_name in mcp_added:
                    typer.echo(f"  - {server_name}")
        except Exception as exc:
            logger.warning(
                "Failed to register MCP servers for '{plugin}': {exc}",
                plugin=plugin_name,
                exc=exc,
            )

        # Install plugin commands
        try:
            commands_added = install_plugin_commands(
                plugin_dir,
                plugin_name,
                marketplace_name=marketplace_name,
            )
            if commands_added:
                typer.echo(f"\nInstalled {len(commands_added)} command(s):")
                for cmd_name in commands_added:
                    typer.echo(f"  - {cmd_name}")
        except Exception as exc:
            logger.warning(
                "Failed to install commands for '{plugin}': {exc}",
                plugin=plugin_name,
                exc=exc,
            )
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
