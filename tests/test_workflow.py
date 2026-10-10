from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from roclec_spec_kit.cli import main
from roclec_spec_kit.config import load_project
from roclec_spec_kit.workflow import check_immutable


def run(*args: str) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        code = main(list(args))
    return code, output.getvalue()


class WorkflowTest(unittest.TestCase):
    def test_multi_component_release_gates_and_generated_views(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace) / "product-specs"
            api = Path(workspace) / "service"
            web = Path(workspace) / "frontend"
            api.mkdir()
            web.mkdir()
            code, output = run("init", str(root), "--name", "Example", "--component", "service=../service", "--component", "frontend=../frontend", "--user-facing", "frontend")
            self.assertEqual(code, 0, output)
            self.assertTrue((root / ".agents/skills/roclec-coordinator/SKILL.md").is_file())
            design_lock = json.loads((root / "skills-lock.json").read_text())
            self.assertEqual(set(design_lock["skills"]), {"frontend-design", "impeccable", "ui-ux-pro-max", "web-design-guidelines"})
            self.assertEqual(run("--project", str(root), "check")[0], 0)
            code, output = run("--project", str(root), "skills", "--into", str(api))
            self.assertEqual(code, 0, output)
            self.assertEqual(load_project(api).root, root.resolve())

            code, output = run("--project", str(root), "new", "001-search", "--title", "Search", "--component", "service", "--component", "frontend")
            self.assertEqual(code, 0, output)
            self.assertEqual(run("--project", str(root), "check")[0], 0)
            self.assertEqual(run("--project", str(root), "check", "--gate", "001")[0], 1)
            spec_dir = root / "specs/001-search"
            spec_file = spec_dir / "spec.md"
            body = spec_file.read_text().replace("effort: TBD", "effort: S").replace("[NEEDS CLARIFICATION: define testable AC-NN scenarios before marking ready.]", "**AC-01** User can search.")
            spec_file.write_text(body.replace("status: draft", "status: ready"))
            (spec_dir / "ux.md").write_text("# UX\n")
            (spec_dir / "prototype").mkdir()
            (spec_dir / "prototype/index.html").write_text("<!doctype html><title>Search</title>")
            self.assertEqual(run("--project", str(root), "check", "--gate", "001")[0], 0)
            self.assertEqual(run("--project", str(root), "check", "--release-gate", "001")[0], 1)
            for component in ("service", "frontend"):
                code, output = run("--project", str(root), "release", "plan", component, "v0.1", "001")
                self.assertEqual(code, 0, output)
            self.assertEqual(run("--project", str(root), "check", "--release-gate", "001")[0], 0)

            spec_file.write_text(spec_file.read_text().replace("status: ready", "status: in-progress"))
            (spec_dir / "plan.md").write_text("# Plan\n")
            (spec_dir / "tasks.md").write_text("- [ ] T001 [service] Add endpoint\n- [ ] T002 [frontend] Add screen\n")
            code, output = run("--project", str(root), "check", "--write")
            self.assertEqual(code, 0, output)
            self.assertEqual(run("--project", str(root), "check")[0], 0)
            self.assertEqual(run("--project", str(root), "release", "close", "service", "v0.1")[0], 2)

            spec_file.write_text(spec_file.read_text().replace("status: in-progress", "status: done"))
            (spec_dir / "tasks.md").write_text("- [x] T001 [service] Add endpoint\n- [x] T002 [frontend] Add screen\n")
            for repo in (api, web):
                (repo / "tests").mkdir()
                (repo / "tests/test_search.py").write_text("def test_search():\n    # [001/AC-01]\n    assert True\n")
            code, output = run("--project", str(root), "check", "--coverage", "--write")
            self.assertEqual(code, 0, output)
            for component in ("service", "frontend"):
                release = root / "roadmap/releases" / component / "v0.1.md"
                release.write_text(release.read_text().replace("## Release Notes\n\n", "## Release Notes\n\n- Search is available.\n"))
                code, output = run("--project", str(root), "release", "close", component, "v0.1")
                self.assertEqual(code, 0, output)
            self.assertEqual(run("--project", str(root), "check", "--coverage")[0], 0)
            roadmap = root / "roadmap/ROADMAP.md"
            roadmap.write_text(roadmap.read_text() + "manual edit\n")
            self.assertEqual(run("--project", str(root), "check")[0], 1)
            self.assertEqual(run("--project", str(root), "check", "--write")[0], 0)

    def test_restore_pinned_skills_in_project_and_code_repo(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace) / "specs-repo"
            code_repo = Path(workspace) / "client"
            code_repo.mkdir()
            self.assertEqual(run("init", str(root), "--name", "Example", "--component", "client=../client", "--user-facing", "client")[0], 0)
            code_lock = {"version": 1, "skills": {"tanstack-query": {
                "source": "example/skills", "sourceType": "github", "skillPath": "skills/tanstack-query/SKILL.md", "computedHash": "a" * 64,
            }}}
            (code_repo / "skills-lock.json").write_text(json.dumps(code_lock))
            calls = []

            def fake_install(command, cwd, check):
                calls.append((command, cwd, check))
                lock = json.loads((cwd / "skills-lock.json").read_text())
                for name in lock["skills"]:
                    target = cwd / ".agents/skills" / name / "SKILL.md"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(f"---\nname: {name}\n---\n")
                return SimpleNamespace(returncode=0)

            with mock.patch("roclec_spec_kit.external_skills.shutil.which", return_value="/usr/bin/npx"), mock.patch("roclec_spec_kit.external_skills.subprocess.run", side_effect=fake_install):
                self.assertEqual(run("--project", str(root), "skills", "--restore")[0], 0)
                self.assertEqual(run("--project", str(root), "skills", "--into", str(code_repo), "--restore")[0], 0)
            self.assertEqual([cwd for _, cwd, _ in calls], [root.resolve(), code_repo.resolve()])
            self.assertEqual(calls[0][0], ["npx", "-y", "skills", "experimental_install"])
            self.assertTrue((code_repo / ".roclec/link.toml").is_file())
            self.assertTrue((root / ".claude/skills/impeccable/SKILL.md").is_file())
            self.assertTrue((code_repo / ".claude/skills/tanstack-query/SKILL.md").is_file())

    def test_restore_requires_a_lock(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace)
            self.assertEqual(run("init", str(root), "--name", "No UI")[0], 0)
            code, output = run("--project", str(root), "skills", "--restore")
            self.assertEqual(code, 2)
            self.assertIn("skills-lock.json is missing", output)

    def test_config_and_release_membership_are_rejected_when_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace)
            self.assertEqual(run("init", str(root), "--name", "Example")[0], 0)
            self.assertEqual(run("init", str(root), "--name", "Example")[0], 2)
            self.assertEqual(run("--project", str(root), "new", "001-one", "--title", "One")[0], 0)
            self.assertEqual(run("--project", str(root), "new", "001-two", "--title", "Two")[0], 2)
            spec = root / "specs/001-one/spec.md"
            spec.write_text(spec.read_text().replace("components: [app]", "components: [unknown]"))
            code, output = run("--project", str(root), "check")
            self.assertEqual(code, 1)
            self.assertIn("unknown component unknown", output)

    def test_future_ids_and_released_files_are_protected(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace)
            self.assertEqual(run("init", str(root), "--name", "Example")[0], 0)
            (root / "FUTURE.md").write_text("# Future ideas\n\n## FUT-001 — Idea\n")
            (root / "roadmap/fut-archive.md").write_text("# Archive\n\n| FUT-001 | promoted | 001 |\n")
            self.assertIn("live and archived", run("--project", str(root), "check")[1])
            (root / "FUTURE.md").write_text("# Future ideas\n")
            release = root / "roadmap/releases/app/v0.1.md"
            release.write_text("# app v0.1 — First\n\n**Status:** released\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "baseline"], cwd=root, check=True)
            release.write_text(release.read_text() + "changed\n")
            errors = check_immutable(load_project(root), "HEAD")
            self.assertEqual(len(errors), 1)
            self.assertIn("released file changed", errors[0])


if __name__ == "__main__":
    unittest.main()
