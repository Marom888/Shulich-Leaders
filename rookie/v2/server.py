"""Local Rookie 2.0 server (Python standard library only, binds 127.0.0.1).

GET  /                                  static app (outputs/rookie2/)
GET  /api/health                        {"ok": true}
GET  /api/config                        front-end configuration
POST /api/jobs                          mission JSON -> {"job_id"} or 400 with validation errors
GET  /api/jobs/<id>                     status, real progress events, result when finished
GET  /api/jobs/<id>/figures/<window>    Plotly figures for one candidate window
"""
from __future__ import annotations

import json
import threading
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from lunarmatch.config import OUTPUT_DIR
from lunarmatch.discovery import descriptors as dsc
from lunarmatch.discovery.job import run_job
from lunarmatch.discovery.requirements import DraftSpec
from lunarmatch.discovery.store import DescriptorCache
from lunarmatch.mission import MissionError, MissionInput
from lunarmatch.terrain.registry import default_registry
from lunarmatch.visualization.window_figures import figures
from rookie.v2.config import build_config, load_spec

STATIC_DIR = OUTPUT_DIR / "rookie2"


class Engine:
    """Holds jobs, registry and caches. Thread-safe for concurrent requests."""

    def __init__(self, registry=None, cache=None, spec="auto", geocoder=None):
        self.registry = registry or default_registry()
        self.geocoder = geocoder
        self.cache = cache or DescriptorCache()
        self.spec = load_spec() if spec == "auto" else spec
        self.draft = DraftSpec.load(self.spec.path) if self.spec else None
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self._layers: dict = {}

    def config(self):
        cfg = build_config(self.registry)
        cfg["geocoding"] = bool(self.geocoder is not None and self.geocoder.enabled)
        return cfg

    def submit(self, payload: dict) -> str:
        known = {e["experiment_id"] for e in self.spec.experiments()} if self.spec else None
        mission = MissionInput.from_dict(payload, known)      # raises MissionError
        jid = uuid.uuid4().hex[:12]
        job = {"id": jid, "status": "queued", "events": [], "result": None}
        with self.lock:
            self.jobs[jid] = job

        def emit(ev):
            with self.lock:
                job["events"].append(ev)

        def work():
            job["status"] = "running"
            res = run_job(mission, self.registry, self.spec, self.cache, emit, self.draft, self.geocoder)
            with self.lock:
                job["result"], job["status"] = res, res["status"]

        threading.Thread(target=work, daemon=True).start()
        return jid

    def job(self, jid: str, since: int = 0):
        with self.lock:
            j = self.jobs.get(jid)
            if j is None:
                return None
            return {"id": jid, "status": j["status"], "events": j["events"][since:],
                    "n_events": len(j["events"]),
                    "result": j["result"] if j["status"] not in ("queued", "running") else None}

    def window_figures(self, jid: str, window_id: str) -> dict:
        j = self.jobs.get(jid)
        if not j or not j["result"]:
            raise KeyError("job not finished")
        cand = next((c for c in j["result"].get("candidates", []) if c["id"] == window_id), None)
        if cand is None:
            raise KeyError("unknown candidate")
        conn = self.registry.get(cand["dataset"]["id"])
        key = (conn.dataset_id, cand["tile"])
        with self.lock:
            cached = self._layers.get(key)
        if cached is None:
            patch = conn.fetch(cand["tile"])
            cached = (patch, dsc.layers(patch))
            with self.lock:
                self._layers[key] = cached
        patch, layers = cached
        rows, cols = _window_rows_cols(j["result"], window_id)
        return figures(patch, rows, cols, title=window_id, layers=layers)


def _window_rows_cols(result, window_id):
    for c in result["candidates"]:
        if c["id"] == window_id:
            return tuple(c["rows"]), tuple(c["cols"])
    raise KeyError(window_id)


def make_handler(engine: Engine, static_dir: Path = STATIC_DIR):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(static_dir), **kw)

        def log_message(self, *a):  # quiet
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            parts = [unquote(p) for p in u.path.split("/") if p]
            if parts[:1] != ["api"]:
                return super().do_GET()
            try:
                if parts == ["api", "health"]:
                    return self._json({"ok": True})
                if parts == ["api", "config"]:
                    return self._json(engine.config())
                if len(parts) == 3 and parts[1] == "jobs":
                    since = int(dict(x.split("=", 1) for x in u.query.split("&") if "=" in x).get("since", 0))
                    j = engine.job(parts[2], since)
                    return self._json(j) if j else self._json({"error": "unknown job"}, 404)
                if len(parts) == 5 and parts[1] == "jobs" and parts[3] == "figures":
                    return self._json(engine.window_figures(parts[2], parts[4]))
            except KeyError as e:
                return self._json({"error": str(e)}, 404)
            except Exception as e:
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            return self._json({"error": "not found"}, 404)

        def do_POST(self):
            if urlparse(self.path).path != "/api/jobs":
                return self._json({"error": "not found"}, 404)
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                return self._json({"error": "request too large"}, 413)
            try:
                payload = json.loads(self.rfile.read(n) or b"{}")
                return self._json({"job_id": engine.submit(payload)}, 202)
            except MissionError as e:
                return self._json({"error": "invalid mission input", "errors": e.errors}, 400)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                return self._json({"error": f"bad request: {e}"}, 400)

    return Handler


def serve(port: int = 8765, engine: Engine | None = None, static_dir: Path = STATIC_DIR):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(engine or Engine(), static_dir))
    return httpd
