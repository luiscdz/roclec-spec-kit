"""Install native instructions with preserved consumer templates and guarded writes."""
from __future__ import annotations

from dataclasses import replace
from importlib.resources import files
import json
import os
from pathlib import Path
import shlex
import shutil
import tempfile

from . import __version__
from .model import ModelError, encoded, need, sha
from .store import Store

MARKER = "<!-- managed by roclec-spec-kit -->"
START, END = "<!-- roclec-spec-kit:begin -->", "<!-- roclec-spec-kit:end -->"


def install(kernel, *, into=None, restore=False, adapter=False):
    profile = kernel.profile
    destination = profile.root
    if into:
        destination = profile.repo(into) if into in profile.components else Path(into).resolve()
        need(destination in {profile.repo(c) for c in profile.components}, "INVALID_REFERENCE", "Install only into an explicitly configured component repo")
    store = Store(destination)
    store.healthy()
    token = store.token()
    if restore:
        from .external_skills import read_lock
        read_lock(destination)
    assets = files("roclec_spec_kit").joinpath("assets")
    writes = {}

    def owned(relative, content):
        path = store.path(relative)
        need(not path.exists() or MARKER.encode() in path.read_bytes() or b"managed by roclec-spec-kit" in path.read_bytes(),
             "UNMANAGED_FILE", "Installation would overwrite consumer-owned instructions", path=relative)
        writes[relative] = content

    for skill in assets.joinpath("skills").iterdir():
        if not skill.is_dir():
            continue
        def visit(source, prefix):
            for item in source.iterdir():
                if item.is_dir():
                    visit(item, prefix + "/" + item.name)
                else:
                    for host in (".agents", ".claude"):
                        owned(f"{host}/skills/{prefix}/{item.name}", item.read_bytes())
        visit(skill, skill.name)
    block = START + "\n" + assets.joinpath("project/agent-instructions.md").read_text().strip() + "\n" + END
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = store.path(name)
        body = path.read_text() if path.exists() else ""
        need(body.count(START) == body.count(END) and body.count(START) <= 1, "UNMANAGED_FILE", "Malformed managed instruction block", path=name)
        if START in body:
            before, rest = body.split(START, 1)
            _, after = rest.split(END, 1)
            content = before + block + after
        else:
            content = body + ("\n\n" if body else "") + block + "\n"
        writes[name] = content.encode()
    owned(".roclec/workflow.md", assets.joinpath("project/workflow.md").read_bytes())
    owned(".roclec/model.md", assets.joinpath("project/model.md").read_bytes())
    relative = os.path.relpath(profile.root, destination)
    runner = ('#!/bin/sh\n# managed by roclec-spec-kit\nset -eu\n'
              'repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
              f'project_relative={shlex.quote(relative)}\n'
              'project_root=$(CDPATH= cd -- "$repo_root/$project_relative" && pwd)\n'
              'if [ -x "$project_root/.venv/bin/roclec" ]; then cli="$project_root/.venv/bin/roclec"; '
              'elif [ -x "$repo_root/.venv/bin/roclec" ]; then cli="$repo_root/.venv/bin/roclec"; '
              'else cli=$(command -v roclec) || { echo "Install roclec-spec-kit in the project .venv" >&2; exit 127; }; fi\n'
              'exec "$cli" --project "$project_root" "$@"\n')
    owned(".roclec/run", runner.encode())
    if destination != profile.root:
        link = store.path(".roclec/link.toml")
        content = f"schema = 1\nproject_root = {json.dumps(relative)}\n".encode()
        need(not link.exists() or link.read_bytes() == content, "UNMANAGED_FILE", "Linked repo already belongs to another project")
        writes[".roclec/link.toml"] = content
    else:
        for template in assets.joinpath("templates").iterdir():
            target = f".roclec/templates/{template.name}"
            if not store.path(target).exists():
                writes[target] = template.read_bytes()
        if not store.path(".roclec/constitution.md").exists() and not store.path(".specify/memory/constitution.md").exists():
            writes[".roclec/constitution.md"] = assets.joinpath("templates/constitution-template.md").read_bytes()
    for notice in assets.joinpath("notices").iterdir():
        target = f".roclec/notices/{notice.name}"
        path = store.path(target)
        need(not path.exists() or path.read_bytes() == notice.read_bytes(), "UNMANAGED_FILE", "Resolve modified attribution before refreshing", path=target)
        writes[target] = notice.read_bytes()
    ignore = store.path(".gitignore")
    ignored = ignore.read_bytes() if ignore.exists() else b""
    if b".roclec/runtime/" not in ignored.splitlines():
        writes[".gitignore"] = ignored + (b"\n" if ignored and not ignored.endswith(b"\n") else b"") + b".roclec/runtime/\n"
    if adapter:
        need(destination == profile.root, "INVALID_INPUT", "Install aliases in the project root", exit_code=2)
        need(store.path(".specify").is_dir(), "INVALID_REFERENCE", "Initialize the desired spec-kit integration before installing Roclec aliases")
        from .adapter import install_speckit
        # Project-file effects remain in staging until the complete diff
        # has passed validation and can be journaled by the native store.
        with tempfile.TemporaryDirectory(prefix="roclec-native-adapter-") as directory:
            stage = Path(directory).resolve()
            initial = {}
            for name in (".specify", ".agents", ".claude", ".codex", ".roclec/templates"):
                source = store.path(name)
                if source.exists():
                    # Unrelated third-party skill symlinks are neither read nor
                    # copied. Every actual write target is still path-validated.
                    shutil.copytree(source, stage / name,
                                    ignore=lambda folder, names: [n for n in names if (Path(folder) / n).is_symlink()])
            for p in stage.rglob("*"):
                if p.is_file(): initial[p.relative_to(stage).as_posix()] = p.read_bytes()
            for path, content in writes.items():
                target = stage / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            install_speckit(replace(profile, root=stage))
            for p in stage.rglob("*"):
                if p.is_file():
                    name = p.relative_to(stage).as_posix()
                    content = p.read_bytes().replace(str(stage).encode(), str(destination).encode())
                    if content != initial.get(name):
                        writes[name] = content
    manifest = {"model_schema": 2, "version": __version__, "adapter": adapter,
                "files": {p: sha(b) for p, b in writes.items()}}
    writes[".roclec/installation.json"] = encoded(manifest)
    receipt = store.apply("skills-install", {"version": __version__, "adapter": adapter}, writes, token)
    # Executability is installed as part of the journal's mode metadata.
    if restore:
        from .external_skills import SkillLockError, restore_verified_external_skills
        try:
            restored = restore_verified_external_skills(destination)
        except SkillLockError as exc:
            error = ModelError(exc.code, str(exc), remediation="Review skills-lock.json and retry skills --restore.")
            error.operation_id, error.partial = receipt["operation_id"], True
            raise error from exc
    else:
        restored = []
    return {"installed": str(destination), "version": __version__, "adapter": adapter, "external_skills": restored, "receipt": receipt}
