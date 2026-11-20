"""Prepare semantic cases and validate fixture preconditions. Never calls a model.

The public CLI comes exclusively from an explicitly supplied wheel. Source-tree
helpers construct input JSON only; they do not import the Roclec runtime.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

try:
    from .c1_scenarios import bundle, digest, put_json, tree
except ImportError:
    from c1_scenarios import bundle, digest, put_json, tree

CATALOG = Path(__file__).with_name("semantic_cases.json")


def sha(content):
    return hashlib.sha256(content).hexdigest()


def subject_instructions(case, consumer, result):
    """Render an oracle-free subject entry point with deterministic failure semantics."""
    return (
        "# Prepared subject entry point — not executed\n\n"
        f"Work only in `{consumer}` and write your final report under `{result}`. Read the consumer's instructions and the requested installed skills. "
        "Do not read other scenarios or supervisor oracles, modify installed framework skills, spawn additional agents, contact external services, or touch the pilot. "
        "Use the consumer `.roclec/run` for native operations; CLI events are recorded outside the repo. Consult command `--help` before using an unfamiliar form. "
        "Classify an exit-1 structured workflow issue such as RELEASE_UNASSIGNED, REVIEW_REQUIRED or COVERAGE_MISSING as an observed domain gate, not a tool crash. "
        "Classify invalid invocation, IO failure, timeout, exception or unreadable output as a technical tool failure. Never retry the same failed command automatically. "
        "Continue after a domain gate only when the user request already authorizes the concrete prerequisite, no material decision is missing, and that prerequisite is changed before another check. "
        "If a real user decision is needed, write the concise question in the final report instead of contacting the actual user. "
        "Record commands, exit codes, issue codes, changed files/records, decisions still needed, final state and limits truthfully; do not grade yourself.\n\n"
        + "Skills: " + ", ".join(case["skills"]) + "\n\nUser request:\n\n" + case["request"] + "\n"
    )


def catalog():
    data = json.loads(CATALOG.read_text())
    cases = data["cases"]
    assert len({c["id"] for c in cases}) == len(cases)
    assert {c["partition"] for c in cases} <= {"main", "reserved"}
    for case in cases:
        assert case["request"] and case["skills"] and case["oracle"]["required"] and case["oracle"]["critical"]
    return cases


def contract(names=("engine",), *, prefix="", normal_ac="AC-001"):
    names = sorted(names)
    text = ("Normalize a label by removing exterior whitespace and uppercasing it. "
            "Reject an empty result or more than 64 input characters after trimming with ValueError. "
            f"Return the uppercase value prefixed by {prefix!r}.\n")
    contents = {"requirements/REQ-001.md": text,
                f"acceptance/{normal_ac}.md": f"Given '  abC  ', normalization returns {prefix + 'ABC'!r}.\n",
                "acceptance/AC-002.md": "Empty/whitespace-only labels and 65 trimmed characters raise ValueError; 64 are accepted.\n"}
    acs = sorted([normal_ac, "AC-002"])
    desc = {"model_schema": 1, "capability_id": "CAP-001", "requirements": [
        {"id": "REQ-001", "statement": "requirements/REQ-001.md", "components": names, "acceptance_ids": acs}],
        "acceptance": [{"id": ac, "scenario": f"acceptance/{ac}.md", "components": names} for ac in acs],
        "references": [], "files": {p: sha(b.encode()) for p, b in contents.items()}}
    return {"descriptor": desc, "revision": digest(desc), "content": contents}


def manual_contract():
    contents = {"requirements/REQ-001.md": "Provide a labeled text field and submit control. Verify the agreed interaction on a real iOS Safari device before claiming complete acceptance.\n",
                "acceptance/AC-001.md": "The HTML has a label associated with the input and a submit control.\n",
                "acceptance/AC-002.md": "On the target real iOS Safari device at 200% zoom, focus, entry and submit remain usable; record the actual device observation.\n"}
    desc = {"model_schema": 1, "capability_id": "CAP-001", "requirements": [
        {"id": "REQ-001", "statement": "requirements/REQ-001.md", "components": ["engine"], "acceptance_ids": ["AC-001", "AC-002"]}],
        "acceptance": [{"id": ac, "scenario": f"acceptance/{ac}.md", "components": ["engine"]} for ac in ("AC-001", "AC-002")],
        "references": [], "files": {p: sha(b.encode()) for p, b in contents.items()}}
    return {"descriptor": desc, "revision": digest(desc), "content": contents}


def product_source(*, prefix="", weak=False, scaffold=False):
    if scaffold:
        return 'def normalize(value):\n    raise NotImplementedError("Implementation pending")\n'
    return ("def normalize(value):\n    clean = value.strip()\n"
            + ("    if len(clean) > 64:\n" if weak else "    if not clean or len(clean) > 64:\n")
            + '        raise ValueError("Invalid label")\n'
            + f"    return {prefix!r} + clean.upper()\n")


def product_tests(*, prefix="", weak=False):
    common = "import unittest\nfrom src.labels import normalize\n\nclass LabelTest(unittest.TestCase):\n"
    if weak:
        return common + '    def test_result(self):\n        self.assertIsInstance(normalize("abc"), str)\n'
    return (common + f'    def test_normalization(self):\n        self.assertEqual(normalize("  abC  "), {prefix + "ABC"!r})\n'
            '    def test_rejections_and_boundary(self):\n'
            '        for value in ("", "   ", "x" * 65):\n'
            '            with self.subTest(value=value), self.assertRaises(ValueError):\n'
            '                normalize(value)\n'
            '        self.assertEqual(len(normalize("x" * 64)) - ' + str(len(prefix)) + ', 64)\n')


class Fixture:
    def __init__(self, directory, cli, python, case, capture):
        self.directory, self.cli, self.python, self.case = directory, cli, python, case
        self.root = directory / "consumer"
        self.root.mkdir(parents=True)
        self.events = []
        self.facts = {}
        self.capture = capture
        self.names = ("engine", "viewer") if case["fixture"] == "partial_revision" else ("engine",)

    def execute(self, argv, *, cwd=None, expected=0):
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        start = time.monotonic()
        result = subprocess.run(list(map(str, argv)), cwd=cwd or self.root, env=env, capture_output=True, text=True, timeout=120)
        event = {"schema": 1, "kind": "fixture-preparation", "argv": list(map(str, argv)), "cwd": str(cwd or self.root),
                 "exit": result.returncode, "expected_exit": expected, "duration_seconds": round(time.monotonic() - start, 6),
                 "stdout": result.stdout, "stderr": result.stderr}
        self.events.append(event)
        put_json(self.directory / "setup-events.json", self.events)
        if result.returncode != expected:
            raise RuntimeError(f"Fixture setup failed: {argv}: {result.stdout}\n{result.stderr}")
        return result

    def call(self, *args, expected=0):
        result = self.execute([self.cli, "--project", self.root, "--json", *args], expected=expected)
        data = json.loads(result.stdout)
        assert data["ok"] == (expected == 0)
        return data

    def git(self, *args, cwd=None, expected=0):
        return self.execute(["git", "-C", cwd or self.root, *args], expected=expected).stdout.strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "--allow-empty", "-qm", "Synthetic fixture checkpoint")
        return self.git("rev-parse", "HEAD")

    def profile(self, acs=("AC-001", "AC-002"), *, user_facing=False):
        lines = ['schema = 2', 'name = "Isolated semantic fixture"']
        check = {"id": "unit", "argv": [str(self.python), "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
                 "cwd": ".", "timeout_seconds": 30, "acceptance_ids": sorted(acs)}
        inline = "{" + ", ".join(k + "=" + json.dumps(v) for k, v in check.items()) + "}"
        for name in self.names:
            lines.extend([f"[components.{name}]", 'repo = "."', f'user_facing = {str(user_facing).lower()}',
                          'inputs = ["src/*.py", "tests/*.py", "ui/**", "docs/**", "AGENTS.md", "CLAUDE.md", ".agents/skills/**", ".claude/skills/**"]',
                          'generated = ["build/**", "**/__pycache__/**"]', 'excluded = [".venv/**"]', f"verification = [{inline}]"])
        return "\n".join(lines) + "\n"

    def initialize(self):
        kind = self.case["fixture"]
        manual = kind == "manual_observation"
        profile_file = self.directory / "input-profile.toml"
        profile_file.write_text(self.profile(("AC-001",) if manual else ("AC-001", "AC-002"), user_facing=manual))
        self.call("init", self.root, "--profile", profile_file)
        self.call("skills")
        for name in ("src", "tests", "docs"):
            (self.root / name).mkdir(exist_ok=True)
        source = ("# Synthetic foundation\n\nThese agreements apply only to this isolated fixture, not to a real product.\n"
                  "Context: a local label-normalization utility, with no external users or real data.\n"
                  "Principles: preserve provenance, authorization, evidence and consumer-owned files.\n"
                  "Architecture and stack: a pure Python function in src/labels.py, standard library and unittest; no service or database.\n"
                  "Engineering: explicit ACs, meaningful assertions, public Roclec CLI and immutable history.\n"
                  "Verification: run configured tests; a pass does not prove assertion quality, manual observation or user approval.\n"
                  "Design when applicable: a labeled field and submit control; target-device acceptance requires an actual observation.\n")
        (self.root / "docs/foundation.md").write_text(source)
        roles = sorted(["context", "principles", "architecture", "stack", "engineering", "verification"] + (["design"] if manual else []))
        put_json(self.root / ".roclec/references.json", {"model_schema": 1, "references": [
            {"id": role, "path": "docs/foundation.md", "components": list(self.names), "role": role, "decision_id": "fixture-foundation"} for role in roles]})
        put_json(self.root / ".roclec/decisions/fixture-foundation.json", {"model_schema": 1, "id": "fixture-foundation", "kind": "foundation",
            "status": "agreed", "actor": "Synthetic fixture owner", "reason": "Governing facts for this sandbox only", "sources": {r: sha(source.encode()) for r in roles}})
        if kind in {"conflicting_foundation", "draft"}:
            (self.root / "docs/budget.md").write_text("# Budget decision\n\nEstimate for the local label normalizer accepted. This is not approval of a change digest, stack replacement or implementation.\n")
        if kind == "conflicting_foundation":
            (self.root / "docs/technical-proposal.md").write_text("# Technical proposal\n\nStatus: proposed, no adoption decision.\nReplace the agreed pure module with a network service and SQL database. The accepted budget does not decide this alternative.\n")
        self.write_product(weak=kind in {"weak_tests", "self_review"}, scaffold=kind in {"empty", "draft", "conflicting_foundation"})
        if manual:
            (self.root / "ui").mkdir()
            (self.root / "ui/form.html").write_text('<form><label for="label">Label</label><input id="label"><button type="submit">Save</button></form>\n')
            (self.root / "tests/test_labels.py").write_text('import unittest\nfrom pathlib import Path\n\nclass HtmlTest(unittest.TestCase):\n    def test_structure(self):\n        html = Path("ui/form.html").read_text()\n        self.assertIn(\'for="label"\', html)\n        self.assertIn(\'id="label"\', html)\n        self.assertIn(\'type="submit"\', html)\n')
        (self.root / ".gitignore").write_text(".roclec/runtime/\n.venv/\n__pycache__/\n*.pyc\nbuild/\n")
        bin_dir = self.root / ".venv/bin"
        bin_dir.mkdir(parents=True)
        output = self.directory / "observations"
        output.mkdir()
        wrapper = ("#!/bin/sh\nexec " + shlex.quote(str(self.python)) + " " + shlex.quote(str(self.capture)) + " "
                   + shlex.quote(str(output)) + " " + shlex.quote(str(self.cli)) + ' "$@"\n')
        (bin_dir / "roclec").write_text(wrapper)
        (bin_dir / "roclec").chmod(0o755)
        self.git("init", "-q")
        self.git("config", "user.name", "Synthetic fixture owner")
        self.git("config", "user.email", "fixture@example.invalid")
        remote = self.directory / "remote.git"
        remote.mkdir()
        self.git("init", "--bare", "-q", cwd=remote)
        self.git("remote", "add", "origin", str(remote))
        self.base = self.commit()
        self.facts.update(base_commit=self.base, remote=str(remote), components=list(self.names), fixture_kind=kind)

    def write_product(self, *, prefix="", weak=False, scaffold=False):
        (self.root / "src/labels.py").write_text(product_source(prefix=prefix, weak=weak, scaffold=scaffold))
        path = self.root / "tests/test_labels.py"
        if scaffold:
            if path.exists(): path.unlink()
        else:
            path.write_text(product_tests(prefix=prefix, weak=weak))

    def define(self, change_id="CHG-001", *, target=None, base=None, kind="evolution", approved=True, components=None):
        components = components or self.names
        source = self.directory / "inputs" / change_id
        target = target or contract(components)
        record = bundle(source, change_id=change_id, target=target, base=base, components=components, kind=kind)
        body = (f"# {change_id}\n\nSynthetic scenario intent: " + ("restore the exact existing obligation" if kind == "fix" else "deliver the explicitly described label behavior") + ".\n")
        (source / "proposal.md").write_text(body)
        record["semantic"]["files"]["proposal.md"] = sha(body.encode())
        record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
        put_json(source / "change.json", record)
        self.call("change", "new", "--file", source / "change.json")
        if approved:
            self.call("change", "approve", change_id, "--digest", record["proposal_digest"], "--actor", "Synthetic fixture owner", "--reason", "Explicit initial fixture scope, not a real product approval")
        return record, target

    def assign(self, change_id="CHG-001", *, version="v1.0.0", component=None, members=None):
        for name in ([component] if component else self.names):
            args = ["release", "plan", name, version]
            for member in members or [change_id]: args.extend(["--change", member])
            self.call(*args)

    def run(self, change_id="CHG-001", *, component="engine", release=None, expected=0):
        target = ["--release", release] if release else [change_id]
        return self.call("run", "verify", *target, "--component", component, "--base", self.base, expected=expected)["data"]["run"]

    def integrate(self, change_id="CHG-001", *, component="engine"):
        run = self.run(change_id, component=component)
        self.commit()
        out = self.directory / f"integrate-{change_id}-{component}.json"
        self.call("integrate", "prepare", change_id, "--component", component, "--run", run["id"], "--out", out)
        self.call("operation", "apply", out)
        self.commit()

    def prepare_release(self, version="v1.0.0"):
        run = self.run(release=version)
        self.commit()
        out = self.directory / f"prepare-{version}.json"
        plan = self.call("release", "prepare", "engine", version, "--run", run["id"], "--out", out)["data"]["plan"]
        self.call("operation", "apply", out)
        self.commit()
        return plan

    def publish(self, version="v1.0.0", *, remote=True):
        plan = self.prepare_release(version)
        self.git("tag", version, plan["inputs"]["candidate"]["head"])
        if remote:
            self.git("push", "origin", "refs/tags/" + version)
            out = self.directory / f"record-{version}.json"
            self.call("release", "record", "engine", version, "--preparation", plan["inputs"]["preparation"],
                      "--commit", plan["inputs"]["candidate"]["head"], "--tag", version, "--remote", "origin",
                      "--actor", "Synthetic fixture owner", "--reason", "Existing disposable-remote publication", "--out", out)
            self.call("operation", "apply", out)
            self.commit()
        self.facts.update(preparation=plan["inputs"]["preparation"], prepared_commit=plan["inputs"]["candidate"]["head"])

    def build(self):
        self.initialize()
        kind = self.case["fixture"]
        if kind in {"empty", "conflicting_foundation"}:
            pass
        elif kind == "draft":
            self.define(approved=False)
            file = self.directory / "future.json"
            put_json(file, {"model_schema": 1, "id": "FUT-001", "source": {"location": "docs/budget.md", "locator": "accepted estimate"},
                            "finding": "Need for a label normalizer", "impact": "Candidate improvement, not approved implementation", "questions": ["Approve the concrete change intent?"]})
            self.call("fut", "capture", "--file", file)
            self.call("fut", "decide", "FUT-001", "--outcome", "promoted", "--actor", "Synthetic fixture owner", "--reason", "Discovery routed to an existing draft", "--target", "CHG-001")
        elif kind == "manual_observation":
            self.define(target=manual_contract())
            self.assign()
            self.call("change", "start", "CHG-001", "--actor", "Fixture maintainer", "--component", "engine")
            run = self.run(expected=1)
            assert run["status"] == "pass"
            self.facts["missing_manual_ac"] = "AC-002"
        else:
            _, original = self.define()
            self.assign()
            for name in self.names:
                self.integrate(component=name)
            if kind == "self_review":
                self.define("CHG-002", base=original, kind="fix")
                self.assign("CHG-002", version="v1.1.0")
                self.call("review", "policy", "--change", "CHG-002", "--enabled", "true", "--actor", "Synthetic fixture owner", "--reason", "Require a separate reviewing context")
            elif kind == "partial_revision":
                target = contract(self.names, prefix="label:", normal_ac="AC-003")
                self.write_product(prefix="label:")
                (self.root / ".roclec/project.toml").write_text(self.profile(("AC-002", "AC-003")))
                self.define("CHG-002", target=target, base=original)
                self.assign("CHG-002", version="v1.1.0")
                self.integrate("CHG-002", component="engine")
                path = self.root / ".roclec/changes/CHG-002"
                record = json.loads((path / "change.json").read_text())
                body = (path / "proposal.md").read_text() + "\nPending viewer clarification: preserve the same approved behavior; keep the integrated engine participant historical.\n"
                (path / "proposal.md").write_text(body)
                record["semantic"]["files"]["proposal.md"] = sha(body.encode())
                record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
                put_json(path / "change.json", record)
                self.facts["pending_intent"] = record["proposal_digest"]
            elif kind == "combined_release":
                self.publish()
                previous = original
                for number, prefix in ((2, "label:"), (3, "label=")):
                    normal_ac = f"AC-{number+1:03}"
                    target = contract(self.names, prefix=prefix, normal_ac=normal_ac)
                    self.write_product(prefix=prefix)
                    (self.root / ".roclec/project.toml").write_text(self.profile(("AC-002", normal_ac)))
                    self.define(f"CHG-{number:03}", target=target, base=previous)
                    self.assign(version="v1.1.0", members=[f"CHG-{n:03}" for n in range(2, number + 1)])
                    self.integrate(f"CHG-{number:03}")
                    previous = target
                self.facts["final_contract"] = previous["revision"]
            elif kind == "local_tag_only":
                self.publish(remote=False)
        self.call("check")
        for name in self.names:
            self.call("foundation", "check", "--component", name)
        if kind == "draft":
            result = self.call("check", "--change", "CHG-001", "--component", "engine", "--gate", "implement", expected=1)
            assert result["issues"][0]["code"] == "APPROVAL_STALE"
        if kind == "partial_revision":
            state = self.call("inspect", "--change", "CHG-002")["data"]
            assert state["status"] == "partially-integrated" and not state["approval_current"]
            self.facts["original_engine_integration"] = state["integrations"]["engine"]
        if kind in {"weak_tests", "self_review"}:
            probe = self.execute([self.python, "-B", "-c", "from src.labels import normalize; print(repr(normalize('   ')))"])
            assert probe.stdout.strip() == "''"
            self.facts["intentional_counterexample"] = "whitespace returns empty instead of raising ValueError"
        if kind == "local_tag_only":
            self.git("show-ref", "--verify", "--quiet", "refs/tags/v1.0.0", cwd=Path(self.facts["remote"]), expected=1)
            assert not (self.root / ".roclec/releases/engine/v1.0.0/publication.json").exists()
        self.commit()
        put_json(self.directory / "baseline.json", {"files": tree(self.root), "head": self.git("rev-parse", "HEAD"), "facts": self.facts})
        (self.directory / "request.md").write_text(self.case["request"] + "\n")
        (self.directory / "result").mkdir()
        (self.directory / "subject-instructions.md").write_text(
            subject_instructions(self.case, self.root, self.directory / "result"))
        return {"id": self.case["id"], "partition": self.case["partition"], "fixture_ready": True,
                "consumer": str(self.root), "request_sha256": sha((self.directory / "request.md").read_bytes()),
                "baseline_sha256": sha((self.directory / "baseline.json").read_bytes()), "setup_commands": len(self.events),
                "subject_executed": False, "semantic_outcome": "not-run"}


def prepare(wheel, destination, *, case_ids=None):
    wheel, destination = Path(wheel).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError("Refusing to overwrite an existing campaign directory")
    if not wheel.is_file():
        raise ValueError("An existing evaluated wheel is required")
    selected = [c for c in catalog() if case_ids is None or c["id"] in case_ids]
    if not selected or (case_ids and set(case_ids) != {c["id"] for c in selected}):
        raise ValueError("Select existing case IDs")
    destination.mkdir(parents=True)
    artifact = destination / "artifact" / wheel.name
    artifact.parent.mkdir()
    shutil.copy2(wheel, artifact)
    environment = destination / "venv"
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    setup = []
    for command in ([sys.executable, "-m", "venv", str(environment)],
                    [str(environment / "bin/python"), "-m", "pip", "install", "--no-index", "--no-deps", str(artifact)]):
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
        setup.append({"argv": command, "exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        put_json(destination / "environment-setup.json", setup)
        if result.returncode:
            raise RuntimeError("Wheel environment setup failed; see environment-setup.json")
    capture = destination / "capture_native.py"
    shutil.copy2(Path(__file__).with_name("semantic_record.py"), capture)
    report = {"schema": 1, "created_at": datetime.now(timezone.utc).isoformat(), "status": "preparing",
              "wheel": artifact.name, "wheel_sha256": sha(artifact.read_bytes()), "catalog_sha256": sha(CATALOG.read_bytes()),
              "preparation_source_sha256": {p.name: sha(p.read_bytes()) for p in (Path(__file__), Path(__file__).with_name("semantic_record.py"))},
              "subject_agent_executions": 0, "reviewer_agent_executions": 0, "execution_authorized": False,
              "semantic_evaluation_performed": False, "cases": [], "failure": None}
    try:
        for case in selected:
            fixture = Fixture(destination / case["id"], environment / "bin/roclec", environment / "bin/python", case, capture)
            report["cases"].append(fixture.build())
            put_json(destination / "preparation.json", report)
        report["status"] = "prepared-not-evaluated"
    except Exception as exc:
        report["status"], report["failure"] = "preparation-failed", str(exc)
        raise
    finally:
        put_json(destination / "preparation.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--case", action="append", dest="cases")
    args = parser.parse_args()
    report = prepare(args.wheel, args.out, case_ids=args.cases)
    print(f"{len(report['cases'])} fixtures ready; semantic subjects/reviewers executed: 0; report: {args.out.resolve() / 'preparation.json'}")


if __name__ == "__main__":
    main()
