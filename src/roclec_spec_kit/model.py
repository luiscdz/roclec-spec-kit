"""Schema-2 record primitives. This module performs no mutations or shell calls."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re


class ModelError(ValueError):
    def __init__(self, code, message, *, exit_code=1, path=None, entity=None,
                 expected=None, actual=None, remediation=None):
        super().__init__(message)
        self.exit_code = exit_code
        self.issue = dict(code=code, severity="error", entity=entity, path=str(path) if path else None,
                          message=message, expected=expected, actual=actual, remediation=remediation)


def need(condition, code, message, **context):
    if not condition:
        raise ModelError(code, message, **context)


def fields(value, required, optional=()):
    need(isinstance(value, dict), "INVALID_INPUT", "Expected an object", exit_code=2)
    need(set(required) <= value.keys() and value.keys() <= set(required) | set(optional),
         "INVALID_INPUT", "Missing or unknown fields", exit_code=2,
         expected=sorted(required), actual=sorted(value))


def text(value):
    return isinstance(value, str) and bool(value.strip())


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value: bytes):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return sha(canonical(value))


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"


def read_json(path: Path):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "INVALID_INPUT", f"Duplicate JSON key: {key}", exit_code=2, path=path)
            result[key] = value
        return result

    def constant(value):
        raise ModelError("INVALID_INPUT", f"Non-finite JSON value: {value}", exit_code=2, path=path)

    def floating(value):
        number = float(value)
        if not math.isfinite(number):
            constant(value)
        return number

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=constant, parse_float=floating)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ModelError("INVALID_INPUT", f"Invalid JSON: {exc}", exit_code=2, path=path) from exc
    except FileNotFoundError as exc:
        raise ModelError("INVALID_REFERENCE", "Referenced file is missing", path=path) from exc


def schema(record):
    need(type(record.get("model_schema")) is int and record["model_schema"] == 1,
         "UNSUPPORTED_SCHEMA", "Record requires model_schema = 1", exit_code=2)


def identifier(value, prefix):
    need(isinstance(value, str) and re.fullmatch(prefix + r"-[0-9]{3,}", value),
         "INVALID_INPUT", f"Expected {prefix}-NNN identifier", exit_code=2, actual=value)
    return value


def fingerprint(value):
    need(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
         "INVALID_INPUT", "Expected lowercase SHA-256", exit_code=2, actual=value)
    return value


def strings(values, *, nonempty=False):
    need(isinstance(values, list) and all(text(v) for v in values),
         "INVALID_INPUT", "Expected a list of strings", exit_code=2)
    need(values == sorted(set(values)) and (not nonempty or bool(values)),
         "INVALID_INPUT", "List must be sorted, unique and contain required entries", exit_code=2)
    return values


def local_path(root: Path, relative: str):
    """Reject traversal and symlinks, including an escaping symlink in an ancestor."""
    need(text(relative) and "\\" not in relative and not any(ord(c) < 32 for c in relative),
         "INVALID_PATH", "Expected a relative POSIX path", exit_code=2)
    value = PurePosixPath(relative)
    need(not value.is_absolute() and value.parts and ".." not in value.parts
         and str(value) == relative and relative != ".", "INVALID_PATH",
         "Path must stay within its configured root", exit_code=2, path=relative)
    path = root
    for part in value.parts:
        path = path / part
        need(not path.is_symlink(), "INVALID_PATH", "Symlink is not allowed for model content",
             exit_code=2, path=relative)
        need(not path.exists() or path.is_dir() or path == root / value,
             "INVALID_PATH", "A path ancestor is not a directory", exit_code=2, path=relative)
    return path


def checked_files(root: Path, manifest):
    need(isinstance(manifest, dict), "INVALID_INPUT", "files must be an object", exit_code=2)
    contents = {}
    for relative, expected in sorted(manifest.items()):
        fingerprint(expected)
        path = local_path(root, relative)
        need(path.is_file(), "INVALID_REFERENCE", "Missing content file", path=relative)
        content = path.read_bytes()
        need(sha(content) == expected, "HASH_MISMATCH", "Content does not match its descriptor",
             path=relative, expected=expected, actual=sha(content))
        need(path.suffix == ".md" and bool(content.strip()), "INVALID_INPUT",
             "Contract/proposal content must be nonempty Markdown", exit_code=2, path=relative)
        try:
            content.decode("utf-8")
        except UnicodeError as exc:
            raise ModelError("INVALID_INPUT", "Content must be UTF-8", exit_code=2, path=relative) from exc
        contents[relative] = content
    return contents


def validate_contract(record, root: Path, components):
    fields(record, ("model_schema", "capability_id", "requirements", "acceptance", "references", "files"))
    schema(record)
    identifier(record["capability_id"], "CAP")
    contents = checked_files(root, record["files"])
    requirements, acceptance = {}, {}
    for key, prefix, required in (
        ("requirements", "REQ", ("id", "statement", "components", "acceptance_ids")),
        ("acceptance", "AC", ("id", "scenario", "components")),
    ):
        need(isinstance(record[key], list), "INVALID_INPUT", f"{key} must be a list", exit_code=2)
        destination = requirements if key == "requirements" else acceptance
        for entry in record[key]:
            fields(entry, required)
            entry_id = identifier(entry["id"], prefix)
            need(entry_id not in destination, "ID_COLLISION", "Duplicate identity in contract", entity=entry_id)
            scope = strings(entry["components"], nonempty=True)
            need(set(scope) <= set(components), "INVALID_REFERENCE", "Unknown component", entity=entry_id)
            content_path = entry["statement" if prefix == "REQ" else "scenario"]
            need(isinstance(content_path, str) and content_path in contents,
                 "INVALID_REFERENCE", "Missing statement/scenario", entity=entry_id)
            destination[entry_id] = entry
        need(list(destination) == sorted(destination), "INVALID_INPUT", f"{key} must be sorted by ID", exit_code=2)
    owners = {}
    for req_id, req in requirements.items():
        scope = set()
        for ac_id in strings(req["acceptance_ids"], nonempty=True):
            need(ac_id in acceptance and ac_id not in owners, "INVALID_REFERENCE",
                 "Each AC must belong to exactly one requirement", entity=ac_id)
            ac_scope = set(acceptance[ac_id]["components"])
            need(ac_scope <= set(req["components"]), "INVALID_REFERENCE", "AC scope exceeds requirement", entity=ac_id)
            owners[ac_id] = req_id
            scope |= ac_scope
        need(scope == set(req["components"]), "COVERAGE_MISSING", "Requirement has a component without an AC", entity=req_id)
    need(owners.keys() == acceptance.keys(), "INVALID_REFERENCE", "Unowned acceptance criterion")
    used = {r["statement"] for r in requirements.values()} | {a["scenario"] for a in acceptance.values()}
    need(used == contents.keys(), "INVALID_REFERENCE", "Contract files must exactly match statement/scenario paths")
    references = record["references"]
    need(isinstance(references, list), "INVALID_INPUT", "references must be a list", exit_code=2)
    for ref in references:
        fields(ref, ("id", "sha256"))
        need(text(ref["id"]), "INVALID_INPUT", "Reference ID is required", exit_code=2)
        fingerprint(ref["sha256"])
    need([r["id"] for r in references] == sorted({r["id"] for r in references}),
         "INVALID_INPUT", "References must be sorted and unique", exit_code=2)
    return contents


def identities(contract):
    cap = contract["capability_id"]
    result = {cap: {"kind": "CAP", "owner": cap}}
    for req in contract["requirements"]:
        result[req["id"]] = {"kind": "REQ", "owner": cap}
        result.update({ac: {"kind": "AC", "owner": req["id"]} for ac in req["acceptance_ids"]})
    return result


def obligation(contract, req_id, component):
    if contract is None:
        return None
    req = next((r for r in contract["requirements"] if r["id"] == req_id and component in r["components"]), None)
    if req is None:
        return None
    criteria = {a["id"]: contract["files"][a["scenario"]] for a in contract["acceptance"]
                if a["id"] in req["acceptance_ids"] and component in a["components"]}
    return {"statement": contract["files"][req["statement"]], "acceptance": criteria}


def validate_delta(base, proposed, component, deltas):
    """Compare the complete applicable before/after sets, never just claimed ACs."""
    before = {r["id"] for r in (base or {}).get("requirements", []) if component in r["components"]}
    after = {r["id"] for r in proposed["requirements"] if component in r["components"]}
    changed = {r for r in before | after if obligation(base, r, component) != obligation(proposed, r, component)}
    declared = set()
    for delta in deltas:
        op = delta["op"]
        ids = [delta["old_requirement"], delta["new_requirement"]] if op == "replace" else [delta["requirement_id"]]
        if not (set(ids) & (before | after)):
            continue  # This delta applies to another component of the capability.
        need(not (declared & set(ids)), "INVALID_REFERENCE", "Overlapping requirement deltas", entity=ids[0])
        declared.update(ids)
        if op == "add":
            valid = ids[0] not in before and ids[0] in after
        elif op == "retire":
            valid = ids[0] in before and ids[0] not in after
        elif op == "replace":
            valid = ids[0] in before and ids[0] not in after and ids[1] not in before and ids[1] in after
        else:
            valid = ids[0] in before and ids[0] in after
            if valid:
                old = obligation(base, ids[0], component)
                new = obligation(proposed, ids[0], component)
                old_ids, new_ids = set(old["acceptance"]), set(new["acceptance"])
                retired, added = set(delta["retire_acceptance_ids"]), set(delta["add_acceptance_ids"])
                applicable_retired = retired & old_ids
                applicable_added = added & new_ids
                valid = old_ids - new_ids == applicable_retired and new_ids - old_ids == applicable_added
                for ac in old_ids & new_ids:
                    need(old["acceptance"][ac] == new["acceptance"][ac] or delta.get("editorial") is True,
                         "INVALID_REFERENCE", "Changed AC behavior needs a new AC identity", entity=ac)
                if old["statement"] != new["statement"] and not delta.get("editorial"):
                    need(bool(applicable_added), "INVALID_REFERENCE", "Revised behavior requires new ACs", entity=ids[0])
        need(valid, "INVALID_REFERENCE", "Delta does not match its exact base and proposed contract", entity=ids[0])
    need(changed == declared,
         "INVALID_REFERENCE", "Proposed contract contains undeclared requirement changes",
         expected=sorted(declared), actual=sorted(changed))
    # Unchanged IDs may survive; a pending proposal never edits the base descriptor.


def version_key(value, *, historical=False):
    pattern = r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?" if historical else r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    match = re.fullmatch(pattern, value) if isinstance(value, str) else None
    need(match is not None, "VERSION_INVALID", "Version must be vX.Y.Z (legacy vX.Y is read-only)", actual=value)
    return tuple(int(v or 0) for v in match.groups())
