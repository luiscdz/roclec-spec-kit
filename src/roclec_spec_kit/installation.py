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
import tomllib

from . import __version__
from .agents import bindings, is_binding_path
from .flow import DEFAULT_VIEW, RETRO_PATH
from .model import ModelError, digest, encoded, need, read_json, sha
from .store import Store

MARKER = "<!-- managed by roclec-spec-kit -->"
START, END = "<!-- roclec-spec-kit:begin -->", "<!-- roclec-spec-kit:end -->"
MANIFEST = ".roclec/installation.json"
NATIVE_FILES = (".roclec/workflow.md", ".roclec/model.md", ".roclec/run")
EDITED_REMEDIATION = ("Restore each listed file (for example `git checkout -- PATH`) or delete it to accept the refreshed "
                      "version, then retry; move consumer content into a consumer-owned file.")


def _native(relative):
    """Paths that only Roclec's own installer writes and may compare by hash or prune.

    Seeded templates/constitution, root instruction blocks, `.gitignore`, links,
    notices and every adapter output (`.specify/`, `speckit-*` skills, commands)
    are deliberately excluded, whatever an installation manifest claims. Role
    bindings match only `roclec-<one lowercase word>` directly in a host's
    `agents/` folder, so hyphenated or other consumer role files never do.
    """
    return relative in NATIVE_FILES or is_binding_path(relative) or any(
        relative.startswith(f"{host}/skills/roclec-") and relative.count("/") >= 3 for host in (".agents", ".claude"))


def _previous(store):
    """Return (recorded native hashes, generation) from the previous manifest.

    Empty hashes mean a first install. Manifests without the optional `managed`
    list (earlier versions) are read through the same native-path rule; a
    missing or invalid manifest falls back to the marker rule and prunes nothing.
    """
    path = store.path(MANIFEST)
    if not path.is_file():
        return {}, None
    try:
        data = read_json(path)
    except ModelError:
        return {}, None
    if not isinstance(data, dict):
        return {}, None
    generation = data.get("generation") if isinstance(data.get("generation"), str) else None
    files = data.get("files")
    managed = data.get("managed", list(files) if isinstance(files, dict) else None)
    if not isinstance(files, dict) or not isinstance(managed, list):
        return {}, generation
    return {p: files[p] for p in managed
            if isinstance(p, str) and _native(p) and isinstance(files.get(p), str)}, generation


def _generation(store, token):
    """Distinguish an effective refresh from every confirmed one.

    A deterministic refresh that restores a deleted or edited file would
    otherwise reuse the operation id of the refresh that first wrote those
    bytes, and the store refuses to replay a receipt whose files diverged.
    Every existing receipt was prepared before it existed, so a digest over
    the current receipt names cannot match any of them.
    """
    receipts = store.path(".roclec/receipts")
    names = sorted(p.name for p in receipts.glob("*.json")) if receipts.is_dir() else []
    return digest({"inputs": token, "receipts": names})


def _flow_view_path(store, writes):
    """The view path the flow declares, read without validation (an invalid flow is reported elsewhere)."""
    raw = writes.get(".roclec/flow.toml")
    if raw is None:
        raw = _current(store, ".roclec/flow.toml") or b""
    try:
        view = tomllib.loads(raw.decode("utf-8")).get("view", DEFAULT_VIEW)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return DEFAULT_VIEW
    return view


def _current(store, relative):
    path = store.path(relative)
    return path.read_bytes() if path.is_file() else None


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
    previous, generation = _previous(store)
    managed, edited = set(), []
    observed = {}  # Bytes each owned or retired path held when it was judged.

    def owned(relative, content):
        path = store.path(relative)
        current = path.read_bytes() if path.exists() else None
        observed[relative] = current
        need(current is None or MARKER.encode("utf-8") in current or b"managed by roclec-spec-kit" in current,
             "UNMANAGED_FILE", "Installation would overwrite consumer-owned instructions", path=relative)
        # A recorded hash proves which bytes Roclec wrote; anything else, unless
        # it already equals the refreshed bytes, is a consumer edit to keep.
        if current is not None and relative in previous and sha(current) not in (previous[relative], sha(content)):
            edited.append(relative)
        writes[relative] = content
        managed.add(relative)

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
    # Subagent role bindings for both hosts, with the project's pinned models.
    for relative, content in bindings(profile).items():
        owned(relative, content)
    block = START + "\n" + assets.joinpath("project/agent-instructions.md").read_text(encoding="utf-8").strip() + "\n" + END
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = store.path(name)
        body = path.read_text(encoding="utf-8") if path.exists() else ""
        need(body.count(START) == body.count(END) and body.count(START) <= 1, "UNMANAGED_FILE", "Malformed managed instruction block", path=name)
        if START in body:
            before, rest = body.split(START, 1)
            _, after = rest.split(END, 1)
            content = before + block + after
        else:
            content = body + ("\n\n" if body else "") + block + "\n"
        writes[name] = content.encode("utf-8")
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
    owned(".roclec/run", runner.encode("utf-8"))
    if destination != profile.root:
        link = store.path(".roclec/link.toml")
        content = f"schema = 1\nproject_root = {json.dumps(relative)}\n".encode("utf-8")
        need(not link.exists() or link.read_bytes() == content, "UNMANAGED_FILE", "Linked repo already belongs to another project")
        writes[".roclec/link.toml"] = content
    else:
        for template in assets.joinpath("templates").iterdir():
            target = f".roclec/templates/{template.name}"
            if not store.path(target).exists():
                writes[target] = template.read_bytes()
        # Consumer-owned like templates: seeded once, never managed, compared or pruned.
        if not store.path(".roclec/flow.toml").exists():
            writes[".roclec/flow.toml"] = assets.joinpath("project/flow.toml").read_bytes()
        # The flow retrospective is project-owned too; skipped if the flow's view occupies its path.
        if not store.path(RETRO_PATH).exists() and _flow_view_path(store, writes) != RETRO_PATH:
            writes[RETRO_PATH] = assets.joinpath("project/flow-retro.md").read_bytes()
            observed[RETRO_PATH] = None  # Outside the store token: recheck it is still absent under the lock.
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
    # Retired native files: delete only bytes Roclec recorded; reject edits.
    retired = []
    for relative in sorted(set(previous) - managed):
        path = store.path(relative)
        if not path.exists():
            continue
        # Read once: the judged bytes are both hashed and rechecked under the lock.
        current = path.read_bytes() if path.is_file() else None
        if current is not None and sha(current) == previous[relative]:
            retired.append(relative)
            observed[relative] = current
        else:
            edited.append(relative)
    need(not edited, "MANAGED_FILE_EDITED", "Refresh would overwrite or delete edited Roclec-managed files",
         path=sorted(edited)[0] if edited else None, actual=sorted(edited), remediation=EDITED_REMEDIATION)
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
                    content = p.read_bytes().replace(str(stage).encode("utf-8"), str(destination).encode("utf-8"))
                    if content != initial.get(name):
                        writes[name] = content
    for relative in retired:
        # Store journals None as a recoverable deletion within this namespace.
        writes.setdefault(relative, None)
    manifest = {"model_schema": 2, "version": __version__, "adapter": adapter,
                "files": {p: sha(b) for p, b in writes.items() if b is not None},
                "managed": sorted(managed)}
    # A refresh that changes nothing keeps the previous generation, so its
    # operation id matches the confirmed one and replays idempotently.
    content = encoded({**manifest, "generation": generation} if generation else manifest)
    if retired or content != _current(store, MANIFEST) or any(_current(store, p) != b for p, b in writes.items()):
        content = encoded({**manifest, "generation": _generation(store, token)})
    writes[MANIFEST] = content
    def unchanged():
        # The store token does not hash `.claude/agents/`; recheck under the
        # lock that no judged file changed before anything is journaled.
        need(all(_current(store, p) == b for p, b in observed.items()), "BASE_CONFLICT",
             "Project inputs changed during validation", exit_code=3)

    receipt = store.apply("skills-install", {"version": __version__, "adapter": adapter}, writes, token, validate=unchanged)
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
