"""Structural validation for captured origins and bidirectional AC coverage."""
from pathlib import PurePosixPath

from .model import ModelError, fields, identifier, need, strings, text


def _record_fields(record, required, entity, optional=()):
    try:
        fields(record, required, optional)
    except ModelError as exc:
        exc.issue["entity"] = entity
        exc.issue["remediation"] = "Provide exactly the required fields for this origin or coverage record"
        raise


def _identifier(value, prefix, entity):
    try:
        return identifier(value, prefix)
    except ModelError as exc:
        exc.issue["entity"] = entity
        exc.issue["remediation"] = f"Provide a valid {prefix} identifier for this origin or coverage record"
        raise


def _strings(values, entity, *, nonempty=False):
    try:
        return strings(values, nonempty=nonempty)
    except ModelError as exc:
        exc.issue["entity"] = entity
        exc.issue["remediation"] = "Provide a sorted, unique list of text IDs with the required entries"
        raise


def captured_paths(origins, *, entity=None):
    need(isinstance(origins, list) and bool(origins), "ORIGIN_REQUIRED",
         "Declare at least one captured origin", entity=entity, remediation="Add an origin and its captured Markdown text")
    paths, seen = [], set()
    for origin in origins:
        entity = origin.get("id") if isinstance(origin, dict) else None
        _record_fields(origin, ("kind", "id", "locator", "captured", "criteria"), entity, ("actor",))
        need(text(origin["kind"]) and origin["kind"] in {"fut", "story", "issue", "incident", "request"}
             and text(entity) and text(origin["locator"]), "INVALID_ORIGIN",
             "Origin needs a supported kind, ID and locator", entity=entity)
        need(entity not in seen, "INVALID_ORIGIN", "Origin IDs must be unique within a change", entity=entity)
        seen.add(entity)
        if origin["kind"] == "request":
            need(text(origin.get("actor")), "INVALID_ORIGIN", "Request origin needs the requesting actor", entity=entity)
        else:
            need("actor" not in origin, "INVALID_ORIGIN", "Only request origins declare an actor", entity=entity)
        if origin["kind"] == "fut":
            _identifier(entity, "FUT", entity)
        _strings(origin["criteria"], entity)
        relative = origin["captured"]
        need(text(relative) and "\\" not in relative and not any(ord(c) < 32 for c in relative),
             "INVALID_PATH", "Origin capture must be a relative Markdown path", entity=entity)
        path = PurePosixPath(relative)
        need(not path.is_absolute() and str(path) == relative and ".." not in path.parts
             and path.suffix == ".md" and path.parts[0] not in {"proposed", "revisions"},
             "INVALID_PATH", "Origin capture must stay within the proposal documents", entity=entity, path=relative)
        paths.append(relative)
    return paths


def validate_coverage(origins, coverage, acceptance_ids, changed_acceptance_ids, *, entity=None):
    change_id = entity
    _record_fields(coverage, ("criteria", "derived"), entity)
    need(isinstance(coverage["criteria"], list) and isinstance(coverage["derived"], list),
         "INVALID_COVERAGE", "Coverage criteria and derived ACs must be lists", entity=entity,
         remediation="Declare criteria and derived as lists of coverage records")
    expected = {(origin["id"], criterion) for origin in origins for criterion in origin["criteria"]}
    seen, mapped = set(), set()
    states = {"covered": "acceptance_ids", "excluded": "reason", "deferred": "fut", "gap": "question"}
    for row in coverage["criteria"]:
        need(isinstance(row, dict) and text(row.get("status")) and row["status"] in states,
             "INVALID_COVERAGE", "Criterion needs covered, excluded, deferred or gap status",
             entity=f"{row.get('origin')}/{row.get('criterion')}" if isinstance(row, dict) else None,
             remediation="Declare the criterion outcome and its required details")
        state = row["status"]
        _record_fields(row, ("origin", "criterion", "status", states[state]),
                       f"{row.get('origin')}/{row.get('criterion')}")
        need(text(row["origin"]) and text(row["criterion"]), "INVALID_COVERAGE", "Criterion IDs must be text",
             entity=f"{row['origin']}/{row['criterion']}", remediation="Cite the origin ID and its declared criterion ID")
        pair = (row["origin"], row["criterion"])
        entity = "/".join(pair)
        need(pair in expected and pair not in seen, "INVALID_COVERAGE", "Criterion is unknown or repeated", entity=entity,
             remediation="Give each declared origin criterion exactly one coverage outcome")
        seen.add(pair)
        if state == "covered":
            ids = _strings(row["acceptance_ids"], entity, nonempty=True)
            need(set(ids) <= acceptance_ids, "INVALID_COVERAGE", "Coverage cites an AC outside this change", entity=entity,
                 remediation="Map the criterion to applicable acceptance IDs")
            mapped.update(ids)
        else:
            need(text(row[states[state]]), "INVALID_COVERAGE", f"{state} criterion needs {states[state]}", entity=entity,
                 remediation=f"Provide {states[state]} for this {state} criterion")
            if state == "deferred":
                _identifier(row["fut"], "FUT", entity)
    need(seen == expected, "INVALID_COVERAGE", "Every origin criterion needs an outcome", entity=change_id,
         actual=["/".join(pair) for pair in sorted(expected - seen)], remediation="Add coverage for each missing criterion")
    derived = set()
    for row in coverage["derived"]:
        _record_fields(row, ("id", "reason"), row.get("id") if isinstance(row, dict) else None)
        ac = _identifier(row["id"], "AC", row["id"])
        need(ac in changed_acceptance_ids and ac not in mapped and ac not in derived and text(row["reason"]),
             "INVALID_COVERAGE", "Derived AC needs a unique added or changed ID and reason, without a criterion mapping", entity=ac,
             remediation="Declare derived only for an AC added or changed by this evolution, with its reason")
        derived.add(ac)
    need(changed_acceptance_ids <= mapped | derived, "INVALID_COVERAGE",
         "Every added or changed AC needs a criterion mapping or a derived reason", entity=change_id,
         actual=sorted(changed_acceptance_ids - mapped - derived),
         remediation="Map each added or changed AC or declare why the spec derived it")
