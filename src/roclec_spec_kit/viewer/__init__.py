"""Optional local viewer (``roclec view``). Requires the ``viewer`` extra: ``roclec-spec-kit[viewer]``."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import threading
import webbrowser

from ..model import ModelError

INSTALL_HINT = "pip install 'roclec-spec-kit[viewer]'"


def available():
    try:
        import flask  # noqa: F401
    except ImportError:
        return False
    return True


def serve(root, *, port=0, open_browser=True, announce=None):
    """Run the viewer in the foreground until interrupted; returns a summary for the CLI envelope."""
    announce = announce or (lambda message: print(message, file=sys.stderr, flush=True))
    if not available():
        raise ModelError("VIEWER_UNAVAILABLE", "The viewer needs the optional 'viewer' extra", exit_code=1,
                         remediation=f"Install it with: {INSTALL_HINT}")
    from werkzeug.serving import make_server
    from .server import STATIC, create_app
    from ..config import load_profile
    profile = load_profile(Path(root))
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # no per-request noise in the terminal
    if not (STATIC / "index.html").is_file():
        raise ModelError("VIEWER_UNAVAILABLE", "This installation does not include the compiled viewer interface", exit_code=1,
                         remediation="Reinstall the published wheel, or run scripts/build_viewer.py in a source checkout.")
    app = create_app(profile.root)
    server = make_server("127.0.0.1", port, app, threaded=True)
    app.config["VIEWER_PORT"] = server.server_port
    url = f"http://127.0.0.1:{server.server_port}/"
    announce(f"Roclec viewer · {profile.data['name']}\n{url}\nCtrl+C para cerrar")
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"url": url, "project": profile.data["name"], "stopped": True}
