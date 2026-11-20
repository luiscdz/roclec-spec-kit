"""Pinned third-party agent skills owned by each consumer repository."""

from __future__ import annotations

from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


class SkillLockError(ValueError):
    pass


SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


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
