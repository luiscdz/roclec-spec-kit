"""Pinned third-party agent skills owned by each consumer repository."""

from __future__ import annotations

from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory

from .model import encoded
from .store import Store


class SkillLockError(ValueError):
    def __init__(self, message, code="SKILL_LOCK_ERROR"):
        super().__init__(message)
        self.code = code


SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
INSTALLER = "skills@1.7.6"

# Version-1 computedHash uses Node's localeCompare order and path/content pairs.
_LOCK_V1_HASH = r"""
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const root = process.argv[1];
const paths = [];
function collect(dir) {
  for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
    const name = path.join(dir, entry.name);
    if (entry.isDirectory() && ['.git', 'node_modules'].includes(entry.name)) {
      throw new Error('unexpected excluded directory in installed skill');
    }
    if (entry.isDirectory()) collect(name);
    else if (entry.isFile()) paths.push(path.relative(root, name).split(path.sep).join('/'));
    else throw new Error('unsupported installed skill entry');
  }
}
collect(root);
const hash = crypto.createHash('sha256');
for (const name of paths.sort((a, b) => a.localeCompare(b))) {
  hash.update(name);
  hash.update(fs.readFileSync(path.join(root, name)));
}
process.stdout.write(hash.digest('hex'));
"""


def installed_hash(path):
    result = subprocess.run(["node", "-e", _LOCK_V1_HASH, str(path)], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise SkillLockError(f"Cannot verify installed skill folder {path.name}", "SKILL_HASH_MISMATCH")
    return result.stdout.strip()


def restore_verified_external_skills(root: Path) -> list[str]:
    """Verify a staged v1 restore before copying its checked bytes to agent paths."""
    store = Store(root)
    lock_path = store.path("skills-lock.json")
    data = read_lock(root)
    names = sorted(data["skills"])
    if not names:
        return []
    if not shutil.which("npx") or not shutil.which("node"):
        raise SkillLockError("Node.js and npx are required to restore skills-lock.json")
    report = {"installer": INSTALLER, "status": "rejected", "skills": {}}
    try:
        with TemporaryDirectory(prefix="roclec-skills-") as directory:
            stage = Path(directory)
            (stage / "skills-lock.json").write_bytes(lock_path.read_bytes())
            result = subprocess.run(["npx", "-y", INSTALLER, "experimental_install", "--frozen-lockfile"],
                                    cwd=stage, capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise SkillLockError(f"Pinned skill installer failed (exit {result.returncode})")
            writes = {}
            for name in names:
                expected = data["skills"][name]["computedHash"]
                source = stage / ".agents/skills" / name
                if not (source / "SKILL.md").is_file() or not source.resolve().is_relative_to(stage):
                    raise SkillLockError(f"Pinned installer did not produce {name}")
                actual = installed_hash(source)
                report["skills"][name] = {"computedHash": actual, "expected": expected, "verified": actual == expected}
                if actual != expected:
                    raise SkillLockError(f"Installed content of {name} differs from skills-lock.json", "SKILL_HASH_MISMATCH")
                for host in (".agents", ".claude"):
                    relative = f"{host}/skills/{name}"
                    destination = store.path(relative)
                    if destination.exists():
                        if not destination.is_dir() or installed_hash(destination) != expected:
                            raise SkillLockError(f"Existing {name} in {host} differs from the verified skill")
                        continue
                    for leaf in source.rglob("*"):
                        if leaf.is_file():
                            writes[f"{relative}/{leaf.relative_to(source).as_posix()}"] = leaf.read_bytes()
            if writes:
                store.apply("skills-install", {"external": names, "installer": INSTALLER}, writes, store.token())
            report["status"] = "verified"
            return names
    except SkillLockError as exc:
        report["error"] = exc.code
        raise
    finally:
        store._atomic(".roclec/runtime/skills/restore.json", encoded(report))


def read_lock(root: Path) -> dict:
    path = root / "skills-lock.json"
    if not path.is_file():
        raise SkillLockError(f"{path} is missing; add a skills-lock.json before restoring external skills")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillLockError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("skills"), dict):
        raise SkillLockError(f"{path} must use skills-lock version 1")
    for name, entry in data["skills"].items():
        if not SKILL_NAME_RE.fullmatch(name) or not isinstance(entry, dict):
            raise SkillLockError(f"{path}: invalid skill {name!r}")
        if not all(isinstance(entry.get(key), str) and entry[key] for key in ("source", "sourceType", "skillPath", "computedHash")):
            raise SkillLockError(f"{path}: {name} needs source, sourceType, skillPath and computedHash")
    return data


def ensure_design_lock(root: Path) -> list[str]:
    """Add the pinned design profile without replacing consumer-chosen versions."""
    path = root / "skills-lock.json"
    default = json.loads(files("roclec_spec_kit").joinpath("assets/profiles/design-skills-lock.json").read_text(encoding="utf-8"))
    if path.exists():
        data = read_lock(root)
    else:
        data = {"version": 1, "skills": {}}
    added = []
    for name, entry in default["skills"].items():
        if name not in data["skills"]:
            data["skills"][name] = entry
            added.append(name)
    if added:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return added


def restore_external_skills(root: Path, *, quiet=False) -> list[str]:
    """Install exactly the dependencies declared in this repository's lock."""
    data = read_lock(root)
    names = list(data["skills"])
    if not names:
        return []
    if shutil.which("npx") is None:
        raise SkillLockError("npx is required to restore skills-lock.json (install Node.js first)")
    output = {"capture_output": True, "text": True} if quiet else {}
    result = subprocess.run(["npx", "-y", "skills", "experimental_install"], cwd=root, check=False, **output)
    if quiet:
        import sys
        sys.stderr.write(result.stdout or "")
        sys.stderr.write(result.stderr or "")
    if result.returncode:
        raise SkillLockError(f"skills installer failed in {root} (exit {result.returncode})")
    missing = [name for name in names if not any((root / host / "skills" / name / "SKILL.md").is_file() for host in (".agents", ".claude"))]
    if missing:
        raise SkillLockError(f"skills installer completed but these locked skills are missing in {root}: {', '.join(missing)}")
    for name in names:
        agent = root / ".agents/skills" / name
        claude = root / ".claude/skills" / name
        source, target = (agent, claude) if (agent / "SKILL.md").is_file() else (claude, agent)
        if target.is_symlink() and target.resolve() == source.resolve():
            continue
        if (target / "SKILL.md").is_file():
            continue
        if target.exists() or target.is_symlink():
            raise SkillLockError(f"Will not overwrite a conflicting skill path: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.symlink_to(os.path.relpath(source, target.parent), target_is_directory=True)
        except OSError:
            shutil.copytree(source, target)
    return names
