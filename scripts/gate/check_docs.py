"""Keep the member docs checks and verify unchanged Publishing artifacts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = (
    "docs/workflows/record-identity.schema.json",
    "scripts/gate/identity.py",
    "scripts/gate/identity_selftest.py",
)


def main() -> int:
    """Run existing checks and the lead's offline checker without a second grammar."""
    commands = [
        ["scripts/check_docs_links.py"],
        ["scripts/gate/identity.py"],
        *[["scripts/gate/identity.py", "--verify-copy", path] for path in ARTIFACTS],
        ["scripts/gate/identity_selftest.py"],
    ]
    for command in commands:
        result = subprocess.run([sys.executable, *command], cwd=ROOT, stdin=subprocess.DEVNULL)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
