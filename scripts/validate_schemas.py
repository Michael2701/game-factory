"""Milestone 2 check: build every schema from sample data, validate, and JSON round-trip.

Usage (from project root):
    python scripts/validate_schemas.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.schemas.examples import ALL_SAMPLES  # noqa: E402


def main() -> int:
    for name, build in ALL_SAMPLES.items():
        obj = build()
        restored = type(obj).model_validate_json(obj.model_dump_json())
        if restored != obj:
            print(f"FAIL {name}: JSON round-trip mismatch")
            return 1
        print(f"\n=== {name} ===")
        print(obj.model_dump_json(indent=2, exclude_none=True))

    print(f"\nall schemas valid ({len(ALL_SAMPLES)} models, JSON round-trip ok)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
