"""Human rejection records, immutable source copies and correction links."""
import re

from .model import digest, fields, fingerprint, identifier, need, read_json, sha, text


def corrections(value, consequence):
    need(isinstance(value, (list, tuple)), "INVALID_INPUT", "Corrections must be a list", exit_code=2)
    ids = []
    for row in value:
        fields(row, ("id", "description"))
        need(text(row["id"]) and re.fullmatch(r"R-[1-9][0-9]*", row["id"]) is not None
             and text(row["description"]), "INVALID_INPUT", "Correction needs an R-N ID and description", exit_code=2)
        ids.append(row["id"])
    need(len(ids) == len(set(ids)) and (bool(ids) or consequence == "cancel"), "INVALID_INPUT",
         "Corrections must be unique and nonempty unless canceling", exit_code=2)


def addresses(value):
    fields(value, ("rejection", "corrections"))
    fingerprint(value["rejection"])
    need(isinstance(value["corrections"], list), "INVALID_INPUT", "Correction responses must be a list", exit_code=2)
    ids = []
    for row in value["corrections"]:
        fields(row, ("id", "status"), ("reason",))
        need(text(row["id"]) and text(row["status"]) and row["status"] in {"addressed", "disputed"}, "INVALID_INPUT",
             "Correction response needs an ID and addressed or disputed status", exit_code=2)
        need("reason" not in row or text(row["reason"]), "INVALID_INPUT", "Response reason must be nonempty", exit_code=2)
        need(row["status"] != "disputed" or text(row.get("reason")), "INVALID_INPUT",
             "A disputed correction requires a reason", exit_code=2)
        ids.append(row["id"])
    need(len(ids) == len(set(ids)), "INVALID_INPUT", "Duplicate correction response", exit_code=2)
    return value


def criteria(value):
    need(isinstance(value, (list, tuple)), "INVALID_INPUT", "Criteria must be a list", exit_code=2)
    ids = []
    for row in value:
        fields(row, ("id", "status"), ("reason",))
        need(text(row["id"]) and text(row["status"]) and row["status"] in {"met", "not-met", "n/a"}, "INVALID_INPUT",
             "Invalid criterion evaluation", exit_code=2)
        need(row["status"] != "n/a" or text(row.get("reason")), "INVALID_INPUT", "n/a requires a reason", exit_code=2)
        need("reason" not in row or text(row["reason"]), "INVALID_INPUT", "Criterion reason must be nonempty", exit_code=2)
        ids.append(row["id"])
    need(len(ids) == len(set(ids)) and (not value or any(r["status"] == "not-met" for r in value)),
         "INVALID_INPUT", "A rejection must cite a not-met criterion with unique IDs", exit_code=2)


def validate_decision(record):
    subject = record.get("subject")
    fields(subject, ("type", "entity", "digest"))
    need(text(subject["type"]) and subject["type"] in {"change", "adr", "reference", "prototype"}
         and text(subject["entity"]) and subject["entity"] == record["entity"],
         "INVALID_INPUT", "Invalid rejection subject", exit_code=2)
    fingerprint(subject["digest"])
    if subject["type"] == "change":
        identifier(subject["entity"], "CHG")
    if subject["type"] == "adr":
        need(re.fullmatch(r"ADR-[0-9]{3,}", subject["entity"]) is not None, "INVALID_INPUT", "Invalid ADR subject", exit_code=2)
    if "addresses" in record:
        addresses(record["addresses"])
    if record["kind"] == "checkpoint":
        need(subject["type"] == "prototype" and text(record.get("outcome")) and record["outcome"] in {"approved", "rejected"},
             "INVALID_INPUT", "Invalid prototype checkpoint", exit_code=2)
        return
    need(text(record.get("consequence")) and record["consequence"] in {"revise", "cancel", "defer"}, "INVALID_INPUT", "Invalid rejection consequence", exit_code=2)
    corrections(record.get("corrections"), record["consequence"])
    criteria(record.get("criteria", []))
    need((record["consequence"] == "defer") == ("fut" in record), "INVALID_INPUT", "Only defer requires a FUT", exit_code=2)
    if "fut" in record:
        identifier(record["fut"], "FUT")
    files = record.get("files")
    need(isinstance(files, dict) and bool(files), "INVALID_INPUT", "Rejection requires frozen files", exit_code=2)
    for path, pin in files.items():
        need(text(path), "INVALID_INPUT", "Frozen file path is required", exit_code=2)
        fingerprint(pin)


class Rejections:
    def __init__(self, kernel):
        self.k = kernel

    def subject(self, kind, entity):
        need(kind in {"change", "adr", "reference", "prototype"}, "INVALID_INPUT", "Unknown rejection subject", exit_code=2)
        if kind == "change":
            record, files, _ = self.k.change(entity)
            return record["proposal_digest"], {p: self.k.store.path(f".roclec/changes/{entity}/{p}").read_bytes() for p in files}
        if kind in {"adr", "reference"}:
            ref = self.k.references().get(entity)
            need(ref is not None and (ref["role"] == "decision") == (kind == "adr"), "INVALID_REFERENCE", "Unknown subject reference", entity=entity)
            path = ref["path"]
        else:
            path = entity
        source = self.k.store.path(path)
        need(source.is_file() and bool(source.read_bytes()), "INVALID_REFERENCE", "Subject source is missing or empty", path=path)
        data = source.read_bytes()
        return sha(data), {"content": data}

    def root(self, subject):
        # Paths are derived from a safe hash for reference and prototype identities.
        base = (f".roclec/changes/{subject['entity']}" if subject["type"] == "change" else
                f".roclec/subjects/{subject['type']}/{digest(subject['entity'])}")
        return f"{base}/rejected/{subject['digest']}"

    def records(self, kind, entity):
        return [d for d in self.k.decisions(entity) if d["kind"] == "rejection" and d["subject"]["type"] == kind]

    def revising(self, entity):
        decisions = self.k.decisions(entity)
        rejected = [d for d in decisions if d["kind"] == "rejection" and d["subject"]["type"] == "change"]
        if any(d["kind"] == "change-cancel" for d in decisions) or not rejected or rejected[-1]["consequence"] != "revise":
            return False
        index = decisions.index(rejected[-1])
        return not any(d["kind"] in {"change-approve", "change-cancel"} for d in decisions[index + 1:])

    def withdrawn(self, kind, entity):
        need(not any(d["consequence"] == "cancel" for d in self.records(kind, entity)), "SUBJECT_WITHDRAWN",
             "Withdrawn subjects require a new identity", entity=entity)

    def require_addresses(self, kind, entity, pin, value):
        self.withdrawn(kind, entity)
        previous = [d for d in self.records(kind, entity) if d["consequence"] == "revise"]
        if value is not None:
            addresses(value)
        if not previous:
            need(value is None, "INVALID_REFERENCE", "Correction responses cite no prior rejection", entity=entity)
            return
        latest = previous[-1]
        need(pin != latest["subject"]["digest"], "REJECTION_UNRESOLVED", "A rejected subject requires a new revision", entity=entity)
        expected = {r["id"] for r in latest["corrections"]}
        need(value is not None and value["rejection"] == latest["id"]
             and {r["id"] for r in value["corrections"]} == expected,
             "CORRECTIONS_REQUIRED", "Declare every correction from the latest rejection", entity=entity,
             expected={"rejection": latest["id"], "corrections": sorted(expected)})

    def history(self, kind, entity, *, value=None, pin=None, decisions=None):
        records = self.k.decisions(entity) if decisions is None else decisions
        revisions = []
        for d in records:
            if d["kind"] in {"foundation", "checkpoint", "change-approve", "rejection"} and d.get("addresses"):
                revisions.append({"digest": d.get("proposal_digest") or (d.get("subject") or {}).get("digest") or d.get("sources", {}).get(entity),
                                  "addresses": d["addresses"], "decision": d["id"]})
        if kind == "change":
            for record in records:
                if record["kind"] != "rejection" or record["subject"]["type"] != "change":
                    continue
                source = self.k.store.path(f"{self.root(record['subject'])}/change.json")
                need(source.is_file() and sha(source.read_bytes()) == record["files"].get("change.json"),
                     "HASH_MISMATCH", "Rejected proposal snapshot was modified", path=source)
                snapshot = read_json(source)
                response = snapshot.get("semantic", {}).get("addresses")
                if response is not None:
                    addresses(response)
                    revisions.append({"digest": record["subject"]["digest"], "addresses": response, "decision": record["id"]})
        if value is not None:
            revisions.append({"digest": pin, "addresses": value, "decision": None})
        result = []
        for record in records:
            if record["kind"] != "rejection" or record["subject"]["type"] != kind:
                continue
            linked = [r for r in revisions if r["addresses"]["rejection"] == record["id"]
                      and r["digest"] != record["subject"]["digest"]]
            resolved = next((r for r in reversed(linked) if {x["id"] for x in r["addresses"]["corrections"]}
                             == {x["id"] for x in record["corrections"]}), None)
            later = records[records.index(record) + 1:]
            superseding = next((d for d in later if d["kind"] == "rejection" and d["subject"]["type"] == kind), None)
            superseded_by = superseding["id"] if resolved is None and superseding is not None else None
            result.append({**record, "revision": resolved, "superseded_by": superseded_by,
                           "open": record["consequence"] == "revise" and resolved is None and superseded_by is None})
        return result

    def state(self, kind, entity, pin, *, approved=False, decisions=None):
        decisions = self.k.decisions(entity) if decisions is None else [d for d in decisions if d["entity"] == entity]
        records = [d for d in decisions if d["kind"] == "rejection" and d["subject"]["type"] == kind]
        if any(d["consequence"] == "cancel" for d in records):
            return "withdrawn"
        relevant = [d for d in records if d["subject"]["digest"] == pin]
        if relevant:
            rejection_index = decisions.index(relevant[-1])
            accepting_kind = {"change": "change-approve", "adr": "foundation", "reference": "foundation", "prototype": "checkpoint"}[kind]
            accepted = any(d["kind"] == accepting_kind
                           and d.get("outcome", "approved") != "rejected"
                           and (d.get("proposal_digest") or d.get("subject", {}).get("digest") or d.get("sources", {}).get(entity)) == pin
                           for d in decisions[rejection_index + 1:])
            if not accepted:
                return "rejected"
        if approved:
            return "approved"
        if records:
            return "revised"
        return "draft"

    def check(self):
        records = self.k.decisions()
        preceding = {}
        for record in records:
            chain = self.k._decision_chain(record)
            previous = preceding.get(chain)
            if record["kind"] == "checkpoint" and record["outcome"] == "rejected":
                need(previous is not None and previous["kind"] == "rejection"
                     and previous["id"] == record.get("rejection") and previous["subject"] == record["subject"],
                     "INVALID_REFERENCE", "Rejected checkpoint must follow its rejection", entity=record["id"])
            if previous is not None and previous["kind"] == "rejection":
                subject = previous["subject"]
                if subject["type"] == "change" and previous["consequence"] == "cancel":
                    need(record["kind"] == "change-cancel" and record["proposal_digest"] == subject["digest"],
                         "INVALID_REFERENCE", "Cancel rejection must be paired with change cancellation", entity=previous["id"])
                if subject["type"] == "prototype":
                    need(record["kind"] == "checkpoint" and record["outcome"] == "rejected"
                         and record.get("rejection") == previous["id"], "INVALID_REFERENCE",
                         "Prototype rejection must be paired with a rejected checkpoint", entity=previous["id"])
            approval = record["kind"] in {"change-approve", "foundation", "checkpoint"} and record.get("outcome") != "rejected"
            response = record["kind"] == "rejection" and "addresses" in record
            if approval or response:
                kind = (record["subject"]["type"] if response else "change" if record["kind"] == "change-approve"
                        else "prototype" if record["kind"] == "checkpoint"
                        else "adr" if re.fullmatch(r"ADR-[0-9]{3,}", record["entity"]) else "reference")
                rejected = [d for d in records[:records.index(record)] if d["kind"] == "rejection"
                            and d["entity"] == record["entity"] and d["subject"]["type"] == kind]
                need(not any(d["consequence"] == "cancel" for d in rejected), "SUBJECT_WITHDRAWN",
                     "Withdrawn subjects cannot be approved", entity=record["entity"])
                pending = [d for d in rejected if d["consequence"] == "revise"]
                value = record.get("addresses")
                need(value is None or bool(pending), "INVALID_REFERENCE", "Correction responses cite no prior rejection", entity=record["id"])
                if pending:
                    latest = pending[-1]
                    pin = record.get("proposal_digest") or record.get("subject", {}).get("digest") or record.get("sources", {}).get(record["entity"])
                    need(value is not None and value["rejection"] == latest["id"] and pin != latest["subject"]["digest"]
                         and {r["id"] for r in value["corrections"]} == {r["id"] for r in latest["corrections"]},
                         "CORRECTIONS_REQUIRED", "Approval must address the preceding rejection", entity=record["id"])
            preceding[chain] = record
        for record in records:
            if record["kind"] == "rejection" and (record["subject"]["type"] == "prototype"
                or (record["subject"]["type"] == "change" and record["consequence"] == "cancel")):
                need(any(d["previous"] == record["id"] and self.k._decision_chain(d) == self.k._decision_chain(record) for d in records),
                     "INVALID_REFERENCE", "Rejection is missing its paired decision", entity=record["id"])

            if record["kind"] != "rejection":
                continue
            if "fut" in record:
                self.k.inspect_fut(record["fut"])
            root = self.root(record["subject"])
            folder = self.k.store.path(root)
            actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
            need(actual == set(record["files"]), "HASH_MISMATCH", "Rejected snapshot file set changed", path=root)
            for path, pin in record["files"].items():
                source = self.k.store.path(f"{root}/{path}")
                need(source.is_file() and sha(source.read_bytes()) == pin, "HASH_MISMATCH", "Rejected snapshot was modified", path=f"{root}/{path}")
            if record["subject"]["type"] == "change":
                change = read_json(self.k.store.path(f"{root}/change.json"))
                need(change.get("id") == record["entity"] and change.get("proposal_digest") == record["subject"]["digest"]
                     and digest({k: change[k] for k in ("id", "kind", "semantic")}) == record["subject"]["digest"],
                     "HASH_MISMATCH", "Rejected proposal digest differs from its subject", path=root)
            else:
                need(record["files"] == {"content": record["subject"]["digest"]}, "HASH_MISMATCH",
                     "Frozen bytes differ from the rejected subject fingerprint", path=root)
