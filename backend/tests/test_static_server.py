"""deploy/static-server.mjs, run: what it answers, and how long it may be kept.

The other deploy tests read the server's source. These start it, because the
bug they cover was in which response got which header, and that only shows
when a request is made.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[2] / "deploy" / "static-server.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

YEAR = "public, max-age=31536000, immutable"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("dist")
    (root / "assets").mkdir()
    (root / "assets" / "index-abc123.js").write_text("console.log(1)")
    (root / "app-shell.html").write_text("<!doctype html><title>shell</title>")
    (root / "index.html").write_text("<!doctype html><title>home</title>")
    port = _free_port()
    process = subprocess.Popen(
        [NODE, str(SERVER), "--root", str(root), "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    yield base
    process.terminate()
    process.wait(timeout=5)


def _get(url: str) -> tuple[int, dict[str, str], bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


class TestOnlyAFingerprintedFileIsKeptForAYear:
    """P36 M4: the year-long header followed the URL, not the file.

    ``cacheControl`` looked at the request path, so anything under ``/assets/``
    that is not a file (``/assets/``, ``/assets/foo``, a chunk name mistyped
    without its extension) was answered with the SPA shell *and* ``immutable``
    for a year. A browser that once fetched one kept that page, and the bundle
    it pins, until next year. Production answered this way.
    """

    def test_a_fingerprinted_asset_is_immutable(self, site):
        status, headers, _ = _get(f"{site}/assets/index-abc123.js")
        assert status == 200
        assert headers["Cache-Control"] == YEAR

    @pytest.mark.parametrize("path", ["/assets/", "/assets/foo", "/assets/nested/route"])
    def test_the_shell_is_never_immutable_whatever_url_it_answers(self, site, path):
        status, headers, body = _get(f"{site}{path}")
        assert status == 200
        assert b"shell" in body
        assert headers["Cache-Control"] == "no-store"

    def test_a_missing_asset_is_not_cacheable_either(self, site):
        # Between a deploy removing old chunks and a tab reloading, a 404 that
        # something in front kept would outlive the next deploy that fixes it.
        status, headers, _ = _get(f"{site}/assets/index-gone.js")
        assert status == 404
        assert headers.get("Cache-Control") == "no-store"

    def test_an_app_route_is_the_shell_and_not_stored(self, site):
        status, headers, body = _get(f"{site}/invoices/42")
        assert status == 200
        assert b"shell" in body
        assert headers["Cache-Control"] == "no-store"
