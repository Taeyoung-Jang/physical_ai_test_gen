"""Random-only environment sweep. Preparation/reporting are offline; run requires --live."""

from run_paired_discovery import main

if __name__ == "__main__":
    raise SystemExit(main(random_only=True))
