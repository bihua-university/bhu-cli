"""Resolve marketplace and plugin sources to local directories."""

import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from kimi_cli.marketplace import MarketplaceError


def resolve_marketplace_source(source: str) -> tuple[Path, Path | None]:
    """Resolve a marketplace source to a local directory.

    Returns ``(local_dir, tmp_dir)``.  If *tmp_dir* is not None the caller
    should clean it up after use.

    Supports:
    - GitHub shorthand: ``owner/repo``
    - Git URL: ``https://github.com/owner/repo.git``
    - Local directory path
    """
    target = source.strip()

    # GitHub shorthand -> full URL
    if not target.startswith(("http://", "https://", "git@", "/", "~", ".")):
        parts = target.split("/")
        if len(parts) == 2 and all(parts):
            target = f"https://github.com/{target}.git"

    # Git URL handling (inline _is_git_url and _parse_git_url)
    is_git = target.startswith(("https://", "git@", "http://")) and (
        ".git/" in target
        or target.endswith(".git")
        or "github.com/" in target
        or "gitlab.com/" in target
    )

    if is_git:
        # Parse git URL into (clone_url, subpath, branch)
        idx = target.find(".git/")
        if idx == -1 and target.endswith(".git"):
            clone_url, subpath, branch = target, None, None
        elif idx != -1:
            clone_url = target[: idx + 4]
            rest = target[idx + 5 :]
            subpath = rest.strip("/") or None
            branch = None
        else:
            parsed = urlparse(target)
            segments = [s for s in parsed.path.split("/") if s]
            if len(segments) < 2:
                clone_url, subpath, branch = target, None, None
            else:
                owner_repo = "/".join(segments[:2])
                clone_url = f"{parsed.scheme}://{parsed.netloc}/{owner_repo}"
                rest_segments = segments[2:]
                if rest_segments and rest_segments[0] == "-":
                    rest_segments = rest_segments[1:]
                branch = None
                if len(rest_segments) >= 2 and rest_segments[0] == "tree":
                    branch = rest_segments[1]
                    rest_segments = rest_segments[2:]
                subpath = "/".join(rest_segments) or None

        tmp = Path(tempfile.mkdtemp(prefix="kimi-marketplace-"))
        clone_cmd = ["git", "clone", "--depth", "1"]
        if branch:
            clone_cmd += ["--branch", branch]
        clone_cmd += [clone_url, str(tmp / "repo")]
        result = subprocess.run(clone_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            raise MarketplaceError(f"git clone failed: {result.stderr.strip()}")

        repo_root = tmp / "repo"
        if subpath:
            resolved = (repo_root / subpath).resolve()
            if not resolved.is_relative_to(repo_root.resolve()):
                shutil.rmtree(tmp, ignore_errors=True)
                raise MarketplaceError(f"subpath escapes repository: {subpath}")
            if not resolved.is_dir():
                shutil.rmtree(tmp, ignore_errors=True)
                raise MarketplaceError(f"subpath not found in repository: {subpath}")
            return resolved, tmp
        return repo_root, tmp

    # Local path
    p = Path(target).expanduser().resolve()
    if p.is_dir():
        return p, None

    raise MarketplaceError(
        f"Marketplace source '{source}' is not a directory or recognized git URL"
    )


def resolve_plugin_source(
    source: str | dict[str, str],
    marketplace_dir: Path | None = None,
) -> tuple[Path, Path | None]:
    """Resolve a plugin source to a local directory.

    Supports the same sources as ``resolve_marketplace_source``, plus
    relative paths resolved against *marketplace_dir*.
    """
    if isinstance(source, dict):
        src_type = source.get("source", "directory")
        if src_type == "github":
            repo = source.get("repo", "")
            if not repo:
                raise MarketplaceError("GitHub source missing 'repo' field")
            return resolve_marketplace_source(repo)
        if src_type == "git":
            url = source.get("url", "")
            if not url:
                raise MarketplaceError("Git source missing 'url' field")
            return resolve_marketplace_source(url)
        # directory dict
        path = source.get("path", "")
        if not path:
            raise MarketplaceError("Directory source missing 'path' field")
        source = path

    src_str = source.strip()

    # Relative path against marketplace dir
    if marketplace_dir is not None and not Path(src_str).is_absolute():
        candidate = (marketplace_dir / src_str).resolve()
        if candidate.is_dir():
            return candidate, None

    return resolve_marketplace_source(src_str)
