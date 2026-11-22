"""TL.6 (M-34): the generated flow view's "Flow learning" section and the seeded flow retrospective.

The section is a deterministic projection of records (no judgments, no generation timestamps);
`check` reports the view stale whenever records change it, and `views --write` regenerates it.
"""
from __future__ import annotations

from importlib.resources import files as package_files
import json
from pathlib import Path
import tempfile
import unittest

from roclec_spec_kit import flow
from roclec_spec_kit.config import load_profile
from roclec_spec_kit.kernel import Kernel
from roclec_spec_kit.model import sha
from scripts.c1_scenarios import FLOW, criteria, put_json
from scripts.c2_scenarios import PRODUCER, setup
try:
    from test_kernel import invoke
except ModuleNotFoundError:  # run as tests.test_flow_learning
    from tests.test_kernel import invoke

VIEW = "docs/flow.md"
RETRO = "docs/flow-retro.md"
TEMPLATE = package_files("roclec_spec_kit").joinpath("assets/project/flow-retro.md").read_bytes()
SEEDED = package_files("roclec_spec_kit").joinpath("assets/project/flow.toml").read_bytes()
TRANSCRIPT = b"user: do the fixture work\nassistant: done\n"


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def section(text, title):
    """Lines of one `### title` subsection of the learning section."""
    start = text.index(f"### {title}\n")
    end = text.find("\n### ", start + 1)
    return text[start:len(text) if end < 0 else end].splitlines()


class LearningTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)
        self.root, self.base = setup(self.workspace, invoke)
        self.inputs = self.workspace / "inputs"
        self.inputs.mkdir()
        self.count = 0

    def call(self, *args, expect=0, issue=None):
        result = invoke(["--project", str(self.root), "--json", *map(str, args)])
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        if issue:
            self.assertIn(issue, [i["code"] for i in payload["issues"]], result.stdout)
        return payload

    def input(self, value):
        self.count += 1
        path = self.inputs / f"input-{self.count}.json"
        put_json(path, value)
        return path

    def view(self):
        return (self.root / VIEW).read_text(encoding="utf-8")

    def stale(self):
        return [i for i in self.call("check")["issues"] if i["code"] == "FLOW_VIEW_STALE"]

    def regenerate(self):
        """The view is stale: `views` refuses without writing; `views --write` regenerates it and is then current."""
        self.assertEqual([i["path"] for i in self.stale()], [VIEW])
        before = files(self.root)
        self.call("views", expect=1, issue="VIEW_STALE")
        self.assertEqual(files(self.root), before, "views without --write must not write")
        self.assertEqual(self.call("views", "--write")["data"]["written"], [VIEW])
        self.assertEqual(self.stale(), [])
        self.assertEqual(self.call("views")["data"]["written"], [])
        return self.view()

    def session(self, stage, role, **scope):
        meta = {"model_schema": 2, "host": "claude-code", "host_session_id": f"host-{self.count}", "actor": "Fixture agent",
                "role": role, "model": "fixture-model", "started_at": "2026-01-31T09:00:00Z",
                "ended_at": "2026-01-31T09:30:00Z", "stage": stage, **scope}
        meta_file = self.input(meta)
        transcript = self.inputs / f"session-{self.count}.jsonl"
        transcript.write_bytes(TRANSCRIPT)
        return self.call("evidence", "record", "--kind", "agent-session", "--file", meta_file,
                         "--transcript", transcript)["data"]["evidence"]["id"]

    def fut(self, fut_id, finding, scope="process"):
        self.call("fut", "capture", "--file", self.input(
            {"model_schema": 2, "id": fut_id, "source": {"location": "retro", "locator": "fixture"},
             "finding": finding, "impact": "Rework", "questions": [], "scope": scope}))

    def test_views_are_deterministic_and_track_each_kind_of_record(self):
        # The C2 fixture seeds a flow agreement: the view init wrote predates it.
        first = self.regenerate()
        (self.root / VIEW).unlink()
        self.call("views", "--write")
        self.assertEqual(self.view(), first, "two generations on the same state must be byte-identical")
        revisions = section(first, "Flow revisions")
        self.assertEqual(len([line for line in revisions if line.startswith("| `")]), 1)
        self.assertIn("Synthetic test setup", "\n".join(revisions))
        for title in ("Open process FUTs", "Rejections by stage", "Findings by severity and status",
                      "Agent sessions by role and stage"):
            self.assertIn("None recorded.", section(first, title), title)
        # The generated stage table, criteria and diagram are unchanged by the learning section.
        parsed = flow.load(self.root)
        plain = flow.render(parsed, load_profile(self.root).data).decode()
        cut = "## Flow learning\n"
        body = first.partition("\n")[2]
        self.assertEqual(body[:body.index(cut)], plain.partition("\n")[2][:plain.partition("\n")[2].index(cut)])

        # Sessions: counts by role x stage.
        self.session("implement", "implementer", change_id="CHG-001", component="engine")
        self.session("implement", "implementer", change_id="CHG-001", component="viewer")
        self.session("define", "specifier", change_id="CHG-001")
        text = self.regenerate()
        self.assertEqual(section(text, "Agent sessions by role and stage")[2:6],
                         ["| Role | define | implement |", "| --- | --- | --- |",
                          "| implementer | 0 | 2 |", "| specifier | 1 | 0 |"])

        # Finding: counted by severity x status across scopes.
        run = self.call("run", "verify", "CHG-001", "--component", "engine", "--base", self.base, *PRODUCER)["data"]["run"]
        finding = {"id": "F-1", "severity": "major", "location": None, "acceptance_ids": ["AC-001"],
                   "condition": "Empty input", "impact": "Crash", "description": "Handle empty input"}
        report = {"model_schema": 2, "kind": "manual", "change_id": "CHG-001", "component": "engine",
                  "run_id": run["id"], "candidate_digest": run["candidate"]["inputs_digest"], "actor": "Observer",
                  "context": "Observation fixture", "outcome": "pass", "acceptance_ids": ["AC-001"],
                  "checks": ["Observed"], "limitations": [], "findings": [finding]}
        self.call("evidence", "record", "--file", self.input(report))
        text = self.regenerate()
        rows = section(text, "Findings by severity and status")
        self.assertIn("| Severity | open | still-open | fixed | accepted | deferred | invalid |", rows)
        self.assertIn("| major | 1 | 0 | 0 | 0 | 0 | 0 |", rows)
        self.assertIn("| info | 0 | 0 | 0 | 0 | 0 | 0 |", rows)

        # Rejection: grouped by the stage of its decision point, open until revised.
        reference = self.root / "docs/reference.md"
        corrections = self.input([{"id": "R-1", "description": "Name the stack"}])
        self.call("reject", "reference", "architecture", "--digest", sha(reference.read_bytes()),
                  "--actor", "Fixture owner", "--reason", "Incomplete", "--corrections", corrections,
                  *criteria(self.root, "foundation", "rejected"))
        text = self.regenerate()
        rows = section(text, "Rejections by stage")
        self.assertIn("| foundation | 1 | 1 |", rows)
        self.assertTrue(any(line.startswith("| foundation | reference | architecture | revise | open | `")
                            for line in rows), rows)

        # Process agreement: friction -> adjustment -> reason; an uncited open process FUT stays open.
        self.fut("FUT-001", "The approve gate blocks too early")
        self.fut("FUT-002", "Reviews wait | for a free reviewer")
        self.fut("FUT-003", "Product idea", scope="product")
        text = self.regenerate()
        self.assertEqual([line for line in section(text, "Open process FUTs") if line.startswith("| FUT-")],
                         ["| FUT-001 | captured | The approve gate blocks too early |",
                          "| FUT-002 | captured | Reviews wait \\| for a free reviewer |"])
        path = self.root / FLOW
        path.write_text(path.read_text() + "\n# Adjusted after FUT-001.\n")
        agreement = self.call("foundation", "agree", "--ref", "flow", "--actor", "Fixture owner",
                              "--reason", "Approve later in the flow", *criteria(self.root, "foundation"),
                              "--fut", "FUT-001")["data"]["decision"]
        text = self.regenerate()
        rows = [line for line in section(text, "Flow revisions") if line.startswith("| `")]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1], f"| `{agreement['id']}` | `{agreement['sources']['flow']}` | Fixture owner | "
                                   "Approve later in the flow | FUT-001 (process): The approve gate blocks too early |")
        self.assertIn("Synthetic test setup", rows[0], "revisions keep decision order")
        self.assertEqual([line for line in section(text, "Open process FUTs") if line.startswith("| FUT-")],
                         ["| FUT-002 | captured | Reviews wait \\| for a free reviewer |"])

        # Same state, fresh generation: identical bytes; the check stays clean.
        (self.root / VIEW).unlink()
        self.call("views", "--write")
        self.assertEqual(self.view(), text)
        self.assertEqual(self.stale(), [])
        self.assertNotIn("score", text.lower())

    def test_ai_false_stages_list_their_reason(self):
        text = self.regenerate()
        self.assertEqual(section(text, "Stages with ai = false")[2:5],
                         ["| Stage | Role | Reason |", "| --- | --- | --- |",
                          "| approve | owner | Only a person decides which intent is accepted. |"])
        path = self.root / FLOW
        plan = 'ai = true\nsession_evidence = "optional"\nrole = "implementer"\n\n[stages.implement]'
        self.assertEqual(path.read_text().count(plan), 1)
        path.write_text(path.read_text().replace(
            plan, 'ai = false\nreason = "Planning commits people."\nrole = "owner"\n\n[stages.implement]'))
        text = self.regenerate()
        self.assertEqual(section(text, "Stages with ai = false")[4:6],
                         ["| approve | owner | Only a person decides which intent is accepted. |",
                          "| plan | owner | Planning commits people. |"])

class LearningUnitTest(unittest.TestCase):
    def test_learning_none_is_the_empty_projection_and_link_is_relative(self):
        parsed = flow.parse(SEEDED)
        empty = {key: [] for key in flow.LEARNING_KEYS}
        self.assertEqual(flow.render(parsed, {}), flow.render(parsed, {}, empty))
        self.assertIn("[docs/flow-retro.md](flow-retro.md)", flow.render(parsed, {}).decode())
        for view, link in (("process.md", "docs/flow-retro.md"), ("docs/team/flow.md", "../flow-retro.md"),
                           ("guides/flow.md", "../docs/flow-retro.md")):
            moved = flow.parse(SEEDED.replace(b'view = "docs/flow.md"', f'view = "{view}"'.encode()))
            self.assertIn(f"[docs/flow-retro.md]({link})", flow.render(moved, {}).decode(), view)

    def test_status_compares_the_full_render(self):
        parsed = flow.parse(SEEDED)
        sessions = {"sessions": [{"role": "implementer", "stage": "implement", "count": 1}]}
        rendered = flow.render(parsed, {}, sessions)
        self.assertEqual(flow.view_status(parsed, {}, rendered, sessions), "current")
        self.assertEqual(flow.view_status(parsed, {}, rendered), "stale")
        self.assertEqual(flow.view_status(parsed, {}, flow.render(parsed, {}), sessions), "stale")

    def test_lists_are_sorted_independently_of_input_order(self):
        parsed = flow.parse(SEEDED)
        rows = [{"stage": "design", "subject": "prototype", "entity": "ui/b.html", "consequence": "revise", "open": False,
                 "decision": "b" * 64},
                {"stage": "foundation", "subject": "reference", "entity": "architecture", "consequence": "defer",
                 "open": False, "decision": "a" * 64}]
        data = {"rejections": rows, "sessions": [{"role": "reviewer", "stage": "review", "count": 1},
                                                 {"role": "implementer", "stage": "verify", "count": 2}],
                "open_futs": [{"id": "FUT-002", "status": "captured", "finding": "b"},
                              {"id": "FUT-001", "status": "evaluating", "finding": "a"}]}
        reversed_data = {key: list(reversed(value)) for key, value in data.items()}
        self.assertEqual(flow.render(parsed, {}, data), flow.render(parsed, {}, reversed_data))


class RetroSeedingTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root, _ = setup(Path(directory.name), invoke)

    def call(self, *args, expect=0):
        result = invoke(["--project", str(self.root), "--json", *map(str, args)])
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_init_seeds_and_skills_preserve_or_restore_the_retrospective(self):
        retro = self.root / RETRO
        self.assertEqual(retro.read_bytes(), TEMPLATE)
        self.assertIn(b"[docs/flow-retro.md](flow-retro.md)", (self.root / VIEW).read_bytes())
        retro.write_text("# Our retro\n\nThe approve gate was too early.\n")
        edited = retro.read_bytes()
        self.call("skills")
        self.assertEqual(retro.read_bytes(), edited, "a refresh must never overwrite the retrospective")
        manifest = json.loads((self.root / ".roclec/installation.json").read_text())
        self.assertNotIn(RETRO, manifest["managed"])
        retro.unlink()
        self.call("skills")
        self.assertEqual(retro.read_bytes(), TEMPLATE)
        self.call("skills")
        self.assertEqual(retro.read_bytes(), TEMPLATE)

    def test_kernel_projection_reads_records_only(self):
        before = files(self.root)
        kernel = Kernel(load_profile(self.root))
        data = kernel._flow_learning()
        self.assertEqual(set(data), set(flow.LEARNING_KEYS))
        self.assertEqual(files(self.root), before)


class RetroInitTest(unittest.TestCase):
    def test_init_keeps_an_existing_retrospective(self):
        from scripts.c1_scenarios import init_trunk, profile
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root, config = workspace / "project", workspace / "profile.toml"
            profile(config)
            init_trunk(root)
            (root / "docs").mkdir()
            (root / RETRO).write_text("# Kept\n")
            result = invoke(["--json", "init", str(root), "--profile", str(config)])
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual((root / RETRO).read_text(), "# Kept\n")


if __name__ == "__main__":
    unittest.main()
