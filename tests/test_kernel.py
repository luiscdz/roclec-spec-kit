from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from roclec_spec_kit.cli import main
from roclec_spec_kit.config import load_profile
from roclec_spec_kit.kernel import Kernel
from roclec_spec_kit.model import ModelError
from roclec_spec_kit.store import Store
from scripts.c1_scenarios import (bundle, digest, file_hash, foundation, init_trunk, profile, put_json,
                                 rejection_scenarios, scenarios, seed_current, seed_publication, snapshot, tree, write_snapshot)


def invoke(argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(argv)
    return SimpleNamespace(returncode=code, stdout=stdout.getvalue(), stderr=stderr.getvalue())


class KernelTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.root = self.workspace / "project"
        init_trunk(self.root)
        config = self.workspace / "profile.toml"
        profile(config)
        result = invoke(["--json", "init", str(self.root), "--profile", str(config)])
        self.assertEqual(result.returncode, 0, result.stdout)

    def call(self, *args, expect=0, issue=None):
        before = tree(self.root)
        result = invoke(["--project", str(self.root), "--json", *args])
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        if issue:
            self.assertIn(issue, [i["code"] for i in payload["issues"]], result.stdout)
        if expect in (1, 2, 3):
            self.assertEqual(tree(self.root), before, "Rejected operation mutated consumer")
        return payload

    def seed(self):
        current = snapshot()
        seed_current(self.root, current)
        return current

    def check_case(self, name, condition, detail=""):
        self.assertTrue(condition, f"{name}: {detail}")

    def test_full_consumer_scenarios(self):
        # Same scenarios are subsequently run using only the installed wheel CLI.
        scenarios(self.workspace, invoke, self.check_case)

    def test_human_rejection_consumer_scenarios(self):
        def inject(code, argv):
            with mock.patch("sys.argv", ["roclec", *argv]):
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as exited:
                        exec(code, {})
                return SimpleNamespace(returncode=exited.exception.code,
                                       stdout=stdout.getvalue(), stderr=stderr.getvalue())

        rejection_scenarios(self.workspace, invoke, self.check_case, inject)

    def test_foundation_authoring_binds_agreement_to_source_bytes(self):
        source = self.root / "foundation.md"
        source.write_text("# Foundation\n", encoding="utf-8")
        for role in ("context", "principles", "architecture", "stack", "engineering", "verification"):
            self.call("reference", "add", role, "--path", "foundation.md", "--role", role, "--component", "engine")
            self.call("foundation", "agree", "--ref", role, "--actor", "Maintainer", "--reason", "Reviewed")
        self.call("foundation", "check", "--component", "engine")
        source.write_text("# Revised foundation\n", encoding="utf-8")
        self.call("foundation", "check", "--component", "engine", expect=1, issue="FOUNDATION_INCOMPLETE")

    def test_seal_generates_an_importable_bundle_without_mutating_project(self):
        folder = self.workspace / "unsealed"
        path = folder / "change.json"
        record = bundle(folder)
        record.pop("proposal_digest")
        record["semantic"].pop("files")
        entry = record["semantic"]["proposed"][0]
        revision = entry.pop("revision")
        parent = folder / "proposed/CAP-001"
        draft = parent / "draft"
        (parent / revision).rename(draft)
        descriptor = json.loads((draft / "contract.json").read_bytes())
        descriptor.pop("files")
        put_json(draft / "contract.json", descriptor)
        put_json(path, record)
        before = tree(self.root)
        preview = self.call("change", "seal", str(folder), "--check")["data"]
        self.assertIn("change.json", preview["changed"])
        self.assertNotIn("proposal_digest", json.loads(path.read_bytes()))
        self.call("change", "seal", str(folder))
        sealed = path.read_bytes()
        self.assertEqual(self.call("change", "seal", str(folder))["data"]["changed"], [])
        self.assertEqual(sealed, path.read_bytes())
        self.assertEqual(before, tree(self.root))
        self.call("change", "new", "--file", str(path))
        self.assertEqual(self.call("status")["data"]["components"]["engine"]["changes"][0]["status"], "draft")
        self.call("change", "approve", record["id"], "--digest", preview["proposal_digest"],
                  "--actor", "Maintainer", "--reason", "Reviewed")
        self.call("change", "seal", str(folder), expect=3, issue="OPERATION_CONFLICT")
        self.assertEqual(sealed, path.read_bytes())

    def test_internal_errors_have_a_distinct_code_and_opt_in_trace(self):
        with mock.patch("roclec_spec_kit.native_cli.execute", side_effect=TypeError("test detail")):
            args = ["--project", str(self.root), "--json"]
            for flags in ([], ["--debug"]):
                result = invoke([*args, *flags, "check"])
                self.assertEqual(result.returncode, 70)
                self.assertEqual(json.loads(result.stdout)["issues"][0]["code"], "INTERNAL_ERROR")
                self.assertEqual("TypeError: test detail" in result.stderr, bool(flags))

    def test_documented_bootstrap_bundle_is_importable(self):
        example = Path(__file__).resolve().parents[1] / "docs/examples/c1"
        root = self.workspace / "documented-consumer"
        init_trunk(root)
        result = invoke(["--json", "init", str(root), "--profile", str(example / "profile.toml")])
        self.assertEqual(result.returncode, 0, result.stdout)
        result = invoke(["--project", str(root), "--json", "change", "new", "--file", str(example / "change/change.json")])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)["data"]["status"], "draft")

    def test_untrusted_bundles_and_descriptors_reject_without_writes(self):
        cases = ("hash", "duplicate-ac", "traversal", "symlink", "unknown-field", "duplicate-json")
        for number, case in enumerate(cases, 10):
            with self.subTest(case=case):
                folder = self.workspace / case
                target = snapshot()
                if case == "duplicate-ac":
                    target["descriptor"]["acceptance"].append(target["descriptor"]["acceptance"][0].copy())
                    target["revision"] = digest(target["descriptor"])
                if case == "unknown-field":
                    target["descriptor"]["unexpected"] = True
                    target["revision"] = digest(target["descriptor"])
                record = bundle(folder, change_id=f"CHG-{number:03}", target=target)
                content_path = folder / "proposed/CAP-001" / target["revision"] / "requirements/REQ-001.md"
                if case == "hash":
                    content_path.write_text("Changed content without updating its digest\n")
                elif case == "symlink":
                    outside = self.workspace / "outside.md"
                    outside.write_bytes(content_path.read_bytes())
                    content_path.unlink()
                    content_path.symlink_to(outside)
                elif case == "traversal":
                    descriptor = target["descriptor"]
                    descriptor["requirements"][0]["statement"] = "../../outside.md"
                    descriptor["files"] = {"../../outside.md": descriptor["files"]["requirements/REQ-001.md"],
                                           **{p: h for p, h in descriptor["files"].items() if p.startswith("acceptance/")}}
                    old_dir = folder / "proposed/CAP-001" / target["revision"]
                    target["revision"] = digest(descriptor)
                    new_dir = old_dir.with_name(target["revision"])
                    old_dir.rename(new_dir)
                    put_json(new_dir / "contract.json", descriptor)
                    record["semantic"]["proposed"][0]["revision"] = target["revision"]
                    record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
                    put_json(folder / "change.json", record)
                elif case == "duplicate-json":
                    path = folder / "change.json"
                    path.write_text(path.read_text().replace('"model_schema": 2', '"model_schema": 2, "model_schema": 2', 1))
                before = tree(self.root)
                result = invoke(["--project", str(self.root), "--json", "change", "new", "--file", str(folder / "change.json")])
                self.assertIn(result.returncode, (1, 2), result.stdout)
                self.assertEqual(tree(self.root), before)

    def test_changed_behavior_needs_new_ac_and_other_obligation_needs_new_identity(self):
        base = self.seed()
        folder = self.workspace / "reused-ac"
        target = snapshot(behavior="two labeled fields")
        bundle(folder, change_id="CHG-010", base=base, target=target)
        self.call("change", "new", "--file", str(folder / "change.json"), expect=1, issue="INVALID_REFERENCE")
        folder = self.workspace / "stolen-ac"
        target = snapshot(req="REQ-002")
        record = bundle(folder, change_id="CHG-011", base=base, target=target)
        record["semantic"]["deltas"] = [{"op": "replace", "capability_id": "CAP-001",
                                         "old_requirement": "REQ-001", "new_requirement": "REQ-002"}]
        record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
        put_json(folder / "change.json", record)
        self.call("change", "new", "--file", str(folder / "change.json"), expect=1, issue="ID_COLLISION")

    def test_foreign_ac_and_obsolete_bases_cannot_be_claimed(self):
        base = self.seed()
        folder = self.workspace / "foreign-ac"
        record = bundle(folder, change_id="CHG-010", base=base, target=snapshot(ac="AC-002", behavior="two fields"))
        record["semantic"]["deltas"][0]["retire_acceptance_ids"] = ["AC-999"]
        record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
        put_json(folder / "change.json", record)
        self.call("change", "new", "--file", str(folder / "change.json"), expect=1, issue="INVALID_REFERENCE")
        folder = self.workspace / "stale"
        bundle(folder, change_id="CHG-011", base=base, target=snapshot(ac="AC-003", behavior="two fields"))
        seed_current(self.root, snapshot(ac="AC-004", behavior="another form"), names=("engine",))
        self.call("change", "new", "--file", str(folder / "change.json"), expect=3, issue="BASE_CONFLICT")

    def test_future_gates_do_not_report_success(self):
        for args in (("release", "prepare", "engine", "v0.1.0"),):
            with self.subTest(args=args):
                self.call(*args, expect=2, issue="INVALID_INPUT")
        for args in (("run", "verify", "CHG-001"), ("integrate", "prepare", "CHG-001")):
            self.call(*args, expect=2, issue="INVALID_INPUT")
        self.call("operation", "apply", "plan.json", expect=1, issue="INVALID_REFERENCE")

    def test_local_partial_write_recovery_and_divergence(self):
        folder = self.workspace / "interrupted"
        bundle(folder)
        original = Store._atomic
        calls = []

        def fail_after_one_write(store, relative, content):
            calls.append(relative)
            if len(calls) == 3:
                raise OSError("Injected disk error")
            return original(store, relative, content)

        with mock.patch.object(Store, "_atomic", fail_after_one_write):
            result = self.call("change", "new", "--file", str(folder / "change.json"), expect=4, issue="IO_PARTIAL")
        operation_id = result["data"]["operation_id"]
        self.assertTrue(result["data"]["partial"])
        self.call("check", expect=4, issue="IO_PARTIAL")
        index = self.root / ".roclec/current.json"
        original_index = index.read_bytes()
        index.write_bytes(original_index + b"\n")
        self.call("operation", "recover", operation_id, expect=3, issue="OPERATION_CONFLICT")
        index.write_bytes(original_index)
        journal = self.call("operation", "inspect", operation_id)["data"]["operation"]
        changed_path = self.root / next(p for p in journal["writes"] if (self.root / p).exists())
        old_bytes = changed_path.read_bytes()
        changed_path.write_bytes(b"Diverged after interruption\n")
        self.call("operation", "recover", operation_id, expect=3, issue="OPERATION_CONFLICT")
        changed_path.write_bytes(old_bytes)
        self.call("operation", "recover", operation_id)
        after = tree(self.root)
        self.call("operation", "recover", operation_id)
        self.assertEqual(tree(self.root), after)
        self.call("check")

    def test_interrupted_initialization_recovers_without_a_readable_profile(self):
        root = self.workspace / "partial-init"
        init_trunk(root)
        original = Store._atomic
        calls = []

        def interrupt_before_profile(store, relative, content):
            calls.append(relative)
            if len(calls) == 2:
                raise KeyboardInterrupt()
            return original(store, relative, content)

        with mock.patch.object(Store, "_atomic", interrupt_before_profile):
            result = invoke(["--json", "init", str(root), "--profile", str(self.workspace / "profile.toml")])
        self.assertEqual(result.returncode, 130, result.stdout)
        self.assertFalse((root / ".roclec/project.toml").exists())
        operation_id = json.loads(result.stdout)["data"]["operation_id"]
        result = invoke(["--project", str(root), "--json", "operation", "recover", operation_id])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(invoke(["--project", str(root), "--json", "check"]).returncode, 0)

    def test_concurrent_precondition_and_recovery_namespace_guards(self):
        store = Store(self.root)
        token = store.token()
        (self.root / ".roclec/concurrent.md").write_text("Changed after preflight\n")
        before = tree(self.root)
        with self.assertRaises(ModelError) as caught:
            store.apply("views", {"sources": {}}, {"specs/capabilities/CAP-001.md": b"view"}, token)
        self.assertEqual(caught.exception.issue["code"], "BASE_CONFLICT")
        self.assertEqual(tree(self.root), before)
        with self.assertRaises(ModelError):
            store.apply("views", {}, {"AGENTS.md": b"overwrite"}, store.token())
        self.assertEqual(tree(self.root), before)

    def test_publication_immutability_and_legacy_normalization(self):
        base = self.seed()
        seed_publication(self.root, "v1.2", base)
        data = self.call("inspect", "--capability", "CAP-001", "--component", "engine", "--at", "v1.2.0")["data"]
        self.assertEqual(data["components"]["engine"]["revision"], base["revision"])
        record = {"model_schema": 2, "component": "engine", "version": "v1.2.0", "kind": "release", "changes": [], "base_tag": None}
        put_json(self.root / ".roclec/releases/engine/v1.2.0/release.json", record)
        self.call("check", expect=1, issue="VERSION_INVALID")
        (self.root / ".roclec/releases/engine/v1.2.0/release.json").unlink()
        path = self.root / ".roclec/releases/engine/v1.2/release.json"
        edited = json.loads(path.read_text())
        edited["kind"] = "bugfix"
        put_json(path, edited)
        self.call("check", expect=1, issue="HASH_MISMATCH")

    def test_edited_proposal_reserves_new_ids_and_approved_snapshots_are_checked(self):
        base = self.seed()
        folder = self.workspace / "edit"
        record = bundle(folder, change_id="CHG-010", base=base, target=snapshot(ac="AC-002", behavior="two fields"))
        self.call("change", "new", "--file", str(folder / "change.json"))
        target = snapshot(ac="AC-003", behavior="two fields")
        stored = self.root / ".roclec/changes/CHG-010"
        write_snapshot(stored / "proposed/CAP-001" / target["revision"], target)
        record["semantic"]["proposed"][0]["revision"] = target["revision"]
        record["semantic"]["deltas"][0]["add_acceptance_ids"] = ["AC-003"]
        record["semantic"]["coverage"]["criteria"][0]["acceptance_ids"] = ["AC-003"]
        record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
        put_json(stored / "change.json", record)
        self.call("change", "approve", "CHG-010", "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "edited scope")
        competitor = self.workspace / "competitor"
        bundle(competitor, change_id="CHG-011", base=base, target=target)
        self.call("change", "new", "--file", str(competitor / "change.json"), expect=1, issue="ID_COLLISION")
        self.call("release", "plan", "engine", "v0.1.0", "--change", "CHG-010")
        archived = stored / "revisions" / record["proposal_digest"] / "proposal.md"
        archived.write_text(archived.read_text() + "Tampered history\n")
        self.call("inspect", "--release", "v0.1.0", "--component", "engine", expect=1, issue="HASH_MISMATCH")

    def test_foundation_freshness_and_cancel_before_unassigning_started_work(self):
        folder = self.workspace / "draft"
        record = bundle(folder)
        self.call("change", "new", "--file", str(folder / "change.json"))
        self.call("change", "approve", "CHG-001", "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "synthetic")
        self.call("release", "plan", "engine", "v0.1.0", "--change", "CHG-001")
        foundation(self.root)
        self.call("change", "start", "CHG-001", "--actor", "Fixture maintainer", "--component", "engine")
        self.call("release", "plan", "engine", "v0.1.0", "--clear", expect=1, issue="CHANGE_IN_PROGRESS")
        stored = self.root / ".roclec/changes/CHG-001"
        proposal = stored / "proposal.md"
        proposal.write_text(proposal.read_text() + "New approved presentation constraint.\n")
        record["semantic"]["files"]["proposal.md"] = file_hash(proposal.read_bytes())
        record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
        put_json(stored / "change.json", record)
        self.call("change", "approve", "CHG-001", "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "Updated intention")
        self.call("release", "plan", "engine", "v0.1.0", "--change", "CHG-001")
        self.call("change", "start", "CHG-001", "--actor", "Fixture maintainer", "--component", "engine")
        reference = self.root / "docs/reference.md"
        reference.write_text(reference.read_text() + "Changed architecture\n")
        self.call("foundation", "check", "--component", "engine", expect=1, issue="FOUNDATION_INCOMPLETE")
        self.call("change", "cancel", "CHG-001", "--actor", "fixture", "--reason", "Scope abandoned")
        self.call("release", "plan", "engine", "v0.1.0", "--clear")
        self.call("change", "approve", "CHG-001", "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "Retry", expect=1, issue="CHANGE_CANCELED")


if __name__ == "__main__":
    unittest.main()
