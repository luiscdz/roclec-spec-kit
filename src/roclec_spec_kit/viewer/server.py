"""Local read-only HTTP server: the compiled interface and a JSON API under ``/api/v1``.

The server binds ``127.0.0.1``, rejects foreign ``Host`` and ``Origin`` headers, runs with
debug and the reloader disabled, and never writes consumer files. ``GIT_OPTIONAL_LOCKS=0``
keeps Git status queries from refreshing the consumer's index.
"""
from __future__ import annotations

from pathlib import Path
import threading
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

from .. import __version__
from ..config import ConfigError, load_profile
from ..kernel import Kernel
from ..model import ModelError
from .docs import DocsIndex
from .reader import Reader, ViewerError, classify, state_id

STATIC = Path(__file__).resolve().parent / "static"
ID_RUN = "RUN-"
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'")


def current_state(root):
    profile = load_profile(Path(root))
    return state_id(profile, Kernel(profile, allow_pending=True).store)


class ViewerApp:
    """Holds per-state caches only; every projection is built from fresh readers."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self._lock = threading.Lock()
        self._index = None

    def snapshot(self, build, *, docs=False):
        """Run one projection, rejecting it when the repository changed while it was being read."""
        before = current_state(self.root)
        reader = Reader(self.root)
        value = build(self.docs(reader, before) if docs else reader)
        if current_state(self.root) != before:
            raise ViewerError("repository_changed", "REPOSITORY_CHANGED", "El repositorio cambió durante la lectura", status=409,
                              remediation="Recarga la vista para leer un estado consistente.")
        return value, before

    def docs(self, reader, state):
        with self._lock:
            if self._index is None or self._index[0] != state:
                self._index = (state, DocsIndex(reader))
            return self._index[1]

    def refresh(self):
        with self._lock:
            self._index = None


def create_app(root):
    state = ViewerApp(root)
    app = Flask(__name__, static_folder=None)
    app.config.update(JSON_SORT_KEYS=False, MAX_CONTENT_LENGTH=1024)
    app.json.sort_keys = False
    app.json.ensure_ascii = False
    app.extensions["roclec_viewer"] = state
    allowed_hosts = {"127.0.0.1", "localhost"}

    @app.before_request
    def guard():
        host = request.host.rsplit(":", 1)[0].strip("[]").lower()
        port = app.config.get("VIEWER_PORT")
        explicit = request.host.rsplit(":", 1)[-1] if ":" in request.host.strip("[]") else None
        if host not in allowed_hosts or (port is not None and explicit is not None and explicit != str(port)):
            return Response("Host not allowed", status=421)
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            return Response("Origin not allowed", status=403)
        if request.method not in {"GET", "HEAD", "POST"} or (request.method == "POST" and request.path != "/api/v1/refresh"):
            return Response("Method not allowed", status=405)

    @app.after_request
    def headers(response):
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def failure(error: ViewerError):
        return jsonify({"ok": False, "error": error.payload}), error.status

    @app.errorhandler(ViewerError)
    def viewer_error(error):
        return failure(error)

    @app.errorhandler(ModelError)
    def model_error(error):
        issue = error.issue
        if issue["code"] in {"IO_PARTIAL", "OPERATION_CONFLICT"}:
            return failure(ViewerError("query_failed", issue["code"], issue["message"], status=503, issue=issue))
        return failure(classify(error))

    @app.errorhandler(ConfigError)
    def config_error(error):
        return failure(ViewerError("query_failed", "CONFIG_ERROR", str(error), status=500))

    @app.errorhandler(Exception)
    def unexpected(error):
        if hasattr(error, "code") and isinstance(error.code, int) and error.code < 500:
            return Response(error.name, status=error.code)
        app.logger.exception("Unexpected viewer error")
        return failure(ViewerError("query_failed", "INTERNAL_ERROR", "Falló la consulta", status=500))

    def respond(build, *, docs=False):
        data, current = state.snapshot(build, docs=docs)
        return jsonify({"ok": True, "state_id": current, "data": data})

    def context(args):
        release, change = args.get("release"), args.get("change")
        if release and change:
            raise ViewerError("invalid_query", "INVALID_INPUT", "Select a release or a change context, not both", status=400)
        if change and not args.get("intent"):
            raise ViewerError("invalid_query", "INVALID_INPUT", "A change context needs its intent revision", status=400)
        return release, ((change, args["intent"]) if change else None)

    # ---- API ------------------------------------------------------------

    @app.get("/api/v1/project")
    def project():
        return respond(lambda r: {**r.project(), "viewer_version": __version__})

    @app.get("/api/v1/state")
    def state_route():
        return jsonify({"ok": True, "state_id": current_state(state.root)})

    @app.post("/api/v1/refresh")
    def refresh():
        state.refresh()
        return respond(lambda r: {**r.project(), "viewer_version": __version__})

    @app.get("/api/v1/releases")
    def releases():
        return respond(lambda r: r.release_list(request.args.get("component")))

    @app.get("/api/v1/releases/<component>/<version>")
    def release(component, version):
        return respond(lambda r: r.release(component, version))

    @app.get("/api/v1/changes/<change_id>")
    def change(change_id):
        return respond(lambda r: r.change(change_id, request.args.get("revision"), request.args.get("component")))

    @app.get("/api/v1/requirements/<req>")
    def requirement(req):
        args = request.args
        cap, revision = args.get("cap"), args.get("revision")
        if not cap or not revision:
            raise ViewerError("invalid_query", "INVALID_INPUT", "A requirement needs its capability and contract revision", status=400)
        release_version, change_context = context(args)
        return respond(lambda r: r.requirement(req, cap, revision, args.get("component"), release_version, change_context,
                                                args.get("release_component")))

    @app.get("/api/v1/evidence/<record>")
    def evidence(record):
        def build(r):
            if record.startswith("RUN-"):
                return r.evidence_run(record)
            if record.startswith("EVD-"):
                return r.evidence_report(record)
            raise ViewerError("not_found", "NOT_FOUND", "Unknown evidence identifier", status=404, entity=record)
        return respond(build)

    @app.get("/api/v1/evidence/<run>/checks/<check>")
    def evidence_check(run, check):
        return respond(lambda r: r.evidence_check(run, check))

    @app.get("/api/v1/docs/tree")
    def docs_tree():
        return respond(lambda index: index.tree(), docs=True)

    @app.get("/api/v1/docs/file")
    def docs_file():
        path = request.args.get("path", "")
        return respond(lambda index: index.document(path), docs=True)

    @app.get("/api/v1/docs/asset")
    def docs_asset():
        path = request.args.get("path", "")
        index = state.docs(Reader(state.root), current_state(state.root))
        file, mimetype = index.asset(path)
        response = send_file(file, mimetype=mimetype, max_age=0)
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        return response

    @app.get("/api/v1/search")
    def search():
        query = request.args.get("q", "")
        return respond(lambda index: index.search(query), docs=True)

    @app.get("/api/<path:rest>")
    def unknown_api(rest):
        return failure(ViewerError("not_found", "NOT_FOUND", "Unknown API route", status=404))

    # ---- Compiled interface ---------------------------------------------

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def interface(path):
        if not (STATIC / "index.html").is_file():
            return Response("The viewer interface is not built. Run scripts/build_viewer.py in a source checkout.", status=503, mimetype="text/plain")
        target = (STATIC / path).resolve() if path else None
        if target and target.is_file() and STATIC.resolve() in target.parents:
            return send_from_directory(STATIC, path, max_age=3600 if path.startswith("assets/") else 0)
        return send_from_directory(STATIC, "index.html", max_age=0)

    return app
