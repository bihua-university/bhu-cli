#!/usr/bin/env python3
"""Fake RTK binary for tests.

Mimics the real rtk behaviour:
- exit 3 + prints "rtk <cmd>" when the command has an RTK equivalent
- exit 1 + no output when unsupported
"""

import sys


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "rewrite":
        cmd = sys.argv[2]
        # Fake rtk supports everything except "npm install"
        if cmd == "npm install":
            sys.exit(1)
        print(f"rtk {cmd}")
        sys.exit(3)


if __name__ == "__main__":
    main()
