"""Knowledge skills as foundation references (TK.1): canonical location and source fingerprints.

A knowledge skill is a consumer-owned directory registered as a reference with role ``skill``.
Its fingerprint is a manifest over every regular file in that directory, recursively and
including hidden files, so editing, adding, removing or renaming any file changes it. Symlinks
anywhere in the skill are rejected, never followed. This module only reads.
"""
from __future__ import annotations

import os
from pathlib import Path

from .model import ModelError, digest, local_path, need, sha

SKILL_ROLE = "skill"
SKILL_ROOT = ".agents/skills"
SKILL_FILE = "SKILL.md"
# Roclec's procedure skills and the optional spec-kit adapter own these names.
RESERVED_PREFIXES = ("roclec-", "speckit-")


def skill_location(ref_id):
    return f"{SKILL_ROOT}/{ref_id}"


def check_skill_reference(ref):
    """Shape of a skill reference: an unreserved ID at its canonical location (no filesystem access)."""
    location = skill_location(ref["id"])
    command = f"reference add {ref['id']} --path {location} --role skill --component NAME"
    need(not ref["id"].startswith(RESERVED_PREFIXES), "INVALID_INPUT",
         "Skill IDs starting with roclec- or speckit- are reserved", exit_code=2, entity=ref["id"], actual=ref["id"],
         remediation="Choose a project-owned skill ID; Roclec and the spec-kit adapter own those prefixes.")
    need(ref["path"] == location, "INVALID_PATH", "A skill reference must be its directory under .agents/skills",
         exit_code=2, entity=ref["id"], path=ref["path"], expected=location, actual=ref["path"], remediation=command)


def skill_files(root: Path, relative):
    """Every regular file of the skill directory, keyed by its POSIX path inside it.

    INVALID_PATH names any symlink, non-regular entry or path that resolves outside the
    directory; INVALID_REFERENCE a missing or empty directory.
    """
    directory = local_path(root, relative)  # Rejects a symlinked directory or ancestor.
    need(directory.is_dir(), "INVALID_REFERENCE", "Skill directory is missing", path=relative,
         remediation=f"Create {relative}/{SKILL_FILE} or register the skill at its directory.")
    resolved = directory.resolve()
    result = {}
    for base, folders, names in os.walk(directory, followlinks=False):
        folders.sort()
        for name in sorted(folders + names):
            item = Path(base) / name
            inner = item.relative_to(directory).as_posix()
            offending = f"{relative}/{inner}"
            need(not item.is_symlink(), "INVALID_PATH", "A skill cannot contain symlinks", exit_code=2, path=offending,
                 remediation="Replace the symlink with the file or directory it points to.")
            need(item.resolve().is_relative_to(resolved), "INVALID_PATH", "Skill path resolves outside its directory",
                 exit_code=2, path=offending)
            local_path(root, offending)  # Same path rules as every model path.
            if name in folders:
                continue
            need(item.is_file(), "INVALID_PATH", "A skill may contain only regular files and directories", exit_code=2,
                 path=offending)
            result[inner] = item.read_bytes()
    need(bool(result), "INVALID_REFERENCE", "Skill directory is empty", path=relative,
         remediation=f"Write {relative}/{SKILL_FILE}.")
    return result


def manifest_digest(files):
    """Fingerprint of a skill from its files ({relative path: bytes})."""
    return digest({"files": {path: sha(data) for path, data in files.items()}})


def require_skill(root: Path, ref_id, relative, *, code="INVALID_REFERENCE"):
    """Files of a usable skill: its directory exists with a nonempty regular SKILL.md (add, update, agree)."""
    location = local_path(root, relative)
    need(location.is_dir(), code, "Skill reference requires an existing directory", entity=ref_id, path=relative,
         remediation=f"Create {relative}/{SKILL_FILE} from .roclec/templates/skill-template.md.")
    skill = local_path(root, f"{relative}/{SKILL_FILE}")
    need(skill.is_file() and bool(skill.read_bytes().strip()), code, f"Skill requires a nonempty {SKILL_FILE}",
         entity=ref_id, path=f"{relative}/{SKILL_FILE}",
         remediation=f"Write {relative}/{SKILL_FILE} from .roclec/templates/skill-template.md.")
    return skill_files(root, relative)


def source_fingerprint(root: Path, ref):
    """Current fingerprint of a reference source: file sha256, skill directory manifest, None when missing.

    A skill containing a symlink raises INVALID_PATH rather than yielding a fingerprint.
    """
    path = local_path(root, ref["path"])
    if ref["role"] == SKILL_ROLE:
        if not path.is_dir():
            return None
        try:
            return manifest_digest(skill_files(root, ref["path"]))
        except ModelError as exc:
            if exc.issue["code"] == "INVALID_REFERENCE":  # An empty directory has no source.
                return None
            raise
    return sha(path.read_bytes()) if path.is_file() else None
