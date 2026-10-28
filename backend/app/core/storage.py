"""The upload volume, as a dependency that can fail.

Every invoice is bytes on disk before it is a row — ``storage_path`` is a
column, so the file has to exist first — which makes the directory behind
``UPLOAD_DIR`` the fourth thing an upload needs after the database, and the
only one of the four that nothing used to watch after boot. A volume that
fills, or that a node remounts read-only, fails every upload with a 500 while
``/health`` goes on answering ``ok``: the startup check had passed, and no
later check existed.

It is also state the API and the Celery worker share *by path*: the API
writes the file, and the worker opens ``storage_path`` to parse it. Both must
mount the same ``UPLOAD_DIR``. That holds on the single box this deploys to;
a worker on another host needs the volume shared, or the bytes moved into
object storage, before it can take a single parse.

Shaped like :func:`app.core.database.check_database` on purpose — ``(ok,
error_type)`` — so the health route treats the two the same way.
"""
from __future__ import annotations

from pathlib import Path

from app.core.config import settings

# A fixed name rather than a fresh one per probe, so a probe that failed
# half-way (written, not unlinked) is overwritten by the next rather than
# accumulating; and dot-prefixed so it never shows up beside real uploads.
_PROBE_NAME = ".write-probe"


def writable(directory: Path) -> bool:
    """Whether a file can be created in *directory* right now.

    An actual write rather than ``os.access``: the access bits say what the
    permissions allow, and a full disk or a read-only remount passes them.
    """
    probe = directory / _PROBE_NAME
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def check_upload_dir() -> tuple[bool, str | None]:
    """``(writable, error_type)`` for the configured upload directory.

    Creates the directory when it is missing, as startup does — a volume that
    came back empty after a remount is a directory that needs making, not a
    failure to report — and then proves a write lands in it. The error type
    is the exception class where there was one, and ``"ReadOnly"`` where the
    directory exists but refused the probe, so the operator knows which of
    the two to go and look at.
    """
    directory = Path(settings.upload_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, type(exc).__name__
    if not writable(directory):
        return False, "ReadOnly"
    return True, None
