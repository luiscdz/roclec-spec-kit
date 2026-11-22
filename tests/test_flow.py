import tempfile
import tomllib
import unittest
from importlib.resources import files
from pathlib import Path

from roclec_spec_kit import flow
from roclec_spec_kit.model import ModelError

DEFAULT = files("roclec_spec_kit").joinpath("assets/project/flow.toml").read_bytes()


def edit(mutate):
    data = tomllib.loads(DEFAULT.decode())
    mutate(data)
    return data


def dump(data):
    def value(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int,)):
            return str(v)
        if isinstance(v, str):
            return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
        if isinstance(v, list):
            return "[" + ", ".join(value(i) for i in v) + "]"
        return "{ " + ", ".join(f"{k} = {value(x)}" for k, x in v.items()) + " }"

    out = []
    for key, val in data.items():
        if not isinstance(val, dict):
            out.append(f"{key} = {value(val)}")
    for section in ("roles", "criteria", "stages"):
        for name, table in data.get(section, {}).items():
            out.append(f"\n[{section}.{name}]")
            out.extend(f"{k} = {value(v)}" for k, v in table.items())
    return "\n".join(out).encode()


class FlowTests(unittest.TestCase):
    def reject(self, mutate, code="FLOW_INVALID", root=None):
        with self.assertRaises(ModelError) as ctx:
            flow.parse(dump(edit(mutate)), root)
        issue = ctx.exception.issue
        self.assertEqual(issue["code"], code)
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertTrue(issue["remediation"])
        self.assertTrue(issue["entity"])
        return issue

    def test_default_asset(self):
        parsed = flow.parse(DEFAULT)
        self.assertEqual(parsed["warnings"], [])
        self.assertEqual([s["name"] for s in parsed["stages"]], list(flow.STAGES))
        self.assertEqual(parsed["view"], "docs/flow.md")
        self.assertEqual(flow.parse(dump(edit(lambda d: None)))["stages"], parsed["stages"])

    def test_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ModelError) as ctx:
                flow.load(Path(tmp))
            self.assertEqual(ctx.exception.issue["code"], "FLOW_MISSING")
            self.assertIn("roclec skills", ctx.exception.issue["remediation"])
            (Path(tmp) / ".roclec").mkdir()
            (Path(tmp) / flow.FLOW_PATH).write_bytes(DEFAULT)
            self.assertEqual(flow.load(Path(tmp))["schema"], 1)

    def test_decode_errors(self):
        for raw in (b"\xff\xfe", b"schema = ["):
            with self.assertRaises(ModelError) as ctx:
                flow.parse(raw)
            self.assertEqual(ctx.exception.issue["code"], "FLOW_INVALID")

    def test_top_level(self):
        self.reject(lambda d: d.update(extra=1))
        self.reject(lambda d: d.update(schema=2))
        self.reject(lambda d: d.update(view="../x.md"))
        self.reject(lambda d: d.update(view="/x.md"))
        self.reject(lambda d: d.update(view=".roclec/x.md"))
        self.reject(lambda d: d.update(view="docs\\x.md"))
        self.reject(lambda d: d.update(view="docs/x.txt"))
        self.reject(lambda d: d.update(view="specs/capabilities/CAP-001.md"))
        self.reject(lambda d: d.update(view="AGENTS.md"))
        self.reject(lambda d: d.update(view="CLAUDE.md"))
        self.reject(lambda d: d.update(view=".claude/agents/roclec-implementer.md"))
        self.reject(lambda d: d.update(view=".agents/skills/x.md"))
        self.assertEqual(flow.parse(dump(edit(lambda d: d.update(view="a/b.md"))))["view"], "a/b.md")

    def test_decider_must_be_text(self):
        self.reject(lambda d: d["stages"]["approve"]["checkpoint"].update(decider=[]))

    def test_stages(self):
        self.reject(lambda d: d["stages"].update(extra=dict(d["stages"]["define"])))
        self.reject(lambda d: d["stages"].pop("verify"))
        reordered = edit(lambda d: d.update(stages=dict(reversed(list(d["stages"].items())))))
        self.assertEqual([s["name"] for s in flow.parse(dump(reordered))["stages"]], list(flow.STAGES))

    def test_ai_reason(self):
        self.reject(lambda d: d["stages"]["approve"].pop("reason"))
        self.reject(lambda d: d["stages"]["define"].update(reason="x"))
        self.reject(lambda d: d["stages"]["approve"].update(ai=True))
        self.reject(lambda d: d["stages"]["define"].update(ai="yes"))

    def test_roles(self):
        self.reject(lambda d: d["stages"]["define"].update(role="ghost"))
        self.reject(lambda d: d["stages"]["approve"].update(role="reviewer"))
        self.reject(lambda d: d["stages"]["approve"]["checkpoint"].update(decider="reviewer"))
        self.reject(lambda d: d["roles"].update(coordinator=dict(kind="human")))
        self.reject(lambda d: d["roles"].update({"roclec-helper": dict(kind="human")}))
        self.reject(lambda d: d["roles"]["owner"].update(kind="robot"))
        self.reject(lambda d: d["roles"].update(Bad=dict(kind="human")))

    def test_agent_binding(self):
        def declare(d):
            d["roles"]["bot"] = dict(kind="agent")
            d["stages"]["define"]["role"] = "bot"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reject(declare, root=root)
            self.assertIsNotNone(flow.parse(dump(edit(declare)), None))
            (root / ".claude" / "agents").mkdir(parents=True)
            (root / ".claude" / "agents" / "bot.md").write_text("x")
            self.assertEqual(flow.parse(dump(edit(declare)), root)["roles"]["bot"]["kind"], "agent")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".codex" / "agents").mkdir(parents=True)
            (root / ".codex" / "agents" / "bot.toml").write_text("x")
            flow.parse(dump(edit(declare)), root)

        def human_agent(d):
            d["roles"]["bot"] = dict(kind="agent")
            d["stages"]["approve"]["role"] = "bot"

        self.reject(human_agent)

    def test_checkpoints(self):
        self.reject(lambda d: d["stages"]["define"].update(checkpoint=dict(decider="owner", on_reject="revise")))
        self.reject(lambda d: d["stages"]["approve"].pop("checkpoint"))
        self.reject(lambda d: d["stages"]["foundation"].pop("checkpoint"))
        self.reject(lambda d: d["stages"]["approve"]["checkpoint"].update(criteria=["CR-099"]))
        self.reject(lambda d: d["stages"]["approve"]["checkpoint"].update(criteria=["CR-002", "CR-002"]))
        self.reject(lambda d: d["stages"]["approve"]["checkpoint"].update(criteria="CR-002"))
        self.reject(lambda d: d["stages"]["approve"]["checkpoint"].update(on_reject="retry"))
        # Handoff decides an immutable integration record: only defer.
        for consequence in ("revise", "cancel"):
            self.reject(lambda d: d["stages"]["release"].update(checkpoint=dict(decider="owner", on_reject=consequence)))
        flow.parse(dump(edit(lambda d: d["stages"]["release"].update(checkpoint=dict(decider="owner", on_reject="defer")))))
        self.reject(lambda d: d["criteria"]["CR-001"].update(text=" "))
        hook = lambda d: d["stages"]["implement"].update(checkpoint=dict(decider="owner", criteria=[], on_reject="defer"))
        self.assertEqual(flow.parse(dump(edit(hook)))["stages"][5]["checkpoint"]["on_reject"], "defer")

    def test_fields(self):
        self.reject(lambda d: d["stages"]["define"].update(skills=["a", "a"]))
        self.reject(lambda d: d["stages"]["define"].update(skills="a"))
        self.reject(lambda d: d["stages"]["define"].update(skills=["Bad"]))
        self.reject(lambda d: d["stages"]["define"].update(deliverables=["../x"]))
        self.reject(lambda d: d["stages"]["define"].update(deliverables=["a", "a"]))
        self.reject(lambda d: d["stages"]["define"].update(session_evidence="always"))
        self.reject(lambda d: d["stages"]["define"].update(description=""))
        ok = flow.parse(dump(edit(lambda d: d["stages"]["define"].update(
            deliverables=["docs/x.txt"], skills=["a-b"], session_evidence="required"))))
        self.assertEqual(ok["stages"][1]["session_evidence"], "required")

    def test_unused_criterion_warns(self):
        parsed = flow.parse(dump(edit(lambda d: d["criteria"].update({"CR-010": dict(text="Spare")}))))
        self.assertEqual([w["code"] for w in parsed["warnings"]], ["FLOW_CRITERION_UNUSED"])
        self.assertEqual(parsed["warnings"][0]["severity"], "warning")
        self.assertEqual(parsed["warnings"][0]["entity"], "criteria.CR-010")

    def test_point(self):
        parsed = flow.parse(DEFAULT)
        self.assertEqual(flow.point(parsed, "approve")["criteria"], ["CR-002", "CR-003"])
        self.assertIsNone(flow.point(parsed, "pre-implement"))
        self.assertIsNone(flow.point(parsed, "handoff"))
        with self.assertRaises(ModelError) as ctx:
            flow.point(parsed, "define")
        self.assertEqual(ctx.exception.issue["code"], "FLOW_INVALID")
        hooked = flow.parse(dump(edit(lambda d: d["stages"]["integrate"].update(
            checkpoint=dict(decider="owner", criteria=[], on_reject="cancel")))))
        self.assertEqual(flow.point(hooked, "pre-integrate"), flow.point(hooked, "integrate"))

    def evaluation(self, name, rows, outcome, code=None):
        parsed = flow.parse(DEFAULT)
        if code is None:
            return flow.evaluate(parsed, name, rows, outcome=outcome)
        with self.assertRaises(ModelError) as ctx:
            flow.evaluate(parsed, name, rows, outcome=outcome)
        self.assertEqual(ctx.exception.issue["code"], code)
        return ctx.exception.issue

    def test_evaluate(self):
        met = [dict(id="CR-003", status="met"), dict(id="CR-002", status="n/a", reason="none")]
        self.assertEqual([r["id"] for r in self.evaluation("approve", met, "approved")], ["CR-002", "CR-003"])
        self.evaluation("approve", [dict(id="CR-002", status="not-met", reason="x"), met[0]], "approved", "CRITERIA_NOT_MET")
        self.evaluation("approve", met, "rejected", "CRITERIA_REQUIRED")
        rejected = [dict(id="CR-002", status="not-met", reason="x"), met[0]]
        self.assertEqual(len(self.evaluation("approve", rejected, "rejected")), 2)
        self.evaluation("approve", [dict(id="CR-002", status="n/a"), met[0]], "approved", "CRITERIA_REASON_REQUIRED")
        issue = self.evaluation("approve", [met[0]], "approved", "CRITERIA_MISMATCH")
        self.assertEqual(issue["expected"], ["CR-002", "CR-003"])
        self.assertEqual(issue["actual"], ["CR-003"])
        self.evaluation("approve", met + [dict(id="CR-009", status="met")], "approved", "CRITERIA_MISMATCH")
        self.assertEqual(self.evaluation("pre-implement", [], "approved"), [])
        self.evaluation("pre-implement", [dict(id="CR-001", status="met")], "approved", "CRITERIA_MISMATCH")
        # A point that declares no criteria can still be rejected, with an empty evaluation (D28).
        self.assertEqual(self.evaluation("pre-implement", [], "rejected"), [])
        self.evaluation("pre-implement", [dict(id="CR-001", status="not-met", reason="x")], "rejected", "CRITERIA_MISMATCH")
        self.evaluation("approve", [dict(id=2, status="met"), met[0]], "approved", "INVALID_INPUT")
        self.evaluation("approve", [dict(id="CR-002", status="met", reason=3), met[0]], "approved", "INVALID_INPUT")

    def test_render(self):
        parsed = flow.parse(DEFAULT)
        profile = {"agents": {"implementer": {"claude": "x"}}}
        first = flow.render(parsed, profile)
        self.assertEqual(first, flow.render(parsed, profile))
        header, _, body = first.partition(b"\n")
        self.assertTrue(header.startswith(b"<!-- roclec-managed-view sha256="))
        text = body.decode()
        self.assertIn("```mermaid\nflowchart LR", text)
        self.assertIn("claude `x`", text)
        self.assertIn("session model", text)
        self.assertIn("roclec views --write", text)
        self.assertEqual(sum(1 for l in text.splitlines() if l[:3] in tuple(f"| {n}" for n in range(1, 10)) or l.startswith("| 10 |")), 10)
        self.assertNotIn("claude `x`", flow.render(parsed, {}).decode())

    def test_escape(self):
        parsed = flow.parse(dump(edit(lambda d: d["criteria"]["CR-001"].update(text="a | b"))))
        self.assertIn("a \\| b", flow.render(parsed, {}).decode())

    def test_view_status(self):
        parsed = flow.parse(DEFAULT)
        rendered = flow.render(parsed, {})
        self.assertEqual(flow.view_status(parsed, {}, rendered), "current")
        self.assertEqual(flow.view_status(parsed, {}, None), "missing")
        changed = flow.parse(dump(edit(lambda d: d["stages"]["define"].update(description="Other"))))
        self.assertEqual(flow.view_status(changed, {}, rendered), "stale")
        self.assertEqual(flow.view_status(parsed, {"agents": {"reviewer": {"codex": "m"}}}, rendered), "stale")
        self.assertEqual(flow.view_status(parsed, {}, rendered + b"hand edit\n"), "edited")
        self.assertEqual(flow.view_status(parsed, {}, b"# my file\n"), "edited")


if __name__ == "__main__":
    unittest.main()
