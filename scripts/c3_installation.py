"""Native installation/refresh scenarios, optionally through real spec-kit CLIs."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tomllib

try:
    from .c1_scenarios import file_hash, put_json, tree
    from .c2_scenarios import setup, git
except ImportError:
    from c1_scenarios import file_hash, put_json, tree
    from c2_scenarios import setup, git


BINDING_ROLES = ("implementer", "reviewer", "specifier")


def bindings(root):
    """Generated role definitions found in a repo's host agent folders."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for folder in (".claude/agents", ".codex/agents")
            if (root / folder).is_dir() for p in sorted((root / folder).iterdir()) if p.is_file()}


def binding_model(root, role, host):
    """Pinned model of one binding, or None when the key is absent (inherit the session)."""
    if host == "codex":
        return tomllib.loads((root / f".codex/agents/roclec-{role}.toml").read_text(encoding="utf-8")).get("model")
    head = (root / f".claude/agents/roclec-{role}.md").read_text(encoding="utf-8").split("\n---\n", 1)[0]
    values = [line.split(": ", 1)[1] for line in head.splitlines() if line.startswith("model: ")]
    return json.loads(values[0]) if values else None


def binding_scenarios(root, call, check):
    """Subagent role bindings are managed files on both hosts (M-28)."""
    expected = {f".claude/agents/roclec-{r}.md" for r in BINDING_ROLES} | {f".codex/agents/roclec-{r}.toml" for r in BINDING_ROLES}
    current = bindings(root)
    check("I-034 subagent bindings installed on both hosts, no coordinator", set(current) == expected, sorted(current))
    codex = {r: tomllib.loads((root / f".codex/agents/roclec-{r}.toml").read_text(encoding="utf-8")) for r in BINDING_ROLES}
    check("I-034 codex bindings parse with name, sandbox and instructions", all(
        data["name"] == f"roclec-{r}" and data["sandbox_mode"] in ("read-only", "workspace-write")
        and "<!-- managed by roclec-spec-kit -->" in data["developer_instructions"] for r, data in codex.items()), "")
    check("I-034 claude bindings carry name, tools and the contract", all(
        (root / f".claude/agents/roclec-{r}.md").read_text(encoding="utf-8").startswith(f"---\nname: roclec-{r}\n")
        and "\ntools: Read, Grep, Glob" in (root / f".claude/agents/roclec-{r}.md").read_text(encoding="utf-8") for r in BINDING_ROLES), "")
    check("I-034 no model key without [agents]", all(binding_model(root, r, h) is None for r in BINDING_ROLES for h in ("claude", "codex")))
    own = {".claude/agents/my-role.md": b"---\nname: my-role\n---\nConsumer role\n", ".codex/agents/my-role.toml": b'name = "my-role"\n'}
    for relative, content in own.items():
        (root / relative).write_bytes(content)
    config = root / ".roclec/project.toml"
    profile = config.read_text(encoding="utf-8")
    config.write_text(profile + '\n[agents.implementer]\nclaude = "m-a"\ncodex = "m-b"\n', encoding="utf-8")
    call("I-034 refresh with pinned implementer models", "skills")
    pinned = bindings(root)
    check("I-034 pinned models reach only the implementer", binding_model(root, "implementer", "claude") == "m-a"
          and binding_model(root, "implementer", "codex") == "m-b"
          and all(binding_model(root, r, h) is None for r in ("reviewer", "specifier") for h in ("claude", "codex")))
    check("I-034 pinning rewrites only the implementer bindings", {p for p in current if pinned[p] != current[p]}
          == {".claude/agents/roclec-implementer.md", ".codex/agents/roclec-implementer.toml"})
    config.write_text(profile + '\n[agents.implementer]\nclaude = "m-c"\ncodex = "m-b"\n', encoding="utf-8")
    changed = call("I-034 refresh after changing one host model", "skills")
    after = bindings(root)
    check("I-034 model change rewrites only that host binding", {p for p in after if after[p] != pinned.get(p)}
          == {".claude/agents/roclec-implementer.md"} and binding_model(root, "implementer", "claude") == "m-c"
          and changed["receipt"]["writes"][".claude/agents/roclec-implementer.md"] == file_hash(after[".claude/agents/roclec-implementer.md"]))
    check("I-034 consumer role files untouched", all((root / p).read_bytes() == b for p, b in own.items()))
    reviewer = root / ".codex/agents/roclec-reviewer.toml"
    original = reviewer.read_bytes()
    reviewer.write_bytes(original + b"# consumer note\n")
    call("I-034 edited binding rejects whole refresh", "skills", expect=1, issue="MANAGED_FILE_EDITED")
    reviewer.write_bytes(b'name = "roclec-reviewer"\n')
    call("I-034 unmarked binding is consumer-owned", "skills", expect=1, issue="UNMANAGED_FILE")
    reviewer.write_bytes(original)
    manifest_path = root / ".roclec/installation.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    retired = {".claude/agents/roclec-retired.md": b"<!-- managed by roclec-spec-kit -->\nretired role\n",
               ".codex/agents/roclec-retired.toml": b"# managed by roclec-spec-kit\nname = \"roclec-retired\"\n"}
    for relative, content in retired.items():
        (root / relative).write_bytes(content)
        manifest["files"][relative] = file_hash(content)
        manifest["managed"].append(relative)
    put_json(manifest_path, manifest)
    (root / ".claude/agents/roclec-retired.md").write_bytes(retired[".claude/agents/roclec-retired.md"] + b"edited\n")
    call("I-034 edited retired binding rejects whole refresh", "skills", expect=1, issue="MANAGED_FILE_EDITED")
    (root / ".claude/agents/roclec-retired.md").write_bytes(retired[".claude/agents/roclec-retired.md"])
    pruned = call("I-034 refresh prunes a retired role", "skills")
    check("I-034 retired role pruned on both hosts", not any((root / p).exists() for p in retired)
          and all(pruned["receipt"]["writes"][p] is None for p in retired)
          and all((root / p).read_bytes() == b for p, b in own.items()))
    config.write_text(profile, encoding="utf-8")
    call("I-034 unpinning restores inherited models", "skills")
    check("I-034 unpinned bindings equal the first install", {p: b for p, b in bindings(root).items() if p not in own} == current)


def scenarios(workspace, invoke, check, *, compatibility=False):
    root, _ = setup(workspace / "c3-installation", invoke, names=("engine",))
    prefix = ["--project", str(root), "--json"]

    def call(label, *args, expect=0, issue=None):
        before = tree(root)
        result = invoke([*prefix, *map(str, args)])
        check(label, result.returncode == expect, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        if issue:
            check(label + ": issue", issue in [i["code"] for i in data["issues"]], result.stdout)
        if expect in (1, 2, 3):
            check(label + ": rejection preserves consumer", tree(root) == before, result.stdout)
        return data.get("data")

    owned = b"# Consumer instructions\n\nPreserve these exact bytes.\n"
    (root / "AGENTS.md").write_bytes(owned)
    (root / "CLAUDE.md").write_bytes(owned)
    first = call("I-033 native skills install without spec-kit", "skills")
    check("I-033 native installation is journaled", first["receipt"]["kind"] == "skills-install")
    check("I-033 launcher executable", (root / ".roclec/run").stat().st_mode & 0o111)
    check("I-033 native schema guidance installed", (root / ".roclec/model.md").is_file())
    for host in (".agents", ".claude"):
        installed = list((root / host / "skills").glob("roclec-*/SKILL.md"))
        check("I-033 " + host + " native stages present", len(installed) == 17)
        check("I-033 " + host + " uses profile-3 operations", "integrate prepare" in (root / host / "skills/roclec-converge/SKILL.md").read_text()
              and "run verify --release" in (root / host / "skills/roclec-release/SKILL.md").read_text())
        check("I-033 " + host + " exact FUT selector", "inspect --fut FUT-001" in (root / host / "skills/roclec-coordinator/SKILL.md").read_text())
        check("I-033 " + host + " digest preflight", "same digest" in (root / host / "skills/roclec-implement/SKILL.md").read_text())
        check("I-033 " + host + " stale evidence rejected", "older participant revision" in (root / host / "skills/roclec-converge/SKILL.md").read_text())
        check("I-033 " + host + " replans current intent", "current approved intent revisions" in (root / host / "skills/roclec-release/SKILL.md").read_text())
        check("I-033 " + host + " safe bundle reference", (root / host / "skills/roclec-specify/references/native-bundle-layout.md").is_file())
    check("I-033 hosts receive identical native coordinator", (root / ".agents/skills/roclec-coordinator/SKILL.md").read_bytes()
          == (root / ".claude/skills/roclec-coordinator/SKILL.md").read_bytes())
    check("I-033 root instruction ownership preserved", (root / "AGENTS.md").read_bytes().startswith(owned)
          and (root / "CLAUDE.md").read_bytes().startswith(owned))
    template = root / ".roclec/templates/plan-template.md"
    constitution = root / ".roclec/constitution.md"
    template.write_bytes(b"# Consumer plan\n")
    constitution.write_bytes(b"# Consumer principles\n")
    call("I-033 refresh managed native stages", "skills")
    check("I-033 refresh preserves consumer templates/principles", template.read_bytes() == b"# Consumer plan\n" and constitution.read_bytes() == b"# Consumer principles\n")
    check("I-033 refresh has one instruction block", (root / "AGENTS.md").read_text().count("<!-- roclec-spec-kit:begin -->") == 1)
    skill = root / ".agents/skills/roclec-plan/SKILL.md"
    original = skill.read_bytes()
    skill.write_bytes(b"# Consumer-owned skill\n")
    call("I-033 unmanaged stage rejects whole refresh", "skills", expect=1, issue="UNMANAGED_FILE")
    skill.write_bytes(original + b"\nConsumer addition that keeps the managed marker.\n")
    call("I-033 edited managed stage rejects whole refresh", "skills", expect=1, issue="MANAGED_FILE_EDITED")
    skill.unlink()
    call("I-033 deleting an edited stage accepts the refreshed version", "skills")
    check("I-033 refreshed stage restored", skill.read_bytes() == original)
    # A stage an earlier version recorded as managed and the assets retired.
    manifest_path = root / ".roclec/installation.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    retired_bytes = b"<!-- managed by roclec-spec-kit -->\n# Retired stage\n"
    retired = [root / host / "skills/roclec-retired/SKILL.md" for host in (".agents", ".claude")]
    for path in retired:
        path.parent.mkdir(parents=True)
        path.write_bytes(retired_bytes)
        relative = path.relative_to(root).as_posix()
        manifest["files"][relative] = file_hash(retired_bytes)
        manifest["managed"].append(relative)
    put_json(manifest_path, manifest)
    retired[0].write_bytes(retired_bytes + b"Consumer note\n")
    call("I-033 edited retired stage rejects whole refresh", "skills", expect=1, issue="MANAGED_FILE_EDITED")
    retired[0].write_bytes(retired_bytes)
    pruned = call("I-033 refresh prunes retired managed stages", "skills")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    check("I-033 retired stages removed on both hosts", not any(path.parent.exists() for path in retired)
          and not any(path.relative_to(root).as_posix() in manifest["files"] for path in retired)
          and all(pruned["receipt"]["writes"][path.relative_to(root).as_posix()] is None for path in retired))
    report = root / ".agents/skills/roclec-reviewer/references/report-template.md"
    check("I-033 review input has candidate/release scope", '"candidate_digest"' in report.read_text() and '"release"' in report.read_text())
    check("I-033 MIT attribution installed", "MIT" in (root / ".roclec/notices/spec-kit-LICENSE.txt").read_text())
    # Consumer-pinned third-party skill links must not become native authorities
    # or be dereferenced merely to refresh Roclec's own instructions.
    third_party = root / ".agents/skills/consumer-helper"
    third_party.mkdir()
    (third_party / "SKILL.md").write_text("# Consumer helper\n")
    (root / ".claude/skills/consumer-helper").symlink_to("../../.agents/skills/consumer-helper", target_is_directory=True)
    call("I-033 refresh preserves unrelated skill links", "skills")
    binding_scenarios(root, call, check)
    if compatibility:
        native_bindings = bindings(root)
        for integration in ("codex", "claude"):
            result = subprocess.run(["specify", "init", "--here", "--integration", integration, "--ignore-agent-tools", "--force"],
                                    cwd=root, capture_output=True, text=True, timeout=60)
            check("I-033 initialize " + integration + " integration", result.returncode == 0, result.stdout + result.stderr)
            call("I-033 install native " + integration + " aliases", "speckit")
            canonical = (root / ".agents/skills/roclec-plan/SKILL.md").read_text().split("\n---\n", 1)[1].lstrip()
            alias = root / ".specify/presets/roclec/commands/speckit.plan.md"
            check("I-033 " + integration + " alias is canonical native prompt", alias.read_text().endswith(canonical))
            extension = json.loads((root / ".specify/extensions/roclec/extension.yml").read_text())
            preset = json.loads((root / ".specify/presets/roclec/preset.yml").read_text())
            check("I-033 versions align", extension["extension"]["version"] == first["version"] == preset["preset"]["version"])
            reviewer = (root / ".specify/extensions/roclec/commands/speckit.roclec.reviewer.md").read_text()
            check("I-033 " + integration + " reviewer reference resolves", str(report) in reviewer)
            specify = (root / ".specify/presets/roclec/commands/speckit.specify.md").read_text()
            bundle_reference = root / ".agents/skills/roclec-specify/references/native-bundle-layout.md"
            check("I-033 " + integration + " specify reference resolves", str(bundle_reference) in specify and bundle_reference.is_file())
            call("I-033 refresh " + integration + " aliases", "speckit")
            check("I-033 adapter refresh preserves consumer template", template.read_bytes() == b"# Consumer plan\n")
            check("I-033 adapter preserves third-party skill link", (root / ".claude/skills/consumer-helper").is_symlink())
        check("I-034 aliases keep role bindings byte-identical", bindings(root) == native_bindings, sorted(bindings(root)))
        aliases = {p: v for p, v in tree(root).items() if p.startswith((".specify/", ".codex/", ".claude/commands/", ".claude/agents/")) or "/skills/speckit-" in p}
        call("I-033 native refresh after aliases", "skills")
        call("I-033 repeated native refresh after aliases", "skills")
        current = tree(root)
        check("I-033 native refresh neither prunes nor flags alias files", bool(aliases) and {p: current.get(p) for p in aliases} == aliases)
    # A linked repository receives its own guarded install without a second
    # profile or a guessed technology stack.
    code = root.parent / "linked code"
    code.mkdir()
    config = root / ".roclec/project.toml"
    config.write_text(config.read_text().replace('repo = "."', 'repo = "../linked code"'))
    call("I-033 install into configured linked component", "skills", "--into", "engine")
    check("I-034 linked component receives the same role bindings",
          {p: b for p, b in bindings(code).items()} == {p: b for p, b in bindings(root).items() if "/roclec-" in p})
    check("I-033 linked install points to original authority", 'project_root = "../code with spaces"' in (code / ".roclec/link.toml").read_text())
    call("I-033 installed native consumer validates", "check")


_STAGED_SKILL_INSTALLER = '''
from pathlib import Path
import subprocess, sys
from unittest.mock import patch
from roclec_spec_kit.cli import main
from roclec_spec_kit import external_skills
original = subprocess.run
which = external_skills.shutil.which
def invoke(argv, *args, **kwargs):
    if argv[0] == "npx":
        assert argv == ["npx", "-y", "skills@1.7.6", "experimental_install", "--frozen-lockfile"]
        folder = Path(kwargs["cwd"]) / ".agents/skills/synthetic"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_bytes(b"# Verified fixture\\n")
        return subprocess.CompletedProcess(argv, 0, "", "")
    return original(argv, *args, **kwargs)
with patch.object(subprocess, "run", invoke), patch.object(external_skills.shutil, "which",
     side_effect=lambda cmd, *a, **kw: "/synthetic/npx" if cmd == "npx" else which(cmd, *a, **kw)):
    raise SystemExit(main(sys.argv[1:]))
'''


def verified_restore_scenarios(workspace, invoke, inject, check):
    import shutil
    if shutil.which("node") is None:
        return
    root, _ = setup(workspace / "verified-restore", invoke, names=("engine",))
    lock = {"version": 1, "skills": {"synthetic": {"source": "example/skills", "sourceType": "github",
            "skillPath": "synthetic/SKILL.md", "computedHash": "0" * 64}}}
    lock_path = root / "skills-lock.json"
    put_json(lock_path, lock)
    args = ["--project", str(root), "--json", "skills", "--restore"]
    result = inject(_STAGED_SKILL_INSTALLER, args)
    payload = json.loads(result.stdout)
    check("F3 mismatched external skill rejected with a specific code",
          result.returncode == 1 and payload["issues"][0]["code"] == "SKILL_HASH_MISMATCH", result.stdout)
    report = root / ".roclec/runtime/skills/restore.json"
    check("F3 mismatch is recorded without adopting it",
          json.loads(report.read_bytes())["status"] == "rejected" and not (root / ".agents/skills/synthetic").exists(), "")
    lock["skills"]["synthetic"]["computedHash"] = file_hash(b"SKILL.md# Verified fixture\n")
    put_json(lock_path, lock)
    result = inject(_STAGED_SKILL_INSTALLER, args)
    check("F3 matching external skill restored with pinned installer",
          result.returncode == 0 and json.loads(report.read_bytes())["skills"]["synthetic"]["verified"]
          and all((root / host / "skills/synthetic/SKILL.md").is_file() for host in (".agents", ".claude")), result.stdout)
