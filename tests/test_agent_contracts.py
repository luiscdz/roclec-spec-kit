"""Canonical role contracts shipped in assets/agents/ (M-28, TR.2)."""
from importlib.resources import files
import re
import tomllib
import unittest


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


if __name__ == "__main__":
    unittest.main()
