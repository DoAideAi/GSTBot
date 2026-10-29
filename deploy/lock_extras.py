"""Print the installed distributions that requirements.lock does not name.

Run with the virtualenv's own interpreter, so it sees what that environment
holds: ``.venv/bin/python deploy/lock_extras.py backend/requirements.lock``.

``pip install -r`` adds and upgrades but never removes, so a package dropped
from the lock stayed installed for good. On 2026-10-29 production carried
eight such leftovers, among them python-jose and ecdsa with published
vulnerabilities — invisible to an audit of the lock, which no longer listed
them. deploy.sh uninstalls whatever this prints.
"""
from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

# Never removed: the installer itself, and this project's own (editable)
# install, which the lock does not list because it is not a dependency.
KEEP = frozenset({"pip", "setuptools", "gstbot-backend"})

_REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==")


def normalize(name: str) -> str:
    """PEP 503: case-insensitive, with runs of -, _ and . equivalent."""
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_names(lock_text: str) -> set[str]:
    return {
        normalize(match.group(1))
        for line in lock_text.splitlines()
        if (match := _REQUIREMENT.match(line.strip()))
    }


def extras(lock_text: str, installed: list[str]) -> list[str]:
    locked = locked_names(lock_text)
    return sorted(
        {normalize(name) for name in installed} - locked - KEEP
    )


def main(argv: list[str]) -> int:
    lock_text = Path(argv[1]).read_text(encoding="utf-8")
    installed = [
        dist.metadata["Name"] for dist in metadata.distributions() if dist.metadata["Name"]
    ]
    for name in extras(lock_text, installed):
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
