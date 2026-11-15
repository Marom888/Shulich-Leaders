import http.server
import os
import re
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    """Static file server that honours single 'Range: bytes=a-b' requests (like the NASA servers)."""

    requests_seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = Path(self.translate_path(self.path))
        RangeHandler.requests_seen.append((self.path, self.headers.get("Range")))
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d+)-(\d*)", rng)
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else len(data) - 1
            if start >= len(data):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(data)}")
                self.end_headers()
                return
            end = min(end, len(data) - 1)
            body = data[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        else:
            body = data
            self.send_response(200)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def range_server(tmp_path):
    """Serve tmp_path/www over HTTP on localhost with Range support. Yields (base_url, www_dir)."""
    www = tmp_path / "www"
    www.mkdir()
    handler = lambda *a, **k: RangeHandler(*a, directory=str(www), **k)  # noqa: E731
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    RangeHandler.requests_seen = []
    # make sure no proxy is used for localhost
    os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
    yield f"http://127.0.0.1:{srv.server_address[1]}", www
    srv.shutdown()


@pytest.fixture()
def store(tmp_path):
    from lunarmatch.core.storage import DataStore

    return DataStore(tmp_path / "data")
