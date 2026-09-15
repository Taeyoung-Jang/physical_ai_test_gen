"""Credential preflight for the existing AFS CLI; no key values are ever printed.

The original CLI remains unchanged. --check-only makes no API request and creates no
artifacts. Other arguments are forwarded to run_expanded_afs.py after live preflight.
"""

import os
import sys


def check_key():
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key.strip():
        print(
            "OPENAI_API_KEY_MISSING: Export OPENAI_API_KEY in the SAME terminal. "
            "The Python process did not receive a nonempty key. No API request was sent.",
            file=sys.stderr,
        )
        return False
    if not key.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in key):
        print(
            "OPENAI_API_KEY_FORMAT: Key contains whitespace or non-ASCII/control characters. "
            "Re-enter the key without quotes or extra spaces. No API request was sent.",
            file=sys.stderr,
        )
        return False
    return True


def main():
    args = sys.argv[1:]
    if "--check-only" in args:
        if args != ["--check-only"]:
            print("Use --check-only by itself; no API request was sent.", file=sys.stderr)
            raise SystemExit(2)
        if not check_key():
            raise SystemExit(2)
        print("KEY_PRESENT: Python received a key. Authentication/model access NOT tested.")
        return
    if "--live" in args and not any(a in args for a in ("--help", "-h")):
        if not check_key():
            raise SystemExit(2)
    from run_expanded_afs import main as run

    run()


if __name__ == "__main__":
    main()
