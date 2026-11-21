"""Canonical role contracts shipped in assets/agents/ (M-28, TR.2)."""
from importlib.resources import files
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

from roclec_spec_kit.agents import HOSTS, subagent_roles
from roclec_spec_kit.config import validate_profile
from roclec_spec_kit.model import ModelError

ASSETS = files("roclec_spec_kit").joinpath("assets")
ROLES = {"coordinator", "specifier", "implementer", "reviewer"}
CAPABILITIES = {"read", "edit-trunk", "edit-change-workspace", "edit-component", "run-checks", "record-evidence", "delegate"}
SECTIONS = ("## Responsibility", "## Inputs", "## Outputs", "## Prohibited", "## Escalation")
# Contracts are host- and model-neutral (plan section 2.1): the binding names models, never the contract.
VENDOR = re.compile(r"\b(claude|anthropic|opus|sonnet|haiku|fable|codex|openai|gpt|gemini|llama|mistral)\b", re.I)


def contract(name):
    text = ASSETS.joinpath("agents", f"{name}.md").read_text(encoding="utf-8")
    _, front, body = text.split("+++\n", 2)
    return tomllib.loads(front), body, text


class AgentContractTests(unittest.TestCase):
    def test_every_role_has_one_contract(self):
        names = {p.name.removesuffix(".md") for p in ASSETS.joinpath("agents").iterdir() if p.name.endswith(".md")}
        self.assertEqual(names, ROLES)

    def test_contract_shape(self):
        skills = {p.name for p in ASSETS.joinpath("skills").iterdir() if p.is_dir()}
        for name in sorted(ROLES):
            with self.subTest(role=name):
                meta, body, _ = contract(name)
                self.assertEqual(meta["role"], name)
                self.assertIn(meta["binding"], {"session", "subagent"})
                self.assertTrue(meta["description"].strip())
                self.assertTrue(meta["skills"])
                self.assertLessEqual(set(meta["skills"]), skills)
                self.assertLessEqual(set(meta["capabilities"]), CAPABILITIES)
                self.assertIn("<!-- managed by roclec-spec-kit -->", body)
                for section in SECTIONS:
                    self.assertIn(section, body)

    def test_only_the_coordinator_delegates_or_runs_in_session(self):
        for name in sorted(ROLES):
            meta, _, _ = contract(name)
            with self.subTest(role=name):
                self.assertEqual(meta["binding"] == "session", name == "coordinator")
                self.assertEqual("delegate" in meta["capabilities"], name == "coordinator")

    def test_reviewer_cannot_edit(self):
        meta, _, _ = contract("reviewer")
        self.assertFalse({c for c in meta["capabilities"] if c.startswith("edit")})

    def test_contracts_name_no_provider_or_model(self):
        for name in sorted(ROLES):
            with self.subTest(role=name):
                self.assertIsNone(VENDOR.search(contract(name)[2]))

    def test_skills_are_referenced_not_copied(self):
        for name in sorted(ROLES):
            meta, body, _ = contract(name)
            for skill in meta["skills"]:
                skill_text = ASSETS.joinpath("skills", skill, "SKILL.md").read_text(encoding="utf-8")
                paragraphs = [p.strip() for p in skill_text.split("\n\n") if len(p.strip()) > 120]
                with self.subTest(role=name, skill=skill):
                    self.assertFalse([p for p in paragraphs if p in body])


class AgentProfileTests(unittest.TestCase):
    """Optional [agents.<role>] host models in profile 3 (D10, TR.7)."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)

    def profile(self, agents=None):
        data = {"schema": 3, "name": "p", "trunk_ref": "refs/heads/main",
                "components": {"app": {"repo": ".", "user_facing": False, "inputs": ["src/**"], "generated": [],
                                       "verification": [], "target_ref": "refs/remotes/origin/main"}}}
        if agents is not None:
            data["agents"] = agents
        return validate_profile(self.root, data)

    def rejected(self, agents):
        with self.assertRaises(ModelError) as caught:
            self.profile(agents)
        issue = caught.exception.issue
        self.assertEqual(issue["code"], "INVALID_INPUT")
        self.assertTrue(issue["remediation"])
        return issue

    def test_profile_without_agents_inherits_session_model(self):
        profile = self.profile()
        for role in subagent_roles():
            for host in HOSTS:
                self.assertIsNone(profile.agent_model(role, host))

    def test_pinned_model_is_per_role_and_host(self):
        profile = self.profile({"implementer": {"claude": "model-a", "codex": "model-b"}, "reviewer": {"codex": "model-c"}})
        self.assertEqual(profile.agent_model("implementer", "claude"), "model-a")
        self.assertEqual(profile.agent_model("implementer", "codex"), "model-b")
        self.assertEqual(profile.agent_model("reviewer", "codex"), "model-c")
        self.assertIsNone(profile.agent_model("reviewer", "claude"))
        self.assertIsNone(profile.agent_model("specifier", "codex"))

    def test_unknown_role_and_coordinator_are_rejected(self):
        for role in ("architect", "coordinator"):
            with self.subTest(role=role):
                issue = self.rejected({role: {"claude": "model-a"}})
                self.assertEqual(issue["message"], "Unknown agent role")
                self.assertEqual(issue["expected"], list(subagent_roles()))

    def test_unsupported_host_is_rejected(self):
        issue = self.rejected({"implementer": {"other-host": "model-a"}})
        self.assertEqual(issue["message"], "Unsupported agent host")
        self.assertEqual(issue["expected"], list(HOSTS))

    def test_malformed_values_are_rejected(self):
        for agents in ([], {"implementer": "model-a"}, {"implementer": {"claude": ""}},
                       {"implementer": {"claude": 3}}, {"implementer": {"claude": "a\nb"}},
                       {"implementer": {"codex": 'a"b'}}, {"implementer": {"claude": " a"}}):
            with self.subTest(agents=agents):
                self.rejected(agents)

    def test_documented_example_profile_stays_valid(self):
        example = Path(__file__).resolve().parents[1] / "docs/examples/c1/profile.toml"
        text = example.read_text(encoding="utf-8")
        self.assertIn("# [agents.implementer]", text)
        validate_profile(self.root, tomllib.loads(text))
        enabled = "\n".join(line.removeprefix("# ") if line.startswith("# [agents") or line.startswith("# claude") or line.startswith("# codex") else line
                            for line in text.splitlines())
        self.assertIsNotNone(validate_profile(self.root, tomllib.loads(enabled)).agent_model("implementer", "claude"))


if __name__ == "__main__":
    unittest.main()
