"""Structured review findings and their causal, read-only state projection."""
from __future__ import annotations

from pathlib import PurePosixPath
import re

from .model import fields, fingerprint, identifier, need, strings, text
from .config import FINDING_SEVERITIES as SEVERITIES

OPEN = {"open", "still-open"}


def finding_key(value):
    need(isinstance(value, str) and "#" in value,
         "INVALID_REFERENCE", "A finding reference must be EVD-ID#F-n", exit_code=2, actual=value)
    evidence, local = value.split("#", 1)
    identifier(evidence, "EVD")
    need(text(local), "INVALID_INPUT", "A finding reference needs its original local ID", exit_code=2)
    return value


def validate_findings(values, *, historical=False):
    need(isinstance(values, list), "INVALID_INPUT", "findings must be a list", exit_code=2)
    seen = set()
    for value in values:
        if historical and isinstance(value, dict) and set(value) == {"id", "description"}:
            need(text(value["id"]) and text(value["description"]), "INVALID_INPUT", "Invalid historical finding", exit_code=2)
        else:
            fields(value, ("id", "severity", "location", "acceptance_ids", "condition", "impact", "description"), ("recurs_from",))
            need(isinstance(value["id"], str) and re.fullmatch(r"F-[0-9]+", value["id"]),
                 "INVALID_INPUT", "A finding ID must be F-n", exit_code=2)
            need(value["severity"] in SEVERITIES, "INVALID_INPUT", "Unknown finding severity", exit_code=2,
                 expected=list(SEVERITIES), actual=value["severity"])
            strings(value["acceptance_ids"])
            need(all(text(value[key]) for key in ("condition", "impact", "description")),
                 "INVALID_INPUT", "Findings require condition, impact and description", exit_code=2)
            location = value["location"]
            if location is not None:
                fields(location, ("path", "line"))
                path = location["path"]
                need(text(path) and "\\" not in path and not any(ord(char) < 32 for char in path),
                     "INVALID_PATH", "Finding location needs a relative POSIX path", exit_code=2)
                parsed = PurePosixPath(path)
                need(not parsed.is_absolute() and ".." not in parsed.parts and str(parsed) == path and path != ".",
                     "INVALID_PATH", "Finding location must stay within the project", exit_code=2)
                need(type(location["line"]) is int and location["line"] > 0,
                     "INVALID_INPUT", "Finding location line must be positive", exit_code=2)
            if "recurs_from" in value:
                finding_key(value["recurs_from"])
        need(value["id"] not in seen, "ID_COLLISION", "Duplicate finding ID", actual=value["id"])
        seen.add(value["id"])


def validate_resolutions(values, candidate_digest):
    need(isinstance(values, list), "INVALID_INPUT", "resolutions must be a list", exit_code=2)
    seen = set()
    for value in values:
        fields(value, ("finding", "status", "candidate_digest", "note"))
        key = finding_key(value["finding"])
        need(key not in seen, "ID_COLLISION", "Duplicate finding resolution", actual=key)
        seen.add(key)
        need(value["status"] in ("fixed", "still-open") and text(value["note"]),
             "INVALID_INPUT", "Reviewer resolutions require fixed/still-open and a note", exit_code=2)
        fingerprint(value["candidate_digest"])
        need(value["candidate_digest"] == candidate_digest, "EVIDENCE_STALE", "Resolution must cite the reviewed candidate", actual=key)


def transitions(record):
    if record["kind"] == "finding-decision":
        return {key: {"status": record["status"], **({"severity": record["severity"]} if "severity" in record else {})}
                for key in record["findings"]}
    return {item["finding"]: item for item in record.get("resolutions", [])}


def project(records):
    """Project each finding using its own DAG, without ordering by ID or merge order."""
    ids = {record["id"]: record for record in records}
    need(len(ids) == len(records), "ID_COLLISION", "Duplicate evidence identity")
    roots = {}
    for record in records:
        if record["kind"] == "finding-decision":
            continue
        for finding in record["findings"]:
            key = record["id"] + "#" + finding["id"]
            roots[key] = (record, finding)
    events = {key: {record["id"]: {"status": "open"}} for key, (record, _) in roots.items()}
    for record in records:
        changes = transitions(record)
        parents = record.get("finding_parents", {})
        need(isinstance(parents, dict) and parents.keys() == changes.keys(),
             "INVALID_REFERENCE", "Finding transitions must declare their causal predecessors", entity=record["id"])
        for key, change in changes.items():
            need(key in roots, "INVALID_REFERENCE", "Finding is absent from this evidence scope", actual=key)
            need(record["id"] != roots[key][0]["id"], "INVALID_REFERENCE", "A review cannot resolve its own finding", actual=key)
            strings(parents[key], nonempty=True)
            events[key][record["id"]] = change
    result = []
    dependencies = {record["id"]: set() for record in records}
    for key, (origin, finding) in sorted(roots.items()):
        pending = set(events[key])
        ordered, heads = set(), set(events[key])
        severities = {}
        while pending:
            ready = []
            for event_id in sorted(pending):
                parents = ids[event_id].get("finding_parents", {}).get(key, [])
                need(set(parents) <= events[key].keys(), "INVALID_REFERENCE", "Finding predecessor does not exist in this scope", actual=key)
                if set(parents) <= ordered:
                    if parents:
                        previous = [events[key][parent]["status"] for parent in parents]
                        if ids[event_id]["kind"] == "independent-review":
                            need(not any(ids[parent]["kind"] == "finding-decision" for parent in parents),
                                 "INVALID_REFERENCE", "Only a user can supersede a user finding disposition", actual=key)
                            if "fixed" in previous:
                                need(len(set(previous)) > 1 and events[key][event_id]["status"] == "fixed",
                                     "INVALID_REFERENCE", "A reviewer can only confirm fixed when reconciling a fixed conflict", actual=key)
                        if ids[event_id]["kind"] == "finding-decision":
                            need(set(previous) != {"fixed"}, "INVALID_REFERENCE",
                                 "A fixed finding requires a new recurrence", actual=key)
                        dependencies[event_id].update(parents)
                        dependencies[event_id].add(origin["id"])
                    ready.append(event_id)
                    inherited = max((severities[parent] for parent in parents), key=SEVERITIES.index) if parents else finding.get("severity", "major")
                    severities[event_id] = events[key][event_id].get("severity", inherited)
                    heads.difference_update(parents)
            need(bool(ready), "INVALID_REFERENCE", "Finding transition cycle", actual=key)
            ordered.update(ready)
            pending.difference_update(ready)
        state_ids = sorted(heads)
        human_ids = [event_id for event_id in state_ids if ids[event_id]["kind"] == "finding-decision"]
        effective_ids = human_ids or state_ids
        statuses = {events[key][event_id]["status"] for event_id in effective_ids}
        ambiguous = len(statuses) > 1
        severity = max((severities[event_id] for event_id in effective_ids), key=SEVERITIES.index)
        status = "still-open" if ambiguous else next(iter(statuses))
        result.append({**finding, "key": key, "severity": severity, "location": finding.get("location"),
                       "acceptance_ids": finding.get("acceptance_ids", []), "status": status,
                       "state_record": effective_ids[0] if not ambiguous else None, "state_records": state_ids,
                       "ambiguous": ambiguous, "requires_human": bool(human_ids) and ambiguous,
                       "evidence_id": origin["id"], "change_id": origin["change_id"],
                       "component": origin["component"], **({"release": origin["release"]} if "release" in origin else {})})
    for record in records:
        if record["kind"] == "finding-decision":
            continue
        recurring = {finding["id"]: finding["recurs_from"] for finding in record["findings"] if "recurs_from" in finding}
        witnesses = record.get("recurrence_witnesses", {})
        need(isinstance(witnesses, dict) and witnesses.keys() == recurring.keys(),
             "INVALID_REFERENCE", "Recurring findings must bind their prior fixed witness", entity=record["id"])
        for local, previous in recurring.items():
            need(previous in roots and previous != record["id"] + "#" + local,
                 "INVALID_REFERENCE", "Recurring finding must cite an earlier finding in this scope", actual=previous)
            witness = witnesses[local]
            need(isinstance(witness, str) and witness in events[previous] and events[previous][witness]["status"] == "fixed",
                 "INVALID_REFERENCE", "Recurring finding must cite a fixed witness", actual=previous)
            dependencies[record["id"]].update((roots[previous][0]["id"], witness))
    pending = set(dependencies)
    visited = set()
    while pending:
        ready = {event_id for event_id in pending if dependencies[event_id] <= visited}
        need(bool(ready), "INVALID_REFERENCE", "Cyclic finding provenance")
        visited.update(ready)
        pending.difference_update(ready)
    return result
