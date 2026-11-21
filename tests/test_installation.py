"""Native skills refresh: pruning retired files, edit detection and journaled deletions."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from roclec_spec_kit.model import ModelError, digest, encoded, sha
from roclec_spec_kit.store import Store
from scripts.c1_scenarios import put_json, tree
from scripts.c2_scenarios import commit, git, setup
from test_kernel import invoke

MARKER = "<!-- managed by roclec-spec-kit -->"
MANIFEST = ".roclec/installation.json"
RETIRED = ("roclec-retired/SKILL.md", "roclec-retired/references/note.md")
HOSTS = (".agents", ".claude")


class InstallationRefreshTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root, _ = setup(Path(temp.name) / "install", invoke, names=("engine",))
        self.install()

    def run_cli(self, *args):
        result = invoke(["--project", str(self.root), "--json", *args])
        return result.returncode, json.loads(result.stdout)

    def install(self, *args):
        code, payload = self.run_cli("skills", *args)
        self.assertEqual(code, 0, payload)
        return payload["data"]

    def rejected(self, issue, *args):
        before = tree(self.root)
        code, payload = self.run_cli("skills", *args)
        self.assertEqual(code, 1, payload)
        self.assertEqual(payload["issues"][0]["code"], issue, payload)
        self.assertEqual(tree(self.root), before, "a rejected refresh must not write")
        self.assertFalse(list((self.root / ".roclec/runtime").glob("*.json")), "no journal is left behind")
        return payload["issues"][0]

    def manifest(self):
        return json.loads((self.root / MANIFEST).read_text(encoding="utf-8"))

    def plant_retired(self, *, legacy=False):
        """Simulate a skill an earlier Roclec installed and the current assets no longer ship."""
        manifest = self.manifest()
        planted = []
        for host in HOSTS:
            for name in RETIRED:
                relative = f"{host}/skills/{name}"
                content = f"{MARKER}\n# Retired stage {name}\n".encode("utf-8")
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                manifest["files"][relative] = sha(content)
                manifest["managed"].append(relative)
                planted.append(relative)
        if legacy:
            del manifest["managed"]
        put_json(self.root / MANIFEST, manifest)
        return planted

    def test_retired_managed_files_are_pruned_on_both_hosts(self):
        planted = self.plant_retired()
        data = self.install()
        for relative in planted:
            self.assertFalse((self.root / relative).exists(), relative)
            self.assertIsNone(data["receipt"]["writes"][relative], "receipt records the deletion")
        for host in HOSTS:
            self.assertFalse((self.root / host / "skills/roclec-retired").exists(), "empty retired folder removed")
            self.assertTrue((self.root / host / "skills").is_dir(), "namespace root kept")
        manifest = self.manifest()
        self.assertFalse(set(planted) & (set(manifest["files"]) | set(manifest["managed"])))
        self.assertTrue((self.root / ".agents/skills/roclec-plan/SKILL.md").is_file())

    def test_manifest_without_managed_field_still_prunes_native_paths(self):
        planted = self.plant_retired(legacy=True)
        self.install()
        self.assertFalse(any((self.root / relative).exists() for relative in planted))
        self.assertIn("managed", self.manifest(), "refresh upgrades the manifest")

    def test_edited_retired_file_rejects_whole_refresh(self):
        planted = self.plant_retired()
        edited = self.root / planted[0]
        edited.write_bytes(edited.read_bytes() + b"Consumer note\n")
        manifest = (self.root / MANIFEST).read_bytes()
        issue = self.rejected("MANAGED_FILE_EDITED")
        self.assertEqual(issue["actual"], [planted[0]])
        self.assertEqual(issue["path"], planted[0])
        self.assertIn("git checkout --", issue["remediation"])
        self.assertEqual((self.root / MANIFEST).read_bytes(), manifest)
        self.assertTrue(all((self.root / relative).is_file() for relative in planted), "nothing pruned")
        edited.unlink()  # Deleting the edited copy accepts its retirement.
        self.install()
        self.assertFalse(any((self.root / relative).exists() for relative in planted))

    def test_edited_shipped_files_are_listed_and_never_overwritten(self):
        self.install()  # Steady state: an identical later refresh would replay this receipt.
        commit(self.root)
        skill = ".claude/skills/roclec-plan/SKILL.md"
        guide = ".roclec/workflow.md"
        for relative in (skill, guide):
            path = self.root / relative
            path.write_bytes(path.read_bytes() + b"\nConsumer addition that keeps the marker.\n")
        issue = self.rejected("MANAGED_FILE_EDITED")
        self.assertEqual(issue["actual"], sorted([skill, guide]))
        git(self.root, "checkout", "--", skill)
        issue = self.rejected("MANAGED_FILE_EDITED")
        self.assertEqual(issue["actual"], [guide])
        (self.root / guide).unlink()  # Accept the refreshed version.
        self.install()
        self.assertNotIn(b"Consumer addition", (self.root / guide).read_bytes())
        self.assertEqual(git(self.root, "status", "--porcelain", "--", skill, guide), "")

    def test_deleted_managed_file_is_restored_even_when_the_state_recurs(self):
        self.install()
        commit(self.root)
        skill = self.root / ".claude/skills/roclec-ux/SKILL.md"
        original = skill.read_bytes()
        generations = set()
        for _ in range(2):
            skill.unlink()
            self.install()
            self.assertEqual(skill.read_bytes(), original)
            generations.add(self.manifest()["generation"])
            # Same tracked bytes again; only the receipts confirmed since differ.
            git(self.root, "checkout", "--", ".")
        self.assertEqual(len(generations), 2)

    def test_unmarked_overwrite_still_reports_unmanaged_file(self):
        path = self.root / ".agents/skills/roclec-plan/SKILL.md"
        path.write_bytes(b"# Consumer-owned skill\n")
        self.rejected("UNMANAGED_FILE")

    def test_consumer_owned_files_survive_refresh(self):
        template = self.root / ".roclec/templates/plan-template.md"
        constitution = self.root / ".roclec/constitution.md"
        ignore = self.root / ".gitignore"
        agents = self.root / "AGENTS.md"
        template.write_bytes(b"# Consumer plan\n")
        constitution.write_bytes(b"# Consumer principles\n")
        ignore.write_bytes(ignore.read_bytes() + b"local-cache/\n")
        agents.write_text("# Consumer header\n\n" + agents.read_text(encoding="utf-8") + "\nConsumer footer\n", encoding="utf-8")
        self.install()
        self.assertEqual(template.read_bytes(), b"# Consumer plan\n")
        self.assertEqual(constitution.read_bytes(), b"# Consumer principles\n")
        self.assertTrue(ignore.read_bytes().endswith(b"local-cache/\n"))
        text = agents.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Consumer header\n") and text.endswith("\nConsumer footer\n"))
        self.assertEqual(text.count("<!-- roclec-spec-kit:begin -->"), 1)

    def test_consumer_skills_are_not_pruned_even_if_a_manifest_names_them(self):
        own = self.root / ".agents/skills/consumer-own/SKILL.md"
        named = self.root / ".claude/skills/roclec-local/SKILL.md"
        for path in (own, named):
            path.parent.mkdir(parents=True)
            path.write_bytes(b"# Consumer skill\n")
        manifest = self.manifest()
        template = ".roclec/templates/plan-template.md"
        # Only native Roclec paths may be pruned, whatever the manifest lists.
        for relative in (".agents/skills/consumer-own/SKILL.md", template):
            manifest["files"][relative] = sha((self.root / relative).read_bytes())
            manifest["managed"].append(relative)
        put_json(self.root / MANIFEST, manifest)
        self.install()
        self.assertEqual(own.read_bytes(), b"# Consumer skill\n")
        self.assertEqual(named.read_bytes(), b"# Consumer skill\n")
        self.assertTrue((self.root / template).is_file())

    def test_without_previous_manifest_marker_rule_applies_and_nothing_is_pruned(self):
        for state in ("missing", "invalid"):
            with self.subTest(state=state):
                planted = self.plant_retired()
                skill = self.root / ".agents/skills/roclec-plan/SKILL.md"
                skill.write_bytes(skill.read_bytes() + b"\nMarked consumer edit.\n")
                if state == "missing":
                    (self.root / MANIFEST).unlink()
                else:
                    (self.root / MANIFEST).write_text("{not json", encoding="utf-8")
                self.install()
                self.assertTrue(all((self.root / relative).is_file() for relative in planted), "first install prunes nothing")
                self.assertNotIn(b"Marked consumer edit.", skill.read_bytes(), "marker rule overwrites as before")
                for host in HOSTS:
                    shutil.rmtree(self.root / host / "skills/roclec-retired")
                self.install()

    def test_adapter_entries_in_previous_manifest_are_never_pruned_or_flagged(self):
        manifest = self.manifest()
        adapter = {".agents/skills/speckit-plan/SKILL.md": b"# alias\n", ".claude/skills/speckit-plan/SKILL.md": b"# alias\n",
                   ".claude/commands/speckit.plan.md": b"# command\n", ".codex/prompts/speckit.plan.md": b"# prompt\n",
                   ".specify/presets/roclec/preset.yml": b"{}\n"}
        for relative, content in adapter.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            manifest["files"][relative] = sha(content)
        manifest["adapter"] = True
        (self.root / ".claude/commands/speckit.plan.md").write_bytes(b"# command regenerated by spec-kit\n")
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                current = dict(manifest)
                if legacy:
                    current["files"] = {**manifest["files"], **{p: sha(b"x") for p in adapter}}
                    current.pop("managed")
                put_json(self.root / MANIFEST, current)
                self.install()
                self.assertTrue(all((self.root / relative).is_file() for relative in adapter))

    def test_repeat_refresh_is_idempotent(self):
        first = self.install()
        before = tree(self.root)
        second = self.install()
        self.assertEqual(first["receipt"]["operation_id"], second["receipt"]["operation_id"])
        self.assertEqual(tree(self.root), before)

    @unittest.skipUnless(shutil.which("specify"), "specify-cli is optional")
    def test_skills_after_speckit_keeps_adapter_files(self):
        result = subprocess.run(["specify", "version"], capture_output=True, text=True)
        if "0.13." not in result.stdout:
            self.skipTest("specify-cli 0.13.x is required by the adapter")
        for integration in ("codex", "claude"):
            init = subprocess.run(["specify", "init", "--here", "--integration", integration, "--ignore-agent-tools", "--force"],
                                  cwd=self.root, capture_output=True, text=True, timeout=120)
            self.assertEqual(init.returncode, 0, init.stdout + init.stderr)
            self.install()  # Not an adapter install yet: native refresh.
            code, payload = self.run_cli("speckit")
            self.assertEqual(code, 0, payload)
        adapter = sorted(p for p in self.manifest()["files"] if not p.startswith((".agents/skills/roclec-", ".claude/skills/roclec-", ".roclec/"))
                         and p not in ("AGENTS.md", "CLAUDE.md", ".gitignore"))
        self.assertTrue(any(p.startswith(".specify/") for p in adapter) and any("/skills/speckit-" in p for p in adapter), adapter)
        snapshot = {p: v for p, v in tree(self.root).items() if p.startswith((".specify/", ".codex/", ".claude/commands/"))
                    or "/skills/speckit-" in p}
        self.install()
        self.install()
        after = tree(self.root)
        self.assertEqual({p: after.get(p) for p in snapshot}, snapshot)


class StoreDeletionTest(unittest.TestCase):
    DELETED = ".agents/skills/roclec-retired/references/note.md"
    WRITTEN = ".roclec/installation.json"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.store = Store(self.root)
        self.old = b"retired bytes\n"
        (self.root / self.DELETED).parent.mkdir(parents=True)
        (self.root / self.DELETED).write_bytes(self.old)
        (self.root / ".agents/skills/roclec-keep").mkdir()

    def apply(self):
        return self.store.apply("skills-install", {"version": "test"}, {self.WRITTEN: b"{}\n", self.DELETED: None}, self.store.token())

    def interrupted(self, target, condition):
        original = getattr(Store, target)
        def fail(store, relative, *args):
            if condition(relative):
                raise OSError("fixture interruption")
            return original(store, relative, *args)
        with mock.patch.object(Store, target, fail), self.assertRaises(ModelError) as caught:
            self.apply()
        self.assertEqual(caught.exception.issue["code"], "IO_PARTIAL")
        return caught.exception.operation_id

    def assert_completed(self, receipt):
        self.assertIsNone(receipt["writes"][self.DELETED])
        self.assertFalse((self.root / self.DELETED).exists())
        self.assertFalse((self.root / ".agents/skills/roclec-retired").exists())
        self.assertTrue((self.root / ".agents/skills/roclec-keep").is_dir())
        self.assertEqual((self.root / self.WRITTEN).read_bytes(), b"{}\n")
        self.assertFalse(list((self.root / ".roclec/runtime").glob("*.json")))

    def test_deletion_is_journaled_receipted_and_replayable(self):
        receipt = self.apply()
        self.assert_completed(receipt)
        stored = json.loads((self.root / f".roclec/receipts/{receipt['operation_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(stored, receipt)
        self.assertEqual(self.apply(), receipt, "replaying a confirmed deletion is idempotent")

    def test_interruption_before_deletion_recovers_forward(self):
        operation = self.interrupted("_remove", lambda relative: relative == self.DELETED)
        self.assertEqual((self.root / self.DELETED).read_bytes(), self.old)
        journal = json.loads((self.root / f".roclec/runtime/{operation}.json").read_text(encoding="utf-8"))
        self.assertIsNone(journal["writes"][self.DELETED])
        with self.assertRaises(ModelError) as blocked:
            self.store.healthy()
        self.assertEqual(blocked.exception.issue["code"], "IO_PARTIAL")
        self.assert_completed(self.store.recover(operation))

    def test_interruption_after_deletion_recovers_without_reapplying(self):
        operation = self.interrupted("_atomic", lambda relative: relative.startswith(".roclec/receipts/"))
        self.assertFalse((self.root / self.DELETED).exists())
        self.assert_completed(self.store.recover(operation))

    def test_recovery_rejects_a_recreated_deleted_path(self):
        operation = self.interrupted("_atomic", lambda relative: relative.startswith(".roclec/receipts/"))
        (self.root / self.DELETED).parent.mkdir(parents=True, exist_ok=True)
        (self.root / self.DELETED).write_bytes(b"consumer recreated it\n")
        with self.assertRaises(ModelError) as caught:
            self.store.recover(operation)
        self.assertEqual(caught.exception.issue["code"], "OPERATION_CONFLICT")
        self.assertEqual((self.root / self.DELETED).read_bytes(), b"consumer recreated it\n")
        (self.root / self.DELETED).unlink()
        self.assert_completed(self.store.recover(operation))

    def test_deletions_respect_kind_and_namespace(self):
        before = tree(self.root)
        # evidence-record has a valid namespace here; only the deletion is refused.
        cases = (("evidence-record", {"id": "EV-1"}, {".roclec/evidence/EV-1.json": None}),
                 ("skills-install", {}, {".roclec/project.toml": None, self.WRITTEN: b"{}\n"}))
        for kind, payload, writes in cases:
            with self.subTest(kind=kind), self.assertRaises(ModelError) as caught:
                self.store.apply(kind, payload, writes, self.store.token())
            self.assertEqual(caught.exception.issue["code"], "OPERATION_CONFLICT")
        self.assertEqual(tree(self.root), before)

    def test_rollback_restores_a_deleted_path(self):
        writes = {self.DELETED: None, self.WRITTEN: b"{}\n"}
        before = {self.DELETED: sha(self.old), self.WRITTEN: None}
        operation_id = digest({"kind": "skills-install", "payload": {}, "writes": {p: None if b is None else sha(b) for p, b in sorted(writes.items())}})
        journal = {"model_schema": 2, "operation_id": operation_id, "kind": "skills-install", "payload": {}, "before": before,
                   "guard": {}, "writes": {self.DELETED: None, self.WRITTEN: base64.b64encode(b"{}\n").decode("ascii")},
                   "prior": {self.DELETED: base64.b64encode(self.old).decode("ascii"), self.WRITTEN: None}}
        journal["journal_digest"] = digest(journal)
        runtime = self.root / ".roclec/runtime"
        runtime.mkdir(parents=True)
        (runtime / f"{operation_id}.json").write_bytes(encoded(journal))
        # Interrupted mid-operation: deletion done, the other write not yet.
        (self.root / self.DELETED).unlink()
        result = self.store._rollback(journal, writes)
        self.assertEqual(result["status"], "rolled-back")
        self.assertEqual((self.root / self.DELETED).read_bytes(), self.old)
        self.assertFalse((self.root / self.WRITTEN).exists())
        self.assertFalse((runtime / f"{operation_id}.json").exists())


if __name__ == "__main__":
    unittest.main()
