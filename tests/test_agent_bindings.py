"""Generated host bindings for subagent roles, installed as managed files (M-28, TR.3)."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest import mock

from roclec_spec_kit import agents
from roclec_spec_kit.installation import _native
from roclec_spec_kit.model import ModelError, sha
from roclec_spec_kit.store import Store
from scripts.c1_scenarios import put_json, tree
from scripts.c2_scenarios import setup
from test_kernel import invoke

MARKER = "<!-- managed by roclec-spec-kit -->"
MANIFEST = ".roclec/installation.json"
ROLES = ("implementer", "reviewer", "specifier")


def paths(role):
    return (f".claude/agents/roclec-{role}.md", f".codex/agents/roclec-{role}.toml")


def frontmatter(content):
    """Line-based parse of a Claude binding's frontmatter, unquoting JSON-style values."""
    text = content.decode("utf-8")
    assert text.startswith("---\n"), text[:40]
    head, body = text[4:].split("\n---\n", 1)
    fields = {}
    for line in head.split("\n"):
        key, value = line.split(": ", 1)
        fields[key] = json.loads(value) if value.startswith('"') else value
    return fields, body.removeprefix("\n")


class BindingSerializationTest(unittest.TestCase):
    def test_roles_bound_and_names_cannot_collide(self):
        self.assertEqual(tuple(sorted(agents.subagent_roles())), ROLES)
        for role in agents.contracts():
            self.assertRegex(role, r"^[a-z]+$", "binding paths rely on one-word role names")

    def test_capability_mapping(self):
        self.assertEqual(agents.claude_tools(["read"]), ["Read", "Grep", "Glob", "Skill"])
        self.assertEqual(agents.claude_tools(["run-checks", "edit-component", "read", "record-evidence"]),
                         ["Read", "Grep", "Glob", "Edit", "Write", "Bash", "Skill"])
        self.assertEqual(agents.claude_tools(["read", "edit-trunk", "edit-change-workspace"]),
                         ["Read", "Grep", "Glob", "Edit", "Write", "Skill"])
        self.assertEqual(agents.codex_sandbox(["read"]), "read-only")
        self.assertEqual(agents.codex_sandbox(["read", "run-checks"]), "workspace-write")
        with self.assertRaises(ValueError):
            agents.claude_tools(["read", "delegate"])

    def test_claude_frontmatter_parses_and_model_is_optional(self):
        for role in ROLES:
            meta = agents.contracts()[role]["meta"]
            for model in (None, "m-a: tuned, v2 #1"):
                with self.subTest(role=role, model=model):
                    fields, body = frontmatter(agents.claude_binding(role, model))
                    expected = {"name": f"roclec-{role}", "description": meta["description"],
                                "tools": ", ".join(agents.claude_tools(meta["capabilities"]))}
                    if model:
                        expected["model"] = model
                    self.assertEqual(fields, expected)
                    self.assertEqual(body, agents.instructions(role))

    def test_codex_toml_round_trips(self):
        for role in ROLES:
            meta = agents.contracts()[role]["meta"]
            for model in (None, "m-b"):
                with self.subTest(role=role, model=model):
                    text = agents.codex_binding(role, model).decode("utf-8")
                    self.assertTrue(text.startswith("# managed by roclec-spec-kit\n"))
                    expected = {"name": f"roclec-{role}", "description": meta["description"],
                                "sandbox_mode": agents.codex_sandbox(meta["capabilities"]),
                                "developer_instructions": agents.instructions(role)}
                    if model:
                        expected["model"] = model
                    self.assertEqual(tomllib.loads(text), expected)

    def test_instructions_are_the_contract_body_plus_the_skill_line(self):
        for role in ROLES:
            contract = agents.contracts()[role]
            text = agents.instructions(role)
            line = "Skills: " + ", ".join(f"`{s}`" for s in contract["meta"]["skills"]) + ".\n\n"
            self.assertIn(line, text)
            self.assertEqual(text.replace(line, "", 1), contract["body"])

    def test_toml_escaping_is_exact_for_hostile_text(self):
        samples = ['', 'plain', 'a "quoted" \\ path', '"""', '""""""', 'ends with "', 'ends with \\',
                   'tab\there', 'cr\rlf\r\n', 'nul\x00bell\x07del\x7f', 'unicode é   \U0001F600',
                   "'''literal'''", '\n\nleading newlines', 'trailing newline\n']
        for value in samples:
            with self.subTest(value=value):
                for multiline in (False, True):
                    document = "v = " + agents.toml_string(value, multiline=multiline) + "\n"
                    self.assertEqual(tomllib.loads(document)["v"], value)

    def test_yaml_values_are_quoted_and_single_line(self):
        self.assertEqual(json.loads(agents.yaml_string('a: b, "c" \\ d')), 'a: b, "c" \\ d')
        for value in ("a\nb", "a b", "", "a\x85b"):
            with self.subTest(value=value), self.assertRaises(ModelError) as caught:
                agents.yaml_string(value)
            self.assertEqual(caught.exception.issue["code"], "INVALID_INPUT")

    def test_native_rule_matches_only_generated_binding_shapes(self):
        for relative in (".claude/agents/roclec-implementer.md", ".codex/agents/roclec-reviewer.toml",
                         ".claude/agents/roclec-retired.md"):
            self.assertTrue(_native(relative), relative)
        for relative in (".claude/agents/roclec-dev-reviewer.md", ".codex/agents/roclec-dev-reviewer.toml",
                         ".claude/agents/my-role.md", ".codex/agents/my-role.toml", ".claude/agents/roclec-.md",
                         ".claude/agents/roclec-reviewer.toml", ".codex/agents/roclec-reviewer.md",
                         ".claude/agents/sub/roclec-reviewer.md", ".claude/agents/roclec-Reviewer.md",
                         ".claude/agents/roclec-reviewer2.md", ".agents/agents/roclec-reviewer.md",
                         ".codex/config.toml", ".codex/prompts/speckit.plan.md"):
            self.assertFalse(_native(relative), relative)


class BindingInstallationTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)
        self.root, _ = setup(self.workspace / "install", invoke, names=("engine",))
        self.install()

    def run_cli(self, *args):
        result = invoke(["--project", str(self.root), "--json", *args])
        return result.returncode, json.loads(result.stdout)

    def install(self, *args):
        code, payload = self.run_cli("skills", *args)
        self.assertEqual(code, 0, payload)
        return payload["data"]

    def rejected(self, issue, *args, exit_code=1):
        before = tree(self.root)
        code, payload = self.run_cli("skills", *args)
        self.assertEqual(code, exit_code, payload)
        self.assertEqual(payload["issues"][0]["code"], issue, payload)
        self.assertEqual(tree(self.root), before, "a rejected refresh must not write")
        self.assertFalse(list((self.root / ".roclec/runtime").glob("*.json")), "no journal is left behind")
        return payload["issues"][0]

    def pin(self, text):
        config = self.root / ".roclec/project.toml"
        body = config.read_text(encoding="utf-8").split("\n[agents.", 1)[0].rstrip("\n") + "\n"
        config.write_text(body + text, encoding="utf-8")

    def manifest(self):
        return json.loads((self.root / MANIFEST).read_text(encoding="utf-8"))

    def bindings(self, root=None):
        root = root or self.root
        return {p.relative_to(root).as_posix(): p.read_bytes()
                for folder in (".claude/agents", ".codex/agents") for p in sorted((root / folder).glob("*")) if p.is_file()}

    def test_install_writes_subagent_bindings_only(self):
        expected = {p for role in ROLES for p in paths(role)}
        self.assertEqual(set(self.bindings()), expected)
        self.assertFalse(any("coordinator" in p for p in self.bindings()))
        manifest = self.manifest()
        self.assertLessEqual(expected, set(manifest["managed"]))
        for role in ROLES:
            claude, codex = (self.root / p for p in paths(role))
            self.assertEqual(claude.read_bytes(), agents.claude_binding(role))
            self.assertEqual(codex.read_bytes(), agents.codex_binding(role))
            self.assertNotIn("model", frontmatter(claude.read_bytes())[0])
            self.assertNotIn("model", tomllib.loads(codex.read_text(encoding="utf-8")))

    def test_install_into_component_repo_writes_bindings(self):
        linked = self.workspace / "install/linked code"
        linked.mkdir()
        config = self.root / ".roclec/project.toml"
        config.write_text(config.read_text(encoding="utf-8").replace('repo = "."', 'repo = "../linked code"'), encoding="utf-8")
        self.install("--into", "engine")
        self.assertEqual(self.bindings(linked), self.bindings())

    def test_pinned_models_reach_only_their_role_and_host(self):
        before = self.bindings()
        self.pin('[agents.implementer]\nclaude = "m-a"\ncodex = "m-b"\n')
        self.install()
        after = self.bindings()
        claude, codex = paths("implementer")
        self.assertEqual(frontmatter(after[claude])[0]["model"], "m-a")
        self.assertEqual(tomllib.loads(after[codex].decode("utf-8"))["model"], "m-b")
        self.assertEqual({p for p in after if after[p] != before[p]}, {claude, codex})
        for role in ("reviewer", "specifier"):
            self.assertNotIn(b"model", b"".join(after[p].split(b"\n---\n")[0] if p.endswith(".md") else
                                                after[p].split(b"developer_instructions")[0] for p in paths(role)))

    def test_model_change_rewrites_only_that_binding(self):
        self.pin('[agents.implementer]\nclaude = "m-a"\ncodex = "m-b"\n')
        self.install()
        before = tree(self.root)
        self.pin('[agents.implementer]\nclaude = "m-c"\ncodex = "m-b"\n')
        data = self.install()
        after = tree(self.root)
        changed = {p for p in set(before) | set(after) if before.get(p) != after.get(p) and not p.startswith(".roclec/")}
        self.assertEqual(changed, {paths("implementer")[0]})
        self.assertEqual(data["receipt"]["writes"][paths("implementer")[0]],
                         sha(agents.claude_binding("implementer", "m-c")))
        self.assertEqual(frontmatter((self.root / paths("implementer")[0]).read_bytes())[0]["model"], "m-c")

    def test_repeat_installs_produce_identical_bytes(self):
        first = self.bindings()
        for relative in first:
            (self.root / relative).unlink()
        self.install()
        self.assertEqual(self.bindings(), first)
        other, _ = setup(self.workspace / "other", invoke, names=("engine",))
        code = invoke(["--project", str(other), "--json", "skills"]).returncode
        self.assertEqual(code, 0)
        self.assertEqual(self.bindings(other), first)

    def plant_retired(self):
        manifest = self.manifest()
        planted = [".claude/agents/roclec-retired.md", ".codex/agents/roclec-retired.toml"]
        for relative in planted:
            content = f"# managed by roclec-spec-kit\n{MARKER}\nretired role\n".encode("utf-8")
            (self.root / relative).write_bytes(content)
            manifest["files"][relative] = sha(content)
            manifest["managed"].append(relative)
        put_json(self.root / MANIFEST, manifest)
        return planted

    def test_retired_role_is_pruned_on_both_hosts(self):
        planted = self.plant_retired()
        data = self.install()
        for relative in planted:
            self.assertFalse((self.root / relative).exists(), relative)
            self.assertIsNone(data["receipt"]["writes"][relative])
        self.assertTrue((self.root / ".claude/agents").is_dir() and (self.root / ".codex/agents").is_dir())
        self.assertEqual(set(self.bindings()), {p for role in ROLES for p in paths(role)})

    def test_edited_bindings_reject_refresh(self):
        planted = self.plant_retired()
        retired = self.root / planted[1]
        retired.write_bytes(retired.read_bytes() + b"# consumer note\n")
        issue = self.rejected("MANAGED_FILE_EDITED")
        self.assertEqual(issue["actual"], [planted[1]])
        retired.unlink()
        self.install()
        self.install()  # Steady state with a recorded receipt.
        for relative in paths("reviewer"):
            with self.subTest(relative=relative):
                path = self.root / relative
                original = path.read_bytes()
                path.write_bytes(original + b"\n# consumer addition that keeps the marker\n")
                issue = self.rejected("MANAGED_FILE_EDITED")
                self.assertEqual(issue["actual"], [relative])
                path.write_bytes(original)

    def test_retired_binding_edited_after_its_hash_check_is_not_deleted(self):
        planted = self.plant_retired()
        target = self.root / planted[0]
        judged = target.read_bytes()
        edited = judged + b"edited after the hash check\n"
        real_sha = sha
        calls = []

        def racing_sha(content):
            # Edit the file right after the installer hashed the bytes it read,
            # i.e. between the retirement check and the journal.
            digest = real_sha(content)
            if content == judged and not calls:
                calls.append(True)
                target.write_bytes(edited)
            return digest

        with mock.patch("roclec_spec_kit.installation.sha", racing_sha):
            code, payload = self.run_cli("skills")
        self.assertTrue(calls, "the hook ran inside the retirement check")
        self.assertEqual(code, 3, payload)
        self.assertEqual(payload["issues"][0]["code"], "BASE_CONFLICT")
        self.assertEqual(target.read_bytes(), edited, "the edited retired binding is not deleted")
        self.assertTrue((self.root / planted[1]).is_file(), "nothing else was pruned")
        self.assertFalse(list((self.root / ".roclec/runtime").glob("*.json")))

    def test_unmarked_file_at_binding_path_is_unmanaged(self):
        for relative in paths("specifier"):
            with self.subTest(relative=relative):
                path = self.root / relative
                original = path.read_bytes()
                path.write_bytes(b"consumer-owned definition\n")
                self.rejected("UNMANAGED_FILE")
                path.write_bytes(original)

    def test_consumer_roles_survive_even_if_a_manifest_names_them(self):
        own = {".claude/agents/my-role.md": b"---\nname: my-role\n---\nMine\n",
               ".codex/agents/my-role.toml": b'name = "my-role"\n',
               # Marked, hyphenated names a consumer (or this repo) may use.
               ".claude/agents/roclec-dev-reviewer.md": f"{MARKER}\nconsumer dev role\n".encode("utf-8"),
               ".codex/agents/roclec-dev-reviewer.toml": b"# managed by roclec-spec-kit\nname = \"x\"\n"}
        manifest = self.manifest()
        for relative, content in own.items():
            (self.root / relative).write_bytes(content)
            manifest["files"][relative] = sha(content)
            manifest["managed"].append(relative)
        put_json(self.root / MANIFEST, manifest)
        self.install()
        self.install()
        for relative, content in own.items():
            self.assertEqual((self.root / relative).read_bytes(), content, relative)
        self.assertFalse(set(own) & set(self.manifest()["managed"]))

    def test_binding_edited_during_validation_is_not_overwritten(self):
        self.install()
        target = self.root / paths("implementer")[0]
        original = Store.apply

        def racing(store, *args, **kwargs):
            target.write_bytes(target.read_bytes() + b"\nconcurrent marked edit\n")
            return original(store, *args, **kwargs)

        (self.root / paths("reviewer")[1]).unlink()  # Make the refresh effective, not a replay.
        with mock.patch.object(Store, "apply", racing):
            code, payload = self.run_cli("skills")
        self.assertEqual(code, 3, payload)
        self.assertEqual(payload["issues"][0]["code"], "BASE_CONFLICT")
        self.assertTrue(target.read_bytes().endswith(b"concurrent marked edit\n"))
        self.assertFalse((self.root / paths("reviewer")[1]).exists(), "nothing written")
        self.assertFalse(list((self.root / ".roclec/runtime").glob("*.json")))


if __name__ == "__main__":
    unittest.main()
