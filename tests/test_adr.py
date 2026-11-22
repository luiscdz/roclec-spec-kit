"""Consumer architecture decision records (ADR): profile, template and lifecycle."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from roclec_spec_kit.config import ADR_DEFAULTS, validate_profile
from roclec_spec_kit.model import ModelError
from scripts import c1_scenarios, c2_scenarios, c3_scenarios
from scripts.c1_scenarios import adr_markdown as scenario_adr_markdown, bundle, criteria, digest, file_hash, put_json, snapshot, tree
from scripts.c2_scenarios import PRODUCER, commit, git, setup
from test_kernel import invoke

TEMPLATE = ".roclec/templates/adr-template.md"


def profile_data(**extra):
    return {"schema": 3, "name": "adr", "trunk_ref": "refs/heads/main",
            "components": {"app": {"repo": ".", "user_facing": False, "inputs": ["src/**"], "generated": [],
                                   "verification": [], "target_ref": "refs/remotes/origin/main"}},
            **extra}


class AdrProfileTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def rejected(self, adr, code):
        with self.assertRaises(ModelError) as caught:
            validate_profile(self.root, profile_data(adr=adr))
        self.assertEqual(caught.exception.issue["code"], code)

    def test_profile_without_adr_uses_template_defaults(self):
        profile = validate_profile(self.root, profile_data())
        self.assertEqual(profile.adr, ADR_DEFAULTS)
        self.assertEqual(profile.adr["path"], "docs/adr")

    def test_defaults_match_the_shipped_template_sections(self):
        template = (Path(__file__).parents[1] / "src/roclec_spec_kit/assets/templates/adr-template.md").read_text(encoding="utf-8")
        headings = [line[3:].strip() for line in template.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, ADR_DEFAULTS["required_sections"])
        self.assertIn(ADR_DEFAULTS["options_section"], headings)

    def test_partial_table_overrides_only_its_keys(self):
        sections = ["Context", "Options", "Decision"]
        profile = validate_profile(self.root, profile_data(adr={"path": "architecture/decisions",
                                                                 "required_sections": sections,
                                                                 "options_section": "Options"}))
        self.assertEqual(profile.adr, {"path": "architecture/decisions", "required_sections": sections,
                                       "options_section": "Options"})
        self.assertEqual(validate_profile(self.root, profile_data(adr={"path": "adr"})).adr["required_sections"],
                         ADR_DEFAULTS["required_sections"])

    def test_invalid_tables_are_rejected(self):
        self.rejected("docs/adr", "INVALID_INPUT")
        self.rejected({"folder": "docs/adr"}, "INVALID_INPUT")
        self.rejected({"path": "/abs/adr"}, "INVALID_PATH")
        self.rejected({"path": "../outside"}, "INVALID_PATH")
        self.rejected({"required_sections": []}, "INVALID_INPUT")
        self.rejected({"required_sections": ["Context", "context"]}, "INVALID_INPUT")
        self.rejected({"options_section": "Alternatives"}, "INVALID_INPUT")
        self.rejected({"required_sections": ["Context", "Decision"]}, "INVALID_INPUT")


class AdrTemplateInstallationTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root, _ = setup(Path(temp.name) / "adr", invoke, names=("engine",))

    def install(self):
        result = invoke(["--project", str(self.root), "--json", "skills"])
        self.assertEqual(result.returncode, 0, result.stdout)
        return json.loads(result.stdout)["data"]

    def test_template_is_seeded_once_and_consumer_edits_survive_refresh(self):
        self.install()
        template = self.root / TEMPLATE
        self.assertIn("## Considered options", template.read_text(encoding="utf-8"))
        template.write_bytes(b"# Consumer ADR format\n")
        self.install()
        self.assertEqual(template.read_bytes(), b"# Consumer ADR format\n")



def adr_markdown(title, *, options=2, sections=None, extra=""):
    sections = sections or ADR_DEFAULTS["required_sections"]
    lines = [f"# {title}", ""]
    for section in sections:
        lines += [f"## {section}", "", f"{section} text.", ""]
        if section == "Considered options":
            for number in range(1, options + 1):
                lines += [f"### Option {number}: Choice {number}", "", "- Advantages: some.", ""]
    return "\n".join(lines) + extra


class AdrCase(unittest.TestCase):
    """Isolated Git consumer (engine only) whose CHG-001 is approved, declared none and assigned to v1.0.0."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)
        self.root, self.base = setup(self.workspace / "adr", invoke, names=("engine",))
        self.members = ["CHG-001"]

    def call(self, *args, expect=0, issue=None, project=None):
        project = project or self.root
        before = tree(project)
        result = invoke(["--project", str(project), "--json", *map(str, args)])
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        if issue:
            self.assertIn(issue, [i["code"] for i in payload["issues"]], result.stdout)
        if expect in (1, 2, 3):
            self.assertEqual(tree(project), before, "Rejected operation mutated the consumer")
        return payload

    def write_adr(self, adr_id, body=None, *, folder="docs/adr"):
        path = self.root / folder / f"{adr_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body if body is not None else adr_markdown(f"{adr_id}: Decision"), encoding="utf-8")
        return path

    def register(self, adr_id, *supersedes, action="add", **kwargs):
        args = ["reference", action, adr_id, "--path", f"docs/adr/{adr_id}.md", "--component", "engine", "--role", "decision"]
        for older in supersedes:
            args += ["--supersedes", older]
        return self.call(*args, **kwargs)

    def agree(self, adr_id, **kwargs):
        return self.call("foundation", "agree", "--ref", adr_id, "--actor", "Maintainer", "--reason", "Accepted ADR",
                         *criteria(self.root, "foundation"), **kwargs)

    def adr(self, adr_id):
        return self.call("inspect", "--adr", adr_id)["data"]

    def state(self, adr_id):
        return self.adr(adr_id)["state"]

    def bundle(self, change_id, declaration, *, base=None):
        folder = self.workspace / "bundles" / change_id
        record = bundle(folder, change_id=change_id, kind="refactor", components=("engine",), base=base)
        if declaration is None:
            record["semantic"].pop("architecture_decisions")
        else:
            record["semantic"]["architecture_decisions"] = declaration
        record.pop("proposal_digest")
        put_json(folder / "change.json", record)
        return folder

    def draft(self, change_id, declaration, *, base=None):
        folder = self.bundle(change_id, declaration, base=base)
        self.call("change", "seal", folder)
        self.call("change", "new", "--file", folder / "change.json")
        return json.loads((folder / "change.json").read_text())

    def approve(self, record, **kwargs):
        return self.call("change", "approve", record["id"], "--digest", record["proposal_digest"], "--actor", "Maintainer",
                         "--reason", "Approved scope", *criteria(self.root, "approve"), **kwargs)

    def assign(self, change_id):
        self.members.append(change_id)
        self.call("release", "plan", "engine", "v1.0.0", *[a for m in self.members for a in ("--change", m)])

    def ready(self, change_id, declaration):
        record = self.draft(change_id, declaration)
        self.approve(record)
        self.assign(change_id)
        return record

    def implement(self, change_id, **kwargs):
        return self.call("check", "--change", change_id, "--component", "engine", "--gate", "implement", **kwargs)

    def references(self):
        return {r["id"]: r for r in json.loads((self.root / ".roclec/references.json").read_text())["references"]}


class AdrStateTest(AdrCase):
    def test_proposed_accepted_stale_and_reaccepted(self):
        path = self.write_adr("ADR-001")
        registered = self.register("ADR-001")["data"]["reference"]
        self.assertEqual(registered, {"id": "ADR-001", "path": "docs/adr/ADR-001.md", "components": ["engine"],
                                      "role": "decision", "decision_id": None, "supersedes": []})
        view = self.adr("ADR-001")
        self.assertEqual((view["state"], view["agreement"], view["sha256"]), ("proposed", None, file_hash(path.read_bytes())))
        agreed = self.agree("ADR-001")["data"]
        self.assertEqual(agreed["decision"]["supersedes"], [])
        view = self.adr("ADR-001")
        self.assertEqual(view["state"], "accepted")
        self.assertEqual(view["agreement"], {"decision_id": agreed["decision"]["id"], "sha256": file_hash(path.read_bytes())})
        path.write_text(adr_markdown("ADR-001: Revised decision"), encoding="utf-8")
        view = self.adr("ADR-001")
        self.assertEqual(view["state"], "stale")
        self.assertNotEqual(view["sha256"], view["agreement"]["sha256"])
        self.agree("ADR-001")
        self.assertEqual(self.state("ADR-001"), "accepted")
        # references.json declaring a supersedes list other than the agreed one is stale too.
        self.write_adr("ADR-002")
        self.register("ADR-002")
        record = json.loads((self.root / ".roclec/references.json").read_text())
        for ref in record["references"]:
            if ref["id"] == "ADR-001":
                ref["supersedes"] = ["ADR-002"]
        put_json(self.root / ".roclec/references.json", record)
        self.assertEqual(self.state("ADR-001"), "stale")
        self.assertEqual(self.adr("ADR-002")["superseded_by"], [])

    def test_supersession_needs_the_replacing_agreement_and_reports_the_chain(self):
        for adr_id in ("ADR-001", "ADR-002", "ADR-003"):
            self.write_adr(adr_id)
        self.register("ADR-001")
        self.agree("ADR-001")
        self.register("ADR-002", "ADR-001")
        self.assertEqual((self.state("ADR-001"), self.state("ADR-002")), ("accepted", "proposed"))
        decision = self.agree("ADR-002")["data"]["decision"]
        self.assertEqual(decision["supersedes"], ["ADR-001"])
        self.assertEqual((self.state("ADR-001"), self.state("ADR-002")), ("superseded", "accepted"))
        self.register("ADR-003", "ADR-002")
        self.agree("ADR-003")
        oldest, middle, newest = (self.adr(i) for i in ("ADR-001", "ADR-002", "ADR-003"))
        self.assertEqual(oldest["superseded_by"], ["ADR-002"])
        self.assertEqual(oldest["chain"], {"replaces": [], "replaced_by": ["ADR-002", "ADR-003"]})
        self.assertEqual(middle["chain"], {"replaces": ["ADR-001"], "replaced_by": ["ADR-003"]})
        self.assertEqual(newest["chain"], {"replaces": ["ADR-001", "ADR-002"], "replaced_by": []})
        self.assertEqual((middle["state"], newest["state"]), ("superseded", "accepted"))
        # Updating the replacing ADR clears its agreement: it stops superseding until agreed again.
        self.register("ADR-003", "ADR-002", action="update")
        self.assertEqual((self.state("ADR-002"), self.state("ADR-003")), ("accepted", "proposed"))
        listing = self.call("list", "adrs")["data"]["adrs"]
        self.assertEqual([(a["id"], a["state"], a["supersedes"], a["superseded_by"]) for a in listing],
                         [("ADR-001", "superseded", [], ["ADR-002"]), ("ADR-002", "accepted", ["ADR-001"], []),
                          ("ADR-003", "proposed", ["ADR-002"], [])])
        self.assertEqual(set(listing[0]), {"id", "path", "components", "state", "supersedes", "superseded_by"})

    def test_invalid_registrations_are_rejected_without_writes(self):
        for adr_id in ("ADR-001", "ADR-002"):
            self.write_adr(adr_id)
        self.register("ADR-001")
        self.register("ADR-002", "ADR-001")
        self.register("ADR-001", "ADR-002", action="update", expect=1, issue="ADR_SUPERSESSION_INVALID")
        self.register("ADR-001", "ADR-009", action="update", expect=1, issue="ADR_SUPERSESSION_INVALID")
        self.register("ADR-001", "ADR-001", action="update", expect=1, issue="ADR_SUPERSESSION_INVALID")
        # A non-decision target cannot have an ADR ID, so the list itself is malformed.
        self.register("ADR-001", "architecture", action="update", expect=2, issue="INVALID_INPUT")
        self.register("ADR-001", "ADR-002", "ADR-002", action="update", expect=2, issue="INVALID_INPUT")
        (self.root / "docs/notes.md").write_text("# Notes\n")
        self.call("reference", "add", "notes", "--path", "docs/notes.md", "--component", "engine", "--role", "context",
                  "--supersedes", "ADR-001", expect=2, issue="INVALID_INPUT")
        self.call("reference", "add", "ADR-003", "--path", "docs/notes.md", "--component", "engine", "--role", "context",
                  expect=2, issue="INVALID_INPUT")
        self.call("reference", "add", "notes", "--path", "docs/adr/ADR-001.md", "--component", "engine", "--role", "decision",
                  expect=2, issue="INVALID_INPUT")
        self.write_adr("ADR-004", folder="docs")
        self.call("reference", "add", "ADR-004", "--path", "docs/ADR-004.md", "--component", "engine", "--role", "decision",
                  expect=2, issue="INVALID_PATH")
        (self.root / "docs/adr/ADR-005.txt").write_text("# ADR-005\n")
        self.call("reference", "add", "ADR-005", "--path", "docs/adr/ADR-005.txt", "--component", "engine", "--role", "decision",
                  expect=2, issue="INVALID_PATH")
        # A foreign record carrying supersedes on a non-decision reference is rejected on read.
        record = json.loads((self.root / ".roclec/references.json").read_text())
        record["references"][-1]["supersedes"] = []
        put_json(self.root / ".roclec/references.json", record)
        self.call("check", expect=2, issue="INVALID_INPUT")

    def test_adr_agreement_must_record_supersedes(self):
        path = self.write_adr("ADR-001")
        self.register("ADR-001")
        decision = {"model_schema": 2, "kind": "foundation", "entity": "ADR-001", "previous": None, "status": "agreed",
                    "actor": "Maintainer", "reason": "Hand-written agreement", "sources": {"ADR-001": file_hash(path.read_bytes())}}
        decision["id"] = digest(decision)
        put_json(self.root / f".roclec/decisions/{decision['id']}.json", decision)
        self.call("check", expect=2, issue="INVALID_INPUT")
        self.call("inspect", "--adr", "ADR-001", expect=2, issue="INVALID_INPUT")

    def test_reading_a_cycle_written_outside_the_cli_fails_check(self):
        for adr_id in ("ADR-001", "ADR-002"):
            self.write_adr(adr_id)
        self.register("ADR-001")
        self.register("ADR-002", "ADR-001")
        record = json.loads((self.root / ".roclec/references.json").read_text())
        for ref in record["references"]:
            if ref["id"] == "ADR-001":
                ref["supersedes"] = ["ADR-002"]
        put_json(self.root / ".roclec/references.json", record)
        self.call("check", expect=1, issue="ADR_SUPERSESSION_INVALID")

    def test_adrs_never_complete_or_block_foundation(self):
        self.write_adr("ADR-001")
        self.register("ADR-001")
        result = self.call("foundation", "check", "--component", "engine")["data"]
        self.assertNotIn("ADR-001", [r["id"] for r in result["references"]])
        self.agree("ADR-001")
        (self.root / "docs/adr/ADR-001.md").write_text(adr_markdown("Edited"), encoding="utf-8")
        self.call("foundation", "check", "--component", "engine")

    def test_registration_and_agreement_are_trunk_only(self):
        self.write_adr("ADR-001")
        commit(self.root)
        side = self.workspace / "side"
        git(self.root, "worktree", "add", "-qb", "side", str(side))
        args = ("reference", "add", "ADR-001", "--path", "docs/adr/ADR-001.md", "--component", "engine", "--role", "decision")
        self.call(*args, expect=3, issue="OFF_TRUNK", project=side)
        self.register("ADR-001")
        commit(self.root)
        git(side, "merge", "-q", "main")
        self.call("foundation", "agree", "--ref", "ADR-001", "--actor", "Maintainer", "--reason", "Accepted", expect=3,
                  issue="OFF_TRUNK", project=side)
        self.call("reference", "update", "ADR-001", "--path", "docs/adr/ADR-001.md", "--component", "engine", "--role",
                  "decision", expect=3, issue="OFF_TRUNK", project=side)


class AdrDeclarationTest(AdrCase):
    def test_approval_requires_a_declaration(self):
        record = self.draft("CHG-002", None)
        self.assertNotIn("architecture_decisions", record["semantic"])
        self.call("check", "--change", "CHG-002", "--gate", "approve", expect=1, issue="ADR_UNDECLARED")
        self.approve(record, expect=1, issue="ADR_UNDECLARED")
        self.assertIsNone(self.call("inspect", "--change", "CHG-002")["data"]["architecture_decisions"])

    def test_malformed_declarations_are_rejected(self):
        self.write_adr("ADR-001")
        self.register("ADR-001")
        for number, value in enumerate(({"none": ""}, {"none": "  "}, {"adrs": []}, {"adrs": [{"id": "ADR-001"}], "none": "x"},
                                        {"other": "x"}, {"adrs": [{"id": "ADR-001", "note": "x"}]}, {"adrs": [{"id": "adr-1"}]},
                                        {"adrs": [{"id": "ADR-001"}, {"id": "ADR-001"}]}, [], "none"), start=2):
            folder = self.bundle(f"CHG-{number:03}", value)
            self.call("change", "seal", folder, expect=2, issue="INVALID_INPUT")
        folder = self.bundle("CHG-019", {"none": "replaced by an explicit null"})
        record = json.loads((folder / "change.json").read_text())
        record["semantic"]["architecture_decisions"] = None
        put_json(folder / "change.json", record)
        self.call("change", "seal", folder, expect=2, issue="INVALID_INPUT")
        # A hand-sealed import is validated the same way.
        folder = self.bundle("CHG-020", {"none": ""})
        record = json.loads((folder / "change.json").read_text())
        record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
        put_json(folder / "change.json", record)
        self.call("change", "new", "--file", folder / "change.json", expect=2, issue="INVALID_INPUT")
        unsorted = {"adrs": [{"id": "ADR-002", "sha256": "1" * 64}, {"id": "ADR-001", "sha256": "0" * 64}]}
        folder = self.bundle("CHG-021", unsorted)
        record = json.loads((folder / "change.json").read_text())
        record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
        put_json(folder / "change.json", record)
        self.call("change", "new", "--file", folder / "change.json", expect=2, issue="INVALID_INPUT")
        self.call("change", "seal", self.bundle("CHG-022", {"adrs": [{"id": "ADR-009"}]}), expect=1, issue="INVALID_REFERENCE")
        self.call("change", "seal", self.bundle("CHG-023", {"adrs": [{"id": "ADR-009", "sha256": "0" * 64}]}),
                  expect=1, issue="INVALID_REFERENCE")

    def test_seal_pins_current_bytes_and_approval_freezes_them(self):
        first, second = self.write_adr("ADR-001"), self.write_adr("ADR-002")
        self.register("ADR-001")
        self.register("ADR-002")
        record = self.draft("CHG-002", {"adrs": [{"id": "ADR-002"}, {"id": "ADR-001"}]})
        pins = [{"id": "ADR-001", "sha256": file_hash(first.read_bytes())}, {"id": "ADR-002", "sha256": file_hash(second.read_bytes())}]
        self.assertEqual(record["semantic"]["architecture_decisions"], {"adrs": pins})
        original = first.read_bytes()
        first.write_text(adr_markdown("ADR-001: Edited after sealing"), encoding="utf-8")
        result = self.approve(record, expect=1, issue="ADR_PIN_STALE")
        self.assertEqual([item["id"] for item in result["issues"][0]["actual"]], ["ADR-001"])
        self.call("check", "--change", "CHG-002", "--gate", "approve", expect=1, issue="ADR_PIN_STALE")
        declared = self.call("inspect", "--change", "CHG-002")["data"]["architecture_decisions"]
        self.assertEqual(declared, {"adrs": [{**pins[0], "state": "proposed", "pin_current": False},
                                             {**pins[1], "state": "proposed", "pin_current": True}]})
        first.write_bytes(original)
        self.assertEqual(self.state("ADR-001"), "proposed")
        self.approve(record)
        snapshot_path = self.root / f".roclec/changes/CHG-002/revisions/{record['proposal_digest']}/change.json"
        self.assertEqual(json.loads(snapshot_path.read_text())["semantic"]["architecture_decisions"], {"adrs": pins})
        cited = self.adr("ADR-001")["changes"]
        self.assertEqual(cited, [{"id": "CHG-002", "revision": record["proposal_digest"], "integrated_components": [],
                                  "status": "approved", "sha256": pins[0]["sha256"], "pin_current": True}])

    def test_seal_keeps_given_pins(self):
        self.write_adr("ADR-001")
        self.register("ADR-001")
        record = self.draft("CHG-002", {"adrs": [{"id": "ADR-001", "sha256": "0" * 64}]})
        self.assertEqual(record["semantic"]["architecture_decisions"]["adrs"][0]["sha256"], "0" * 64)
        self.approve(record, expect=1, issue="ADR_PIN_STALE")

    def test_change_declarations_in_queries(self):
        self.write_adr("ADR-001")
        self.register("ADR-001")
        self.draft("CHG-002", {"adrs": [{"id": "ADR-001"}]})
        none = {"none": "Synthetic fixture applies no architecture decision record."}
        for deep in ((), ("--deep",)):
            self.assertEqual(self.call("inspect", "--change", "CHG-001", *deep)["data"]["architecture_decisions"], none)
            declared = self.call("inspect", "--change", "CHG-002", *deep)["data"]["architecture_decisions"]
            self.assertEqual([(a["id"], a["state"], a["pin_current"]) for a in declared["adrs"]], [("ADR-001", "proposed", True)])
        status = self.call("status")["data"]["components"]["engine"]
        self.assertEqual(status["pending_adrs"], [{"id": "ADR-001", "state": "proposed"}])
        self.agree("ADR-001")
        self.assertEqual(self.call("status")["data"]["components"]["engine"]["pending_adrs"], [])
        (self.root / "docs/adr/ADR-001.md").write_text(adr_markdown("Edited"), encoding="utf-8")
        self.assertEqual(self.call("status")["data"]["components"]["engine"]["pending_adrs"], [{"id": "ADR-001", "state": "stale"}])
        self.call("inspect", "--adr", "ADR-404", expect=1, issue="INVALID_REFERENCE")
        self.call("inspect", "--adr", "architecture", expect=1, issue="INVALID_REFERENCE")
        for args in (("inspect", "--adr", "ADR-001"), ("list", "adrs"), ("status",), ("inspect", "--change", "CHG-002")):
            human = invoke(["--project", str(self.root), *args])
            self.assertEqual(human.returncode, 0, human.stdout)
            self.assertIn("ADR-001", human.stdout)


class AdrGateTest(AdrCase):
    def test_implementation_requires_accepted_adrs_with_the_pinned_bytes(self):
        path = self.write_adr("ADR-001")
        self.register("ADR-001")
        self.ready("CHG-002", {"adrs": [{"id": "ADR-001"}]})
        failure = self.implement("CHG-002", expect=1, issue="ADR_NOT_ACCEPTED")["issues"][0]
        self.assertEqual([(f["id"], f["state"]) for f in failure["actual"]], [("ADR-001", "proposed")])
        self.assertIn("foundation agree --ref ADR-001", failure["remediation"])
        self.call("change", "start", "CHG-002", "--component", "engine", "--actor", "Maintainer", expect=1, issue="ADR_NOT_ACCEPTED")
        for stage in ("verify", "integrate"):
            self.call("check", "--change", "CHG-002", "--component", "engine", "--gate", stage, expect=1, issue="ADR_NOT_ACCEPTED")
        self.agree("ADR-001")
        self.implement("CHG-002")
        path.write_text(adr_markdown("ADR-001: Edited after acceptance"), encoding="utf-8")
        failure = self.implement("CHG-002", expect=1, issue="ADR_NOT_ACCEPTED")["issues"][0]
        self.assertEqual([(f["id"], f["state"]) for f in failure["actual"]], [("ADR-001", "stale")])
        self.agree("ADR-001")
        failure = self.implement("CHG-002", expect=1, issue="ADR_PIN_STALE")["issues"][0]
        self.assertEqual(failure["actual"][0]["agreed"], file_hash(path.read_bytes()))
        self.assertNotEqual(failure["actual"][0]["pinned"], failure["actual"][0]["agreed"])
        self.ready("CHG-003", {"adrs": [{"id": "ADR-001"}]})
        self.call("change", "start", "CHG-003", "--component", "engine", "--actor", "Maintainer")
        self.write_adr("ADR-002")
        self.register("ADR-002", "ADR-001")
        self.implement("CHG-003")
        self.agree("ADR-002")
        failure = self.implement("CHG-003", expect=1, issue="ADR_NOT_ACCEPTED")["issues"][0]
        self.assertEqual([(f["id"], f["state"], f["superseded_by"]) for f in failure["actual"]],
                         [("ADR-001", "superseded", ["ADR-002"])])
        self.assertIn("ADR-002", failure["remediation"])
        self.ready("CHG-004", {"none": "Pure refactor inside the existing decisions"})
        self.implement("CHG-004")
        self.call("change", "start", "CHG-004", "--component", "engine", "--actor", "Maintainer")

    def test_legacy_approval_without_declaration_passes_implementation_gates(self):
        from unittest import mock
        from roclec_spec_kit.adr import Adrs
        record = self.draft("CHG-002", None)
        with mock.patch.object(Adrs, "approvable"):  # Seeds an approval recorded before declarations existed.
            self.approve(record)
        self.assign("CHG-002")
        self.implement("CHG-002")
        self.call("check", "--change", "CHG-002", "--gate", "approve", expect=1, issue="ADR_UNDECLARED")


class AdrStructureTest(AdrCase):
    def warnings(self):
        payload = self.call("check")
        return [(i["entity"], i["message"], i["actual"]) for i in payload["issues"]
                if i["code"] == "ADR_STRUCTURE" and i["severity"] == "warning"]

    def test_structural_warnings_do_not_block(self):
        self.write_adr("ADR-001")
        self.register("ADR-001")
        self.assertEqual(self.warnings(), [])
        sections = [s for s in ADR_DEFAULTS["required_sections"] if s != "Consequences"]
        fenced = "\n```markdown\n## Consequences\n### Option 3: Hidden\n```\n"
        self.write_adr("ADR-002", adr_markdown("ADR-002", sections=sections, extra=fenced))
        self.register("ADR-002")
        self.write_adr("ADR-003", adr_markdown("ADR-003", options=1, extra="\n## Relations\n\n### Not an option\n"))
        self.register("ADR-003")
        self.assertEqual(self.warnings(), [("ADR-002", "ADR lacks required sections", ["Consequences"]),
                                           ("ADR-003", "ADR describes fewer than two considered options", 1)])
        (self.root / "docs/adr/ADR-003.md").unlink()
        self.assertIn(("ADR-003", "ADR file is missing", None), self.warnings())

    def test_adapted_template_and_profile_pass_and_moved_folder_warns(self):
        body = "# ADR-001\n\n## Context\n\nWhy.\n\n## Alternatives\n\n### Keep\n\nA.\n\n### Replace\n\nB.\n\n## Outcome\n\nKeep.\n"
        self.write_adr("ADR-001", body)
        self.register("ADR-001")
        self.assertEqual([w[1:] for w in self.warnings()], [("ADR lacks required sections", ADR_DEFAULTS["required_sections"])])
        profile = self.root / ".roclec/project.toml"
        profile.write_text(profile.read_text() + '\n[adr]\nrequired_sections = ["Context", "Alternatives", "Outcome"]\n'
                           'options_section = "Alternatives"\n', encoding="utf-8")
        self.assertEqual(self.warnings(), [])
        profile.write_text(profile.read_text().replace("[adr]\n", '[adr]\npath = "architecture/decisions"\n'), encoding="utf-8")
        self.assertEqual([w[:2] for w in self.warnings()],
                         [("ADR-001", "ADR is not a Markdown file inside the configured ADR folder")])


class AdrHistoryTest(AdrCase):
    """An integrated change keeps its pin; the release gate only reports the later supersession."""

    def integrate(self, change_id):
        run = self.call("run", "verify", change_id, "--component", "engine", "--base", self.base, *PRODUCER)["data"]["run"]
        commit(self.root)
        plan = self.workspace / f"{change_id}-plan.json"
        self.call("integrate", "prepare", change_id, "--component", "engine", "--run", run["id"], "--out", plan)
        self.call("operation", "apply", plan)

    def test_integrated_pin_survives_supersession_and_release_reports_it(self):
        path = self.write_adr("ADR-001")
        self.register("ADR-001")
        self.agree("ADR-001")
        commit(self.root)
        self.integrate("CHG-001")
        record = self.draft("CHG-002", {"adrs": [{"id": "ADR-001"}]}, base=snapshot(("engine",)))
        self.approve(record)
        self.assign("CHG-002")
        commit(self.root)
        self.integrate("CHG-002")
        self.assertEqual(self.call("inspect", "--change", "CHG-002")["data"]["status"], "integrated")
        self.write_adr("ADR-002")
        self.register("ADR-002", "ADR-001")
        self.agree("ADR-002")
        path.write_text(adr_markdown("ADR-001: Edited after integration"), encoding="utf-8")
        self.assertEqual(self.state("ADR-001"), "superseded")
        self.call("check")
        self.implement("CHG-002")
        cited = self.adr("ADR-001")["changes"]
        self.assertEqual([(c["id"], c["status"], c["pin_current"]) for c in cited], [("CHG-002", "integrated", False)])
        self.assertEqual(cited[0]["sha256"], record["semantic"]["architecture_decisions"]["adrs"][0]["sha256"])
        commit(self.root)
        release = self.call("run", "verify", "--release", "v1.0.0", "--component", "engine", "--base", self.base, *PRODUCER)["data"]["run"]
        commit(self.root)
        gate = self.call("check", "--component", "engine", "--gate", "release", "--release", "v1.0.0")["data"]
        self.assertEqual(gate["limitations"], [{"code": "ADR_SUPERSEDED", "change_id": "CHG-002", "adr": "ADR-001",
                                                "superseded_by": ["ADR-002"]}])
        prepared = self.call("release", "prepare", "engine", "v1.0.0", "--run", release["id"], "--out",
                             self.workspace / "release-prepare.json")["data"]["plan"]
        self.call("operation", "apply", self.workspace / "release-prepare.json")
        self.assertNotIn("limitations", json.loads(next((self.root / ".roclec/releases/engine/v1.0.0/preparations").glob("*.json")).read_text()))
        self.assertTrue(prepared["inputs"]["preparation"])

    def test_component_adr_is_a_candidate_input_without_profile_classification(self):
        path = self.write_adr("ADR-001")
        self.register("ADR-001")
        (self.root / "docs/adr/notes.md").write_text("# Unregistered notes\n")
        failure = self.call("run", "verify", "CHG-001", "--component", "engine", "--base", self.base, *PRODUCER,
                            expect=1, issue="CANDIDATE_INCOMPLETE")["issues"][0]
        self.assertEqual(failure["actual"], ["docs/adr/notes.md"])
        (self.root / "docs/adr/notes.md").unlink()
        run = self.call("run", "verify", "CHG-001", "--component", "engine", "--base", self.base, *PRODUCER)["data"]["run"]
        self.assertEqual(run["status"], "pass")
        candidate = run["candidate"]
        self.assertEqual(candidate["categories"]["docs/adr/ADR-001.md"], "input")
        self.assertEqual(candidate["inputs"]["files"]["docs/adr/ADR-001.md"]["sha256"], file_hash(path.read_bytes()))
        self.assertNotIn("ADR-001", [r["id"] for r in candidate["inputs"]["references"]])
        # Editing the ADR changes the candidate, like any other reference of the component.
        path.write_text(adr_markdown("ADR-001: Edited"), encoding="utf-8")
        self.call("check", "--change", "CHG-001", "--component", "engine", "--gate", "verify", expect=1, issue="EVIDENCE_STALE")


class AdrPartialIntegrationTest(AdrCase):
    """A pending participant's new revision must not hide the citation its integrated participant applied."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)
        # No AC coverage on the checks: the refactor below has no base contract and therefore no ACs.
        self.root, self.base = setup(self.workspace / "adr", invoke, names=("engine", "viewer"), coverage=False)

    def test_integrated_revision_keeps_citing_the_adr_after_a_pending_revision(self):
        for adr_id in ("ADR-001", "ADR-002"):
            self.write_adr(adr_id)
            self.call("reference", "add", adr_id, "--path", f"docs/adr/{adr_id}.md", "--component", "engine",
                      "--component", "viewer", "--role", "decision")
            self.agree(adr_id)
        folder = self.workspace / "bundles" / "CHG-002"
        record = bundle(folder, change_id="CHG-002", kind="refactor", components=("engine", "viewer"))
        record["semantic"]["architecture_decisions"] = {"adrs": [{"id": "ADR-001"}]}
        record.pop("proposal_digest")
        put_json(folder / "change.json", record)
        self.call("change", "seal", folder)
        self.call("change", "new", "--file", folder / "change.json")
        first = json.loads((folder / "change.json").read_text())
        self.approve(first)
        for component in ("engine", "viewer"):
            self.call("release", "plan", component, "v1.0.0", "--change", "CHG-001", "--change", "CHG-002")
        commit(self.root)
        run = self.call("run", "verify", "CHG-002", "--component", "engine", "--base", self.base, *PRODUCER)["data"]["run"]
        commit(self.root)
        plan = self.workspace / "CHG-002-engine.json"
        self.call("integrate", "prepare", "CHG-002", "--component", "engine", "--run", run["id"], "--out", plan)
        self.call("operation", "apply", plan)
        # The pending participant's revision cites ADR-002 instead and is approved again.
        stored = self.root / ".roclec/changes/CHG-002/change.json"
        revised = json.loads(stored.read_text())
        pin2 = file_hash((self.root / "docs/adr/ADR-002.md").read_bytes())
        revised["semantic"]["architecture_decisions"] = {"adrs": [{"id": "ADR-002", "sha256": pin2}]}
        revised["proposal_digest"] = digest({k: revised[k] for k in ("id", "kind", "semantic")})
        put_json(stored, revised)
        self.approve(revised)
        pin1 = first["semantic"]["architecture_decisions"]["adrs"][0]["sha256"]
        self.assertEqual(self.adr("ADR-001")["changes"], [
            {"id": "CHG-002", "revision": first["proposal_digest"], "integrated_components": ["engine"],
             "status": "partially-integrated", "sha256": pin1, "pin_current": True}])
        self.assertEqual(self.adr("ADR-002")["changes"], [
            {"id": "CHG-002", "revision": revised["proposal_digest"], "integrated_components": [],
             "status": "partially-integrated", "sha256": pin2, "pin_current": True}])
        self.call("check")


class AdrSharedScenariosTest(unittest.TestCase):
    """The scripted public-CLI scenarios that scripts/harness.py replays against the installed wheel."""

    def run_scenarios(self, module):
        with tempfile.TemporaryDirectory() as directory:
            module.adr_scenarios(Path(directory), invoke, lambda name, condition, detail="": self.assertTrue(condition, f"{name}: {detail}"))

    def test_c1_adr_lifecycle_declarations_and_structure(self):
        self.run_scenarios(c1_scenarios)

    def test_c2_adr_gates_pins_and_candidate_inputs(self):
        self.run_scenarios(c2_scenarios)

    def test_c3_release_gate_reports_superseded_adrs(self):
        self.run_scenarios(c3_scenarios)

    def test_scenario_adr_matches_the_defaults(self):
        self.assertEqual(scenario_adr_markdown("ADR-001"), adr_markdown("ADR-001"))


if __name__ == "__main__":
    unittest.main()
