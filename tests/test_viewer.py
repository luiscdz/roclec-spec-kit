"""Viewer API on real consumer projects: shared scenarios plus server-level safety checks."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

try:
    import flask  # noqa: F401
except ImportError:  # The viewer is an optional extra.
    flask = None

from scripts.viewer_scenarios import partial_provenance_scenarios, published_scenarios, review_attribution_scenarios, scenarios
from test_kernel import invoke


def checker(test):
    return lambda name, condition, detail="": test.assertTrue(condition, f"{name}: {detail}")


class Fetcher:
    """Flask test-client access, one app per project root."""

    def __init__(self):
        from roclec_spec_kit.viewer.server import create_app
        self.make, self.clients = create_app, {}

    def __call__(self, root, path):
        client = self.clients.setdefault(Path(root), self.make(Path(root)).test_client())
        response = client.get(path, base_url="http://localhost")
        try:
            return response.status_code, response.get_json()
        except Exception:  # noqa: BLE001 - binary or empty body
            return response.status_code, None


@unittest.skipIf(flask is None, "the viewer extra is not installed")
class ViewerTest(unittest.TestCase):
    def test_planning_release_comparison_reading_scope_and_branches(self):
        with tempfile.TemporaryDirectory() as directory:
            scenarios(Path(directory), invoke, checker(self), Fetcher())

    def test_published_history_survives_project_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            published_scenarios(Path(directory), invoke, checker(self), Fetcher())

    def test_review_attribution_matches_the_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            review_attribution_scenarios(Path(directory), invoke, checker(self), Fetcher())

    def test_partial_publication_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            partial_provenance_scenarios(Path(directory), invoke, checker(self), Fetcher())


@unittest.skipIf(flask is None, "the viewer extra is not installed")
class ServerSafetyTest(unittest.TestCase):
    def setUp(self):
        from scripts.c1_scenarios import init_trunk, profile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        init_trunk(self.root)
        config = Path(self.temp.name) / "profile.toml"
        profile(config)
        self.assertEqual(invoke(["--json", "init", str(self.root), "--profile", str(config)]).returncode, 0)
        from roclec_spec_kit.viewer.server import create_app
        self.app = create_app(self.root)
        self.client = self.app.test_client()

    def test_empty_project_has_no_releases(self):
        body = self.client.get("/api/v1/releases", base_url="http://localhost").get_json()
        self.assertEqual(body["data"], {"releases": []})
        tree = self.client.get("/api/v1/docs/tree", base_url="http://localhost").get_json()["data"]
        # init generates only the flow view; its managed header is not taken as the title.
        self.assertEqual([(c["path"], [(f["path"], f["title"]) for f in c["children"]]) for c in tree["children"]],
                         [("docs", [("docs/flow.md", "Project flow")])])

    def test_foreign_host_origin_and_methods_are_rejected(self):
        self.assertEqual(self.client.get("/api/v1/project", base_url="http://evil.example").status_code, 421)
        self.assertEqual(self.client.get("/api/v1/project", base_url="http://localhost", headers={"Origin": "http://evil.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/project", base_url="http://localhost").status_code, 405)
        self.assertEqual(self.client.delete("/api/v1/project", base_url="http://localhost").status_code, 405)
        self.assertEqual(self.client.get("/api/v1/project", base_url="http://127.0.0.1").status_code, 200)

    def test_security_headers_and_unknown_routes(self):
        response = self.client.get("/api/v1/project", base_url="http://localhost")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        missing = self.client.get("/api/v1/nope", base_url="http://localhost")
        self.assertEqual((missing.status_code, missing.get_json()["error"]["kind"]), (404, "not_found"))

    def test_repository_change_during_read_is_reported_not_mixed(self):
        states = iter(["before", "after"])
        with mock.patch("roclec_spec_kit.viewer.server.current_state", side_effect=lambda root: next(states)):
            response = self.client.get("/api/v1/project", base_url="http://localhost")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["kind"], "repository_changed")

    def test_invalid_record_is_distinct_from_missing(self):
        broken = self.root / ".roclec/releases/engine/v1.0.0"
        broken.mkdir(parents=True)
        (broken / "release.json").write_text("{not json", encoding="utf-8")
        response = self.client.get("/api/v1/releases", base_url="http://localhost")
        error = response.get_json()["error"]
        self.assertEqual((response.status_code, error["kind"], error["code"]), (422, "invalid_record", "INVALID_INPUT"))
        missing = self.client.get("/api/v1/releases/engine/v2.0.0", base_url="http://localhost")
        self.assertIn(missing.get_json()["error"]["kind"], {"invalid_record"})  # the damaged history blocks every release read

    def test_pending_operation_is_reported_as_unavailable(self):
        runtime = self.root / ".roclec/runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / ("a" * 64 + ".json")).write_text("{}", encoding="utf-8")
        response = self.client.get("/api/v1/releases", base_url="http://localhost")
        error = response.get_json()["error"]
        self.assertEqual((response.status_code, error["code"]), (503, "IO_PARTIAL"))


class CommandTest(unittest.TestCase):
    def test_view_without_extra_gives_install_instruction(self):
        from roclec_spec_kit import viewer
        with mock.patch.object(viewer, "available", return_value=False):
            result = invoke(["--json", "--project", ".", "view", "--no-open"])
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["issues"][0]["code"], "VIEWER_UNAVAILABLE")
        self.assertIn("roclec-spec-kit[viewer]", payload["issues"][0]["remediation"])

    def test_view_rejects_invalid_port(self):
        result = invoke(["--json", "view", "--port", "70000"])
        self.assertEqual(result.returncode, 2)
