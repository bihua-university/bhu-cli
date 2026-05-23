#!/usr/bin/env python3
"""PreToolUse hook that rewrites Bash commands via RTK (Rust Token Killer)."""

import json
import subprocess
import sys


def main() -> None:
    data = json.load(sys.stdin)
    tool_name = data.get("tool_name", "")
    if tool_name != "Shell":
        sys.exit(0)

    cmd = data.get("tool_input", {}).get("command", "")
    if not cmd:
        sys.exit(0)

    try:
        result = subprocess.run(
            ["rtk", "rewrite", cmd],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        # rtk returns 0 or 3 when it has a rewritten equivalent, and 1 when
        # the command is unsupported. Treat anything other than 0/3 as "no
        # rewrite available" so we fail-open.
        if result.returncode not in (0, 3):
            sys.exit(0)
        rewrite = result.stdout.strip()
    except Exception:
        sys.exit(0)

    if rewrite and rewrite != cmd:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "updatedInput": {"command": rewrite},
                    }
                }
            )
        )


if __name__ == "__main__":
    main()
