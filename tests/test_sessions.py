"""M-34: opaque agent-session evidence imported with its transcript, quota and storage policy."""
from pathlib import Path
import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

from scripts.c1_scenarios import bundle, chore_bundle, put_json
from scripts.c2_scenarios import PRODUCER, commit, git, setup
from test_kernel import invoke
from roclec_spec_kit.config import load_profile
from roclec_spec_kit.kernel import Kernel
from roclec_spec_kit.verification import Verification

SECRET_ENV = "ROCLEC_TEST_SESSION_SECRET"
SECRET = "s3cret-session-value-91"
TRANSCRIPT = (f"user: deploy with {SECRET}\nassistant: token tok-4821 used; ok\n"
              f"tool: echo {SECRET}\nassistant: déjà vu\r\n").encode("utf-8")


def files(root):
    """Every file below root except Git internals, by relative path."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts}


class SessionEvidenceTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)
        self.root, self.base = setup(self.workspace, invoke)
        self.inputs = self.workspace / "inputs"
        self.inputs.mkdir()

    # ---- helpers --------------------------------------------------------

    def call(self, *args, root=None, expect=0, issue=None):
        result = invoke(["--project", str(root or self.root), "--json", *map(str, args)])
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        if issue:
            self.assertIn(issue, [i["code"] for i in payload["issues"]], result.stdout)
        return payload

    def check_issues(self, root=None, **kwargs):
        """`check` issues except two expected warnings of these fixtures: the flow view's staleness (its learning
        section counts these records, TL.6) and redacted copies in a fixture profile that declares no secrets."""
        return [i for i in self.call("check", root=root, **kwargs)["issues"] if i["code"] not in {"FLOW_VIEW_STALE", "SESSION_REDACTION_EMPTY"}]

    def meta(self, **overrides):
        value = {"model_schema": 2, "host": "claude-code", "host_session_id": "session-0001", "actor": "Fixture agent",
                 "role": "implementer", "model": "fixture-model", "started_at": "2026-01-31T09:00:00Z",
                 "ended_at": "2026-01-31T09:30:00Z", "stage": "implement", "change_id": "CHG-001", "component": "engine"}
        value.update(overrides)
        return {k: v for k, v in value.items() if v is not None}

    def record(self, meta=None, content=TRANSCRIPT, name="session.jsonl", root=None, expect=0, issue=None, extra=()):
        meta_file, transcript = self.inputs / "meta.json", self.inputs / name
        put_json(meta_file, self.meta() if meta is None else meta)
        transcript.write_bytes(content)
        args = ["evidence", "record", "--file", meta_file, *(extra or ("--kind", "agent-session", "--transcript", transcript))]
        return self.call(*args, root=root, expect=expect, issue=issue)

    def profile(self, top="", table=""):
        path = self.root / ".roclec/project.toml"
        text = path.read_text(encoding="utf-8")
        if top:
            text = text.replace('trunk_ref = "refs/heads/main"\n', f'trunk_ref = "refs/heads/main"\n{top}\n', 1)
        if table:
            text = text.rstrip("\n") + f"\n[sessions]\n{table}\n"
        path.write_text(text, encoding="utf-8")

    def stored(self, session_id, root=None):
        return json.loads((root or self.root).joinpath(f".roclec/evidence/{session_id}.json").read_text(encoding="utf-8"))

    # ---- import ---------------------------------------------------------

    def test_branch_import_keeps_original_bytes_and_owner_only_copy(self):
        commit(self.root)
        worktree = self.workspace / "feature"
        git(self.root, "worktree", "add", "-qb", "feature", str(worktree), "HEAD")
        session = self.record(root=worktree)["data"]["evidence"]
        self.assertEqual(session["kind"], "agent-session")
        self.assertIs(session["executed_by_roclec"], False)
        transcript = session["transcript"]
        self.assertEqual((transcript["sha256"], transcript["size"]), (hashlib.sha256(TRANSCRIPT).hexdigest(), len(TRANSCRIPT)))
        self.assertEqual(transcript["storage"], "versioned-redacted")
        raw = worktree / f".roclec/runtime/sessions/{session['id']}/session.jsonl"
        self.assertEqual(raw.read_bytes(), TRANSCRIPT)
        self.assertEqual(raw.stat().st_mode & 0o777, 0o600)
        self.assertEqual(raw.parent.stat().st_mode & 0o077, 0)
        self.assertEqual(self.stored(session["id"], worktree), session)
        self.assertTrue((worktree / f".roclec/evidence/{session['id']}.session").is_file())
        self.assertEqual(self.check_issues(root=worktree), [])
        self.assertFalse((self.root / f".roclec/evidence/{session['id']}.json").exists())

    def test_over_quota_is_rejected_without_any_write(self):
        self.profile(table="quota_bytes = 16")
        before = files(self.root)
        payload = self.record(content=b"x" * 17, expect=2, issue="SESSION_QUOTA_EXCEEDED")
        self.assertIn("quota_bytes", payload["issues"][0]["remediation"])
        self.assertEqual(files(self.root), before)
        self.assertFalse((self.root / ".roclec/runtime/sessions").exists())
        self.record(content=b"x" * 16)

    def test_redacted_copy_hides_secret_values_and_patterns_outside_runtime(self):
        self.profile(top=f'secret_env = ["{SECRET_ENV}"]\nredact_patterns = ["tok-[0-9]+"]')
        with mock.patch.dict(os.environ, {SECRET_ENV: SECRET}):
            session = self.record()["data"]["evidence"]
        self.assertEqual(session["transcript"]["redactions"], 3)
        copy = (self.root / f".roclec/evidence/{session['id']}.session").read_bytes()
        expected = TRANSCRIPT.replace(SECRET.encode(), b"[REDACTED]").replace(b"tok-4821", b"[REDACTED]")
        self.assertEqual(copy, expected)
        self.assertEqual(session["transcript"]["versioned_sha256"], hashlib.sha256(expected).hexdigest())
        for relative, content in files(self.root).items():
            if relative.startswith(".roclec/runtime/"):
                continue
            self.assertNotIn(SECRET.encode(), content, relative)
            self.assertNotIn(b"tok-4821", content, relative)
        self.assertEqual((self.root / f".roclec/runtime/sessions/{session['id']}/session.jsonl").read_bytes(), TRANSCRIPT)

    def test_json_escaped_secret_forms_are_redacted(self):
        secret = 'p@ss"w\\rd/é'
        self.profile(top=f'secret_env = ["{SECRET_ENV}"]')
        content = (json.dumps({"out": f"TOKEN={secret}"}) + "\n"
                   + json.dumps({"out": f"TOKEN={secret}"}, ensure_ascii=False) + "\n").encode("utf-8")
        with mock.patch.dict(os.environ, {SECRET_ENV: secret}):
            session = self.record(content=content)["data"]["evidence"]
        self.assertEqual(session["transcript"]["redactions"], 2)
        for relative, data in files(self.root).items():
            if relative.startswith(".roclec/runtime/"):
                continue
            for form in (secret, json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1]):
                self.assertNotIn(form.encode("utf-8"), data, relative)

    def test_redaction_warnings_and_ignored_runtime(self):
        empty = self.record()
        self.assertEqual([w["code"] for w in empty["issues"]], ["SESSION_REDACTION_EMPTY"])
        self.assertIn("SESSION_REDACTION_EMPTY", [i["code"] for i in self.call("check")["issues"]])
        self.profile(top=f'secret_env = ["{SECRET_ENV}"]')
        with mock.patch.dict(os.environ, {SECRET_ENV: ""}):
            unset = self.record()
        self.assertEqual([w["code"] for w in unset["issues"]], ["SESSION_SECRET_UNSET", "SESSION_REDACTION_EMPTY"])
        ignore = self.root / ".gitignore"
        ignore.write_text(ignore.read_text().replace(".roclec/runtime/\n", ""))
        before = files(self.root)
        self.record(expect=2, issue="RUNTIME_NOT_IGNORED")
        self.assertEqual(files(self.root), before)

    def test_stray_session_files_and_tampered_kind(self):
        session = self.record()["data"]["evidence"]
        orphan = self.root / ".roclec/runtime/sessions/EVD-01ARZ3NDEKTSV4RRFFQ69G5FAV"
        orphan.mkdir()
        (orphan / "lost.jsonl").write_bytes(b"lost")
        self.call("check", issue="SESSION_RAW_ORPHAN")
        stray = self.root / ".roclec/evidence/EVD-01ARZ3NDEKTSV4RRFFQ69G5FAV.session"
        stray.write_bytes(b"stray")
        self.call("check", expect=1, issue="INVALID_REFERENCE")
        stray.unlink()
        # A copy without redactions must equal the original, even when record and copy are rewritten together.
        stored = self.stored(session["id"])
        self.assertEqual(stored["transcript"]["redactions"], 0)
        forged = b"forged"
        stored["transcript"]["versioned_sha256"] = hashlib.sha256(forged).hexdigest()
        from roclec_spec_kit.model import digest
        stored["digest"] = digest({k: v for k, v in stored.items() if k != "digest"})
        put_json(self.root / f".roclec/evidence/{session['id']}.json", stored)
        (self.root / f".roclec/evidence/{session['id']}.session").write_bytes(forged)
        self.call("check", expect=1, issue="HASH_MISMATCH")
        # Relabelling a report as a session cannot hide it from gates.
        run = self.call("run", "verify", "CHG-001", "--component", "engine", "--base", self.base, *PRODUCER)["data"]["run"]
        observation = self.inputs / "observation.json"
        put_json(observation, {"model_schema": 2, "kind": "manual", "change_id": "CHG-001", "component": "engine",
                               "run_id": run["id"], "candidate_digest": run["candidate"]["inputs_digest"],
                               "actor": "Synthetic observer", "context": "Session fixture", "outcome": "pass",
                               "acceptance_ids": ["AC-001"], "checks": ["Observed test"], "limitations": [], "findings": []})
        report = self.call("evidence", "record", "--file", observation)["data"]["evidence"]
        path = self.root / f".roclec/evidence/{report['id']}.json"
        put_json(path, {**self.stored(report["id"]), "kind": "agent-session"})
        verifier = Verification(Kernel(load_profile(self.root)))
        with self.assertRaises(Exception) as caught:
            verifier.evidence("CHG-001", "engine")
        self.assertEqual(caught.exception.issue["code"], "HASH_MISMATCH")

    def test_redaction_requires_utf8_and_names_the_local_policy(self):
        before = files(self.root)
        payload = self.record(content=b"\xff\xfe binary", expect=2, issue="INVALID_INPUT")
        self.assertIn('storage = "local"', payload["issues"][0]["remediation"])
        self.assertEqual(files(self.root), before)

    def test_raw_and_local_storage_policies(self):
        self.profile(table='storage = "versioned-raw"')
        raw = self.record()
        session = raw["data"]["evidence"]
        self.assertEqual((self.root / f".roclec/evidence/{session['id']}.session").read_bytes(), TRANSCRIPT)
        self.assertEqual(session["transcript"]["versioned_sha256"], session["transcript"]["sha256"])
        self.assertNotIn("redactions", session["transcript"])
        warnings = self.check_issues()
        self.assertEqual([(i["code"], i["severity"]) for i in warnings], [("SESSION_RAW_VERSIONED", "warning")])
        profile = self.root / ".roclec/project.toml"
        profile.write_text(profile.read_text().replace('"versioned-raw"', '"local"'))
        local = self.record(content=b"\xff binary is fine locally")["data"]["evidence"]
        self.assertIsNone(local["transcript"]["versioned_sha256"])
        self.assertFalse((self.root / f".roclec/evidence/{local['id']}.session").exists())
        self.assertEqual(self.check_issues(), [])
        stray = self.root / f".roclec/evidence/{local['id']}.session"
        stray.write_bytes(b"stray")
        self.call("check", expect=1, issue="INVALID_REFERENCE")

    def test_original_and_copy_integrity_in_check(self):
        session = self.record()["data"]["evidence"]
        raw = self.root / f".roclec/runtime/sessions/{session['id']}/session.jsonl"
        copy = self.root / f".roclec/evidence/{session['id']}.session"
        raw.unlink()
        unavailable = self.check_issues(issue="SESSION_RAW_UNAVAILABLE")
        self.assertEqual([i["severity"] for i in unavailable], ["warning"])
        raw.write_bytes(TRANSCRIPT + b"edited")
        self.call("check", expect=1, issue="HASH_MISMATCH")
        raw.write_bytes(TRANSCRIPT)
        self.assertEqual(self.check_issues(), [])
        saved = copy.read_bytes()
        copy.write_bytes(saved + b"edited")
        self.call("check", expect=1, issue="HASH_MISMATCH")
        copy.write_bytes(saved)
        record = self.root / f".roclec/evidence/{session['id']}.json"
        stored = self.stored(session["id"])
        put_json(record, {**stored, "actor": "Someone else"})
        self.call("check", expect=1, issue="HASH_MISMATCH")

    def test_scopes_for_foundation_release_and_change_stages(self):
        foundation = self.record(self.meta(stage="foundation", change_id=None, component=None, subject="architecture",
                                           role="coordinator"))["data"]["evidence"]
        release = self.record(self.meta(stage="release", change_id=None, component=None,
                                        release={"component": "engine", "version": "v1.0.0"}))["data"]["evidence"]
        define = self.record(self.meta(stage="define", component=None, role="specifier"))["data"]["evidence"]
        self.assertNotIn("component", define)
        self.assertEqual(self.check_issues(), [])
        verifier = Verification(Kernel(load_profile(self.root)))
        self.assertEqual([s["id"] for s in verifier.sessions()], sorted([foundation["id"], release["id"], define["id"]]))
        self.assertEqual([s["id"] for s in verifier.sessions("CHG-001")], [define["id"]])
        self.assertEqual(verifier.sessions("CHG-001", "engine"), [])
        self.record(self.meta(stage="release", change_id=None, component=None,
                              release={"component": "engine", "version": "v9.0.0"}), expect=2, issue="INVALID_REFERENCE")
        self.record(self.meta(stage="foundation", change_id=None, component=None, subject="missing-reference"),
                    expect=2, issue="INVALID_REFERENCE")

    def test_plan_session_may_precede_the_chore_it_drafts(self):
        # A chore's plan is its bundle: its plan session, like a define session, precedes the import.
        plan = self.record(self.meta(stage="plan", role="implementer", change_id="CHG-101", component=None))["data"]["evidence"]
        self.record(self.meta(stage="plan", change_id="CHG-102", component="engine"), expect=2, issue="INVALID_INPUT")
        self.record(self.meta(stage="implement", change_id="CHG-103"), expect=2, issue="INVALID_REFERENCE")
        source = self.workspace / "chore"
        record = chore_bundle(source, change_id="CHG-101", mutate=lambda s: s.update(sessions=[plan["id"]]))
        self.call("change", "new", "--file", source / "change.json")
        self.assertEqual(json.loads((self.root / ".roclec/changes/CHG-101/change.json").read_text())["semantic"]["sessions"],
                         [plan["id"]])
        self.assertEqual(record["kind"], "chore")

    def test_declared_agent_roles_from_the_flow(self):
        flow = self.root / ".roclec/flow.toml"
        flow.write_text(flow.read_text() + '\n[roles.analyst]\nkind = "agent"\n')
        (self.root / ".claude/agents").mkdir(parents=True)
        (self.root / ".claude/agents/analyst.md").write_text("Fixture binding\n")
        self.record(self.meta(role="analyst"))
        self.record(self.meta(role="owner"), expect=2, issue="INVALID_REFERENCE")

    def test_invalid_metadata_and_arguments_are_rejected_without_writes(self):
        source = self.workspace / "engine-only"
        bundle(source, change_id="CHG-002", components=("engine",), kind="refactor")
        self.call("change", "new", "--file", source / "change.json")
        before = files(self.root)
        cases = {
            "unknown stage": (self.meta(stage="deploy"), "INVALID_INPUT", "Unknown session stage"),
            "foundation without subject": (self.meta(stage="foundation", change_id=None, component=None), "INVALID_INPUT",
                                           "Invalid scope for a foundation session"),
            "component outside scope": (self.meta(change_id="CHG-002", component="viewer"), "INVALID_REFERENCE",
                                        "Session component is outside the change"),
            "component required": (self.meta(component=None), "INVALID_INPUT", "Invalid scope for a implement session"),
            "unknown change": (self.meta(change_id="CHG-404"), "INVALID_REFERENCE", "Unknown change"),
            "ended before started": (self.meta(ended_at="2026-01-31T08:59:59Z"), "INVALID_INPUT", "ended_at precedes started_at"),
            "non-UTC timestamp": (self.meta(started_at="2026-01-31T09:00:00+01:00"), "INVALID_INPUT", "started_at must be a UTC"),
            "unknown role": (self.meta(role="ghost"), "INVALID_REFERENCE", "Unknown agent role"),
            "kind declared": (self.meta(kind="agent-session"), "INVALID_INPUT", "must not declare kind"),
            "multi-line actor": (self.meta(actor="Fixture\nagent"), "INVALID_INPUT", "actor must be non-empty single-line"),
            "subject outside foundation": (self.meta(subject="architecture"), "INVALID_INPUT", "Invalid scope for a implement"),
            "missing host": ({k: v for k, v in self.meta().items() if k != "host"}, "INVALID_INPUT", "Missing or unknown fields"),
        }
        for label, (meta, code, message) in cases.items():
            with self.subTest(label):
                issue = self.record(meta, expect=2, issue=code)["issues"][0]
                self.assertIn(message, issue["message"])
                self.assertTrue(issue["remediation"] or message == "Missing or unknown fields", issue)
        transcript = self.inputs / "loose.jsonl"
        transcript.write_bytes(TRANSCRIPT)
        put_json(self.inputs / "meta.json", self.meta())
        self.call("evidence", "record", "--file", self.inputs / "meta.json", "--transcript", transcript, expect=2, issue="INVALID_INPUT")
        self.call("evidence", "record", "--file", self.inputs / "meta.json", "--kind", "agent-session", expect=2, issue="INVALID_INPUT")
        put_json(self.inputs / "typed.json", {**self.meta(), "kind": "agent-session"})
        self.call("evidence", "record", "--file", self.inputs / "typed.json", expect=2, issue="INVALID_INPUT")
        self.record(name=".hidden.jsonl", expect=2, issue="INVALID_INPUT")
        self.record(content=b"", expect=2, issue="INVALID_INPUT")
        self.assertEqual(files(self.root), before)

    def test_refused_write_leaves_no_original_and_interrupted_write_recovers(self):
        from roclec_spec_kit.model import ModelError
        from roclec_spec_kit.store import Store
        before = files(self.root)
        def refuse(*args, **kwargs):
            raise ModelError("BASE_CONFLICT", "Project inputs changed during validation", exit_code=3)
        with mock.patch.object(Store, "apply", refuse):
            self.record(expect=3, issue="BASE_CONFLICT")
        self.assertEqual(files(self.root), before)
        self.assertEqual(list((self.root / ".roclec/runtime/sessions").iterdir()), [])
        def interrupt(store, journal):
            raise OSError("simulated crash after journaling")
        with mock.patch.object(Store, "_finish", interrupt):
            self.record(expect=4, issue="IO_ERROR")
        journals = list((self.root / ".roclec/runtime").glob("*.json"))
        self.assertEqual(len(journals), 1)
        [kept] = (self.root / ".roclec/runtime/sessions").iterdir()
        self.assertEqual((kept / "session.jsonl").read_bytes(), TRANSCRIPT)
        self.call("operation", "recover", journals[0].stem)
        self.assertEqual(self.stored(kept.name)["transcript"]["sha256"], hashlib.sha256(TRANSCRIPT).hexdigest())
        self.assertEqual(self.check_issues(), [])

    def test_existing_evidence_flows_ignore_sessions(self):
        session = self.record()["data"]["evidence"]
        run = self.call("run", "verify", "CHG-001", "--component", "engine", "--base", self.base, *PRODUCER)["data"]["run"]
        observation = self.inputs / "observation.json"
        put_json(observation, {"model_schema": 2, "kind": "manual", "change_id": "CHG-001", "component": "engine",
                               "run_id": run["id"], "candidate_digest": run["candidate"]["inputs_digest"],
                               "actor": "Synthetic observer", "context": "Session fixture", "outcome": "pass",
                               "acceptance_ids": ["AC-001"], "checks": ["Observed test"], "limitations": [], "findings": []})
        report = self.call("evidence", "record", "--file", observation)["data"]["evidence"]
        self.assertEqual(report["supersedes"], [])
        self.assertEqual(self.call("list", "findings", "--change", "CHG-001")["data"]["findings"], [])
        self.call("inspect", "--change", "CHG-001", "--deep")
        self.call("check", "--change", "CHG-001", "--component", "engine", "--gate", "verify")
        self.assertEqual(self.check_issues(), [])
        verifier = Verification(Kernel(load_profile(self.root)))
        self.assertEqual([r["id"] for r in verifier.evidence("CHG-001", "engine")], [report["id"]])
        from roclec_spec_kit.viewer.reader import Reader
        reports = Reader(self.root).reports()
        self.assertEqual((sorted(reports["reports"]), reports["invalid"]), ([report["id"]], []))
        self.assertNotIn(session["id"], reports["reports"])


if __name__ == "__main__":
    unittest.main()
