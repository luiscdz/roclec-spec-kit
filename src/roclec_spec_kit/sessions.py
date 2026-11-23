"""Opaque agent-session evidence (M-34).

A host-exported transcript is imported without being interpreted: Roclec keeps the
original bytes locally under ``.roclec/runtime/sessions/``, records their SHA-256 and
size, and versions a copy according to the profile ``[sessions]`` policy. Only the
declared metadata is validated; the host format is never parsed.
"""
from __future__ import annotations

import contextlib
from datetime import datetime
import hashlib
import json
import os
import re
import subprocess

from .causality import record_id
from .config import SESSION_STORAGES
from .flow import STAGES
from .model import (ModelError, digest, encoded, fields, fingerprint, identifier, need, read_json, schema, sha, text,
                    version_key)

KIND = "agent-session"
META_REQUIRED = ("model_schema", "host", "host_session_id", "actor", "role", "model", "started_at", "ended_at", "stage")
META_OPTIONAL = ("change_id", "component", "subject", "release")
STORED = ("kind", "id", "executed_by_roclec", "transcript", "digest")
# Stages whose session belongs to one component of a change; the other change stages may name one.
COMPONENT_STAGES = ("design", "implement", "verify", "review", "integrate")
TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
ROLE = re.compile(r"[a-z][a-z0-9-]*")
REDACTED = "[REDACTED]"
RECORD_HINT = ("Import a host session with evidence record --kind agent-session --file META.json --transcript PATH; "
               "the metadata file must not declare kind.")
STRICT_TIME = "%Y-%m-%dT%H:%M:%SZ"


def single_line(value):
    return text(value) and value.splitlines() == [value]


def invalid(message, **context):
    return ModelError("INVALID_INPUT", message, exit_code=2, **context)


def timestamp(value, name):
    parsed = None
    if isinstance(value, str) and TIMESTAMP.fullmatch(value):
        with contextlib.suppress(ValueError):
            parsed = datetime.strptime(value, STRICT_TIME)
    need(parsed is not None, "INVALID_INPUT", f"{name} must be a UTC timestamp YYYY-MM-DDTHH:MM:SSZ", exit_code=2,
         entity=name, actual=value, remediation=f"Write {name} in UTC, for example 2026-01-31T09:30:00Z.")
    return parsed


def safe_name(name):
    """A transcript basename usable as one plain file name inside the runtime folder."""
    need(isinstance(name, str) and bool(name) and not name.startswith(".") and "/" not in name and "\\" not in name
         and not any(ord(c) < 32 or ord(c) == 127 for c in name) and len(name.encode("utf-8", "surrogateescape")) <= 255,
         "INVALID_INPUT", "Transcript file name must be a plain, visible file name", exit_code=2, actual=name,
         remediation="Rename the exported transcript to a name without a leading dot, path separators or control characters.")
    try:
        name.encode("utf-8")
    except UnicodeError:
        raise invalid("Transcript file name must be valid UTF-8", actual=repr(name),
                      remediation="Rename the exported transcript using UTF-8 characters.") from None
    return name


def shape(record, components):
    """Structural metadata rules shared by import and stored records; no project lookups."""
    schema(record)
    for key in ("host", "host_session_id", "actor", "model"):
        need(single_line(record[key]), "INVALID_INPUT", f"{key} must be non-empty single-line text", exit_code=2,
             entity=key, remediation=f"Declare {key} as one line of text, as reported by the host.")
    need(single_line(record["role"]) and ROLE.fullmatch(record["role"]) is not None, "INVALID_INPUT",
         "role must be a role name", exit_code=2, entity="role", actual=record["role"],
         remediation="Use a built-in role or an agent role declared in .roclec/flow.toml.")
    started, ended = timestamp(record["started_at"], "started_at"), timestamp(record["ended_at"], "ended_at")
    need(ended >= started, "INVALID_INPUT", "ended_at precedes started_at", exit_code=2,
         actual=[record["started_at"], record["ended_at"]], remediation="Declare the session's real start and end times.")
    stage = record["stage"]
    need(stage in STAGES, "INVALID_INPUT", "Unknown session stage", exit_code=2, expected=list(STAGES), actual=stage,
         remediation="Use one of the canonical flow stages: " + ", ".join(STAGES) + ".")
    present = {key for key in META_OPTIONAL if key in record}
    if stage == "foundation":
        allowed, required = {"subject"}, {"subject"}
    elif stage == "release":
        allowed, required = {"release", "component"}, {"release"}
    else:
        allowed = {"change_id", "component"}
        required = {"change_id", "component"} if stage in COMPONENT_STAGES else {"change_id"}
    need(required <= present <= allowed, "INVALID_INPUT", f"Invalid scope for a {stage} session", exit_code=2,
         expected=sorted(required), actual=sorted(present),
         remediation=(f"A {stage} session declares " + " and ".join(sorted(required))
                      + (f" (optionally {', '.join(sorted(allowed - required))})" if allowed - required else "")
                      + " and no other scope field."))
    if "subject" in record:
        need(single_line(record["subject"]), "INVALID_INPUT", "subject must be a reference or ADR ID", exit_code=2,
             remediation="Name the foundation reference or ADR the session worked on.")
    if "change_id" in record:
        identifier(record["change_id"], "CHG")
    if "release" in record:
        fields(record["release"], ("component", "version"))
        version_key(record["release"]["version"], historical=True)
        need(record.get("component", record["release"]["component"]) == record["release"]["component"],
             "INVALID_INPUT", "component differs from the release component", exit_code=2,
             remediation="Omit component or use the release component.")
    for component in [record.get("component"), (record.get("release") or {}).get("component")]:
        if component is not None:
            need(isinstance(component, str) and component in components, "INVALID_REFERENCE", "Unknown session component",
                 exit_code=2, actual=component, expected=sorted(components), remediation="Use a configured component.")


def validate_meta(kernel, meta):
    """Declared metadata of a new import, checked against the current project."""
    need(isinstance(meta, dict), "INVALID_INPUT", "Session metadata must be an object", exit_code=2)
    need("kind" not in meta, "INVALID_INPUT", "Session metadata must not declare kind", exit_code=2,
         remediation="Remove kind; Roclec sets kind = agent-session.")
    fields(meta, META_REQUIRED, META_OPTIONAL)
    shape(meta, kernel.profile.components)
    from .agents import contracts
    builtin = tuple(contracts())
    if meta["role"] not in builtin:
        from . import flow
        try:
            roles = flow.load(kernel.profile.root)["roles"]
        except ModelError as exc:
            if exc.issue["code"] != "FLOW_MISSING":
                raise
            roles = {}
        agents = sorted(name for name, row in roles.items() if row["kind"] == "agent")
        need(meta["role"] in agents, "INVALID_REFERENCE", "Unknown agent role", exit_code=2, actual=meta["role"],
             expected=[*builtin, *agents],
             remediation="Use a built-in role or declare it in .roclec/flow.toml under [roles] with kind = \"agent\".")
    if "subject" in meta:
        need(meta["subject"] in kernel.references(), "INVALID_REFERENCE", "Unknown foundation subject", exit_code=2,
             entity=meta["subject"], remediation="Name a registered reference or ADR (see references.json).")
    if "change_id" in meta:
        imported = kernel.store.path(f".roclec/changes/{meta['change_id']}/change.json").is_file()
        # The session that drafts a change precedes its import, so the first bundle can cite it.
        need(imported or meta["stage"] == "define", "INVALID_REFERENCE", "Unknown change", exit_code=2,
             entity=meta["change_id"], remediation="Cite an imported change ID (only define sessions may precede it).")
        need(imported or "component" not in meta, "INVALID_INPUT", "A define session before its change is imported names no component",
             exit_code=2, entity=meta["change_id"], remediation="Remove component; the session then counts for every component.")
        if imported and "component" in meta:
            scope = kernel.change(meta["change_id"])[0]["semantic"]["components"]
            need(meta["component"] in scope, "INVALID_REFERENCE", "Session component is outside the change", exit_code=2,
                 entity=meta["component"], expected=scope, remediation="Use one of the change components: " + ", ".join(scope) + ".")
    if "release" in meta:
        try:
            kernel.release(**meta["release"])
        except ModelError as exc:
            raise ModelError("INVALID_REFERENCE", "Unknown release", exit_code=2, actual=meta["release"], entity=exc.issue["entity"],
                             remediation="Cite a planned release with release plan COMPONENT VERSION.") from exc


def redact(content, profile):
    """Strict UTF-8 transcript with secret values and patterns replaced, as run-log excerpts do."""
    try:
        value = content.decode("utf-8")
    except UnicodeError:
        raise invalid("Transcript is not valid UTF-8 and cannot be redacted", remediation=(
            'Set [sessions] storage = "local" in .roclec/project.toml to keep it only locally.')) from None
    values = {os.environ[key] for key in profile.get("secret_env", []) if os.environ.get(key)}
    # Host transcripts are usually JSON lines: a secret may appear only in its JSON-escaped forms.
    forms = {form for secret in values
             for form in (secret, json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1]) if form}
    secrets = sorted(forms, key=len, reverse=True)
    count = 0
    for secret in secrets:
        count += value.count(secret)
        value = value.replace(secret, REDACTED)
    for pattern in profile.get("redact_patterns", []):
        value, found = re.subn(pattern, REDACTED, value)
        count += found
    return value.encode("utf-8"), count


def redaction_warnings(profile):
    """Why a versioned-redacted import may still carry secrets: nothing effective to redact."""
    unset = [key for key in profile.get("secret_env", []) if not os.environ.get(key)]
    if unset:
        yield {**ModelError("SESSION_SECRET_UNSET", "Declared secret variables are unset; their values were not redacted",
                            actual=unset, path=".roclec/project.toml",
                            remediation="Import the session from a shell where these secret_env variables are set.").issue,
               "severity": "warning"}
    if len(unset) == len(profile.get("secret_env", [])) and not profile.get("redact_patterns"):
        yield {**ModelError("SESSION_REDACTION_EMPTY", "No secret value or pattern was available; the copy is unredacted",
                            path=".roclec/project.toml",
                            remediation="Declare secret_env or redact_patterns, or use [sessions] storage = \"local\".").issue,
               "severity": "warning"}


def require_ignored(root):
    """Originals live in .roclec/runtime/, which must stay out of Git."""
    probe = ".roclec/runtime/sessions/probe"
    try:
        ignored = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "--no-index", probe],
                                 capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ignored = False
    need(ignored, "RUNTIME_NOT_IGNORED", "Session originals would not be ignored by Git", exit_code=2, path=".gitignore",
         remediation="Add the line .roclec/runtime/ to .gitignore (roclec skills restores it), then import again.")


def sync_folder(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def raw_path(record):
    return f".roclec/runtime/sessions/{record['id']}/{record['transcript']['name']}"


def copy_path(record):
    return f".roclec/evidence/{record['id']}.session"


def keep_raw(store, relative, content):
    """Write the original once, owner-only, below the untracked runtime folder."""
    folder = relative.rsplit("/", 1)[0]
    store.path(".roclec/runtime").mkdir(parents=True, exist_ok=True)
    for part in (".roclec/runtime/sessions", folder):
        store.path(part).mkdir(mode=0o700, exist_ok=part != folder)
    descriptor = os.open(store.path(relative), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        data = memoryview(content)
        while data:
            written = os.write(descriptor, data)
            if written <= 0:
                raise OSError("Session copy made no progress")
            data = data[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    # Make the new entries durable before a tracked record refers to them.
    for part in (folder, ".roclec/runtime/sessions", ".roclec/runtime"):
        sync_folder(store.path(part))


def drop_raw(store, session_id, relative):
    """Remove the local original of an import that left no record and no pending journal.

    Best effort: cleanup never replaces the failure that triggered it.
    """
    with contextlib.suppress(ModelError, OSError):
        if store.path(f".roclec/evidence/{session_id}.json").exists():
            return
        for journal in store.path(".roclec/runtime").glob("*.json"):
            try:
                if read_json(journal).get("payload", {}).get("id") == session_id:
                    return
            except (ModelError, AttributeError):
                return  # An unreadable journal may be ours; keep the original for recovery.
        path = store.path(relative)
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def record(kernel, meta_file, transcript):
    """Validate, keep the original locally, then record the session and its versioned copy."""
    meta = read_json(meta_file)
    validate_meta(kernel, meta)
    policy = kernel.profile.sessions
    storage, quota = policy["storage"], policy["quota_bytes"]
    need(transcript.is_file(), "INVALID_REFERENCE", "Transcript file is missing", exit_code=2, path=transcript,
         remediation="Pass the exported transcript file with --transcript PATH.")
    name = safe_name(transcript.name)
    too_large = dict(exit_code=2, path=transcript, expected=quota,
                     remediation="Raise [sessions] quota_bytes in .roclec/project.toml or split the export into smaller sessions.")
    size = transcript.stat().st_size
    need(size <= quota, "SESSION_QUOTA_EXCEEDED", "Transcript exceeds the session quota", actual=size, **too_large)
    with transcript.open("rb") as stream:
        content = stream.read(quota + 1)
    need(len(content) <= quota, "SESSION_QUOTA_EXCEEDED", "Transcript exceeds the session quota", actual=len(content), **too_large)
    need(bool(content), "INVALID_INPUT", "Transcript is empty", exit_code=2, path=transcript,
         remediation="Export the session again; an empty transcript is not evidence.")
    require_ignored(kernel.profile.root)
    versioned, details, warnings = None, {}, []
    if storage == "versioned-redacted":
        versioned, count = redact(content, kernel.profile.data)
        details["redactions"] = count
        warnings = list(redaction_warnings(kernel.profile.data))
    elif storage == "versioned-raw":
        versioned = content
    session = {**meta, "kind": KIND, "id": record_id("EVD"), "executed_by_roclec": False,
               "transcript": {"name": name, "sha256": sha(content), "size": len(content), "storage": storage,
                              "versioned_sha256": None if versioned is None else sha(versioned), **details}}
    session["digest"] = digest(session)
    writes = {f".roclec/evidence/{session['id']}.json": encoded(session)}
    if versioned is not None:
        writes[copy_path(session)] = versioned
    raw = raw_path(session)
    try:
        # The original exists locally before any tracked write refers to it.
        keep_raw(kernel.store, raw, content)
        receipt = kernel.store.apply("session-record", {"id": session["id"]}, writes, kernel.token)
    except BaseException:
        drop_raw(kernel.store, session["id"], raw)
        raise
    result = {"evidence": session, "receipt": receipt}
    if warnings:
        result["warnings"] = warnings
    return result


def integrity(path, record, components):
    """Identity, digest and shape of a stored session record, without reading its copies."""
    need(isinstance(record.get("id"), str) and record["id"] == path.stem, "INVALID_REFERENCE",
         "Evidence identity differs from its path", path=str(path))
    need(record.get("digest") == digest({k: v for k, v in record.items() if k != "digest"}),
         "HASH_MISMATCH", "Session record integrity mismatch", entity=record["id"])
    fields(record, META_REQUIRED + STORED, META_OPTIONAL)
    shape(record, components)
    return record


def read(kernel, path, record):
    """Validate a stored session record and its versioned copy; the local original is checked by issues()."""
    fields(record, META_REQUIRED + STORED, META_OPTIONAL)
    need(record["kind"] == KIND and record["executed_by_roclec"] is False, "INVALID_INPUT",
         "An agent session is a declared import", exit_code=2, entity=record["id"])
    identifier(record["id"], "EVD")
    need(record["id"] == path.stem, "INVALID_REFERENCE", "Evidence identity differs from its path")
    need(record["digest"] == digest({k: v for k, v in record.items() if k != "digest"}),
         "HASH_MISMATCH", "Session record integrity mismatch", entity=record["id"])
    shape(record, kernel.profile.components)
    transcript = record["transcript"]
    storage = transcript.get("storage") if isinstance(transcript, dict) else None
    fields(transcript, ("name", "sha256", "size", "storage", "versioned_sha256"),
           ("redactions",) if storage == "versioned-redacted" else ())
    safe_name(transcript["name"])
    fingerprint(transcript["sha256"])
    need(storage in SESSION_STORAGES and type(transcript["size"]) is int and transcript["size"] > 0
         and (storage != "versioned-redacted" or (type(transcript.get("redactions")) is int and transcript["redactions"] >= 0)),
         "INVALID_INPUT", "Invalid session transcript descriptor", exit_code=2, entity=record["id"])
    copy = kernel.store.path(copy_path(record))
    if storage == "local":
        need(transcript["versioned_sha256"] is None, "INVALID_INPUT", "A local session has no versioned copy", exit_code=2,
             entity=record["id"])
        need(not copy.exists(), "INVALID_REFERENCE", "A local-only session has a versioned copy", entity=record["id"],
             path=copy_path(record), remediation="Remove the stray copy; this session is kept only locally.")
        return record
    fingerprint(transcript["versioned_sha256"])
    need(storage != "versioned-raw" or transcript["versioned_sha256"] == transcript["sha256"], "HASH_MISMATCH",
         "A raw versioned copy must equal the original", entity=record["id"])
    need(storage != "versioned-redacted" or transcript["redactions"] > 0
         or transcript["versioned_sha256"] == transcript["sha256"], "HASH_MISMATCH",
         "A copy without redactions must equal the original", entity=record["id"])
    need(copy.is_file(), "INVALID_REFERENCE", "Versioned session copy is missing", entity=record["id"], path=copy_path(record))
    need(sha(copy.read_bytes()) == transcript["versioned_sha256"], "HASH_MISMATCH",
         "Versioned session copy differs from its record", entity=record["id"], path=copy_path(record))
    return record


def issues(store, record):
    """Local original: unavailable is a limitation; present but different is an integrity failure."""
    relative = raw_path(record)
    path = store.path(relative)
    if not path.is_file():
        issue = ModelError("SESSION_RAW_UNAVAILABLE", "Local session original is unavailable", path=relative,
                           entity=record["id"]).issue
        yield {**issue, "severity": "warning"}
        return
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    need(actual == record["transcript"]["sha256"] and path.stat().st_size == record["transcript"]["size"],
         "HASH_MISMATCH", "Local session original differs from its record", path=relative, entity=record["id"])


# ---- citations (TL.3) and required stages (TL.4) --------------------------------------------

SESSION_ID = re.compile(r"EVD-[0-7][0-9A-HJKMNP-TV-Z]{25}")


def looks_like_id(value):
    return isinstance(value, str) and SESSION_ID.fullmatch(value.strip()) is not None


def ids(value):
    """Shape of a stored citation list: a nonempty, sorted, unique list of EVD IDs (omitted when empty)."""
    need(isinstance(value, list) and bool(value), "INVALID_INPUT", "sessions must be a nonempty list; omit it when empty",
         exit_code=2, actual=value)
    for item in value:
        identifier(item, "EVD")
    need(value == sorted(set(value)), "INVALID_INPUT", "sessions must be sorted and unique", exit_code=2, actual=value)
    return value


def find(kernel, session_id):
    """The validated agent-session record of an ID, or None when no such EVD exists or it is another kind."""
    relative = f".roclec/evidence/{session_id}.json"
    path = kernel.store.path(relative)
    if not looks_like_id(session_id) or not path.is_file():
        return None
    record = kernel.read(relative)
    return read(kernel, path, record) if record.get("kind") == KIND else None


def same_release(first, second):
    if not isinstance(first, dict) or not isinstance(second, dict) or first.get("component") != second.get("component"):
        return False
    return version_key(first["version"], historical=True) == version_key(second["version"], historical=True)


def scope_text(change_id=None, release=None, subject=None):
    if change_id is not None:
        return f"change_id {change_id}"
    if release is not None:
        return f"release {release['component']} {release['version']}"
    if subject is not None:
        return f"subject {subject}"
    return "any scope"


def cite(kernel, values, *, change_id=None, release=None, subject=None):
    """Validate the sessions a new record cites; return them sorted and unique ([] when none).

    Each ID must be an existing agent session; with a scope, the session must name that change
    (change_id), release (release) or foundation subject (subject).
    """
    if values is None:
        return []  # Absent citation; any other non-list value (null aside) is rejected below.
    need(isinstance(values, (list, tuple)) and all(isinstance(v, str) for v in values), "INVALID_INPUT",
         "sessions must be a list of EVD IDs", exit_code=2, actual=values)
    if not values:
        return []
    result = sorted(set(values))
    hint = (f"Cite an agent session recorded for {scope_text(change_id, release, subject)}; import one with "
            "roclec evidence record --kind agent-session --file META.json --transcript PATH.")
    for session_id in result:
        identifier(session_id, "EVD")
        path = kernel.store.path(f".roclec/evidence/{session_id}.json")
        need(path.is_file(), "INVALID_REFERENCE", "Unknown agent session", exit_code=2, entity=session_id, remediation=hint)
        record = kernel.read(f".roclec/evidence/{session_id}.json")
        need(record.get("kind") == KIND, "INVALID_REFERENCE", "Cited evidence is not an agent session", exit_code=2,
             entity=session_id, actual=record.get("kind"), remediation=hint)
        record = read(kernel, path, record)
        if change_id is not None:
            matched = record.get("change_id") == change_id
        elif release is not None:
            matched = same_release(record.get("release"), release)
        elif subject is not None:
            matched = record.get("subject") == subject
        else:
            matched = True
        need(matched, "INVALID_REFERENCE", "Cited agent session is outside this record's scope", exit_code=2,
             entity=session_id, expected=scope_text(change_id, release, subject),
             actual={k: record[k] for k in ("stage", *META_OPTIONAL) if k in record}, remediation=hint)
    return result


def matches(record, stage, *, change_id=None, component=None, subject=None, release=None, any_component=False):
    """Whether a session counts for `stage` of one scope (see required())."""
    if record["stage"] != stage:
        return False
    if stage == "foundation":
        return record.get("subject") == subject
    if stage == "release":
        return same_release(record.get("release"), release)
    if record.get("change_id") != change_id:
        return False
    if component is None:
        return True
    return record.get("component") == component or (any_component and "component" not in record)


def required_hint(stage, *, change_id=None, component=None, subject=None, release=None):
    scope = {"stage": stage}
    if stage == "foundation":
        scope["subject"] = subject
    elif stage == "release":
        scope["release"] = release
    else:
        scope["change_id"] = change_id
        if component is not None:
            scope["component"] = component
    declared = ", ".join(f"{key} {value if not isinstance(value, dict) else value['component'] + ' ' + value['version']}"
                         for key, value in scope.items())
    return (f"Import the {stage} session with roclec evidence record --kind agent-session --file <meta.json> "
            f"--transcript <export>, its metadata declaring {declared}.")


def stray_warnings(store, sessions):
    """Session files that no stored session record explains: orphaned originals and versioned copies."""
    known = {record["id"] for record in sessions}
    pending = set()
    for journal in store.path(".roclec/runtime").glob("*.json") if store.path(".roclec/runtime").is_dir() else ():
        with contextlib.suppress(ModelError, AttributeError, OSError):
            pending.add(read_json(journal).get("payload", {}).get("id"))
    folder = store.path(".roclec/runtime/sessions")
    for path in sorted(folder.iterdir()) if folder.is_dir() else ():
        if path.name not in known and path.name not in pending:
            yield {**ModelError("SESSION_RAW_ORPHAN", "Local session original has no session record",
                                path=f".roclec/runtime/sessions/{path.name}",
                                remediation="Delete the folder after checking it holds no evidence you need.").issue,
                   "severity": "warning"}
    for path in sorted(store.path(".roclec/evidence").glob("EVD-*.session")):
        need(path.stem in known, "INVALID_REFERENCE", "Versioned session copy has no session record",
             path=f".roclec/evidence/{path.name}", remediation="Remove the stray copy or restore its session record.")


def policy_warnings(profile, sessions=()):
    redacted = [s["id"] for s in sessions if s["transcript"]["storage"] == "versioned-redacted"]
    if redacted and not profile.data.get("secret_env") and not profile.data.get("redact_patterns"):
        yield {**ModelError("SESSION_REDACTION_EMPTY", "Versioned session copies are redacted without any secret or pattern",
                            path=".roclec/project.toml", actual=redacted,
                            remediation="Declare secret_env or redact_patterns, or use [sessions] storage = \"local\".").issue,
               "severity": "warning"}
    if profile.sessions["storage"] == "versioned-raw":
        issue = ModelError("SESSION_RAW_VERSIONED", "Agent sessions are versioned without redaction and may contain secrets",
                           path=".roclec/project.toml",
                           remediation='Use [sessions] storage = "versioned-redacted" or "local" unless raw sessions are intended.').issue
        yield {**issue, "severity": "warning"}
