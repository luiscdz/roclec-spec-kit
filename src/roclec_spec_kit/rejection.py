"""Human rejection records, immutable source copies and correction links.

Stage checkpoints (hooks pre-implement, pre-integrate and handoff on a change component) are
``checkpoint`` decisions with subject type ``stage``: the approval and the rejection are the same
record (``outcome``), they carry their own corrections/consequence and never pair with a
``rejection`` record or a frozen copy, because their subjects are already immutable records.
"""
import re

from .flow import HOOKS
from .model import digest, fields, fingerprint, identifier, need, read_json, sha, text

STAGE_FIELDS = ("model_schema", "id", "kind", "entity", "previous", "actor", "reason", "subject", "hook", "component",
                "outcome", "criteria", "flow")
STAGE_OPTIONAL = ("run", "consequence", "corrections", "fut", "addresses", "sessions")


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


def evaluations(value, *, approved):
    """Shape of recorded criteria evaluations; never re-evaluated against the current flow."""
    need(isinstance(value, (list, tuple)), "INVALID_INPUT", "Criteria must be a list", exit_code=2)
    ids = []
    for row in value:
        fields(row, ("id", "status"), ("reason",))
        need(text(row["id"]) and text(row["status"]) and row["status"] in {"met", "not-met", "n/a"}, "INVALID_INPUT",
             "Invalid criterion evaluation", exit_code=2)
        need(row["status"] != "n/a" or text(row.get("reason")), "INVALID_INPUT", "n/a requires a reason", exit_code=2)
        need("reason" not in row or text(row["reason"]), "INVALID_INPUT", "Criterion reason must be nonempty", exit_code=2)
        ids.append(row["id"])
    need(len(ids) == len(set(ids)), "INVALID_INPUT", "Criterion evaluations need unique IDs", exit_code=2)
    failing = any(r["status"] == "not-met" for r in value)
    if approved:
        need(not failing, "INVALID_INPUT", "An approval cannot record a not-met criterion", exit_code=2)
    else:
        need(not value or failing, "INVALID_INPUT", "A rejection must cite a not-met criterion", exit_code=2)


def criteria(value):
    evaluations(value, approved=False)


def stage_key(record):
    return record["entity"], record["hook"], record["component"]


def is_stage(record):
    return record["kind"] == "checkpoint" and record["subject"]["type"] == "stage"


def validate_stage(record):
    fields(record, STAGE_FIELDS, STAGE_OPTIONAL)
    identifier(record["entity"], "CHG")
    need(isinstance(record["hook"], str) and record["hook"] in HOOKS and text(record["component"])
         and isinstance(record["outcome"], str) and record["outcome"] in {"approved", "rejected"},
         "INVALID_INPUT", "Invalid stage checkpoint", exit_code=2)
    need(("run" in record) == (record["hook"] == "pre-integrate"), "INVALID_INPUT",
         "Only a pre-integrate checkpoint names its run", exit_code=2)
    if "run" in record:
        identifier(record["run"], "RUN")
    fingerprint(record["flow"])
    approved = record["outcome"] == "approved"
    evaluations(record["criteria"], approved=approved)
    if approved:
        need(not {"consequence", "corrections", "fut"} & record.keys(), "INVALID_INPUT",
             "An approved checkpoint has no rejection details", exit_code=2)
        return
    need(isinstance(record.get("consequence"), str) and record["consequence"] in {"revise", "cancel", "defer"},
         "INVALID_INPUT", "Invalid rejection consequence", exit_code=2)
    corrections(record.get("corrections"), record["consequence"])
    need((record["consequence"] == "defer") == ("fut" in record), "INVALID_INPUT", "Only defer requires a FUT", exit_code=2)
    if "fut" in record:
        identifier(record["fut"], "FUT")


def validate_decision(record):
    subject = record.get("subject")
    fields(subject, ("type", "entity", "digest"))
    types = {"prototype", "stage"} if record["kind"] == "checkpoint" else {"change", "adr", "reference", "prototype"}
    need(text(subject["type"]) and subject["type"] in types
         and text(subject["entity"]) and subject["entity"] == record["entity"],
         "INVALID_INPUT", "Invalid rejection subject", exit_code=2)
    fingerprint(subject["digest"])
    if subject["type"] in {"change", "stage"}:
        identifier(subject["entity"], "CHG")
    if subject["type"] == "adr":
        need(re.fullmatch(r"ADR-[0-9]{3,}", subject["entity"]) is not None, "INVALID_INPUT", "Invalid ADR subject", exit_code=2)
    if "addresses" in record:
        addresses(record["addresses"])
    if subject["type"] == "stage":
        validate_stage(record)
        return
    need(not {"hook", "run"} & record.keys(), "INVALID_INPUT", "Only stage checkpoints name a hook or run", exit_code=2)
    if record["kind"] == "checkpoint":
        need(text(record.get("outcome")) and record["outcome"] in {"approved", "rejected"},
             "INVALID_INPUT", "Invalid prototype checkpoint", exit_code=2)
        if "criteria" in record:
            evaluations(record["criteria"], approved=record["outcome"] == "approved")
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

    @staticmethod
    def require_stage(prior, pin, value, *, approving, entity):
        """FX correction rules for one hook/component; `prior` are its earlier rejected checkpoints, in order."""
        if value is not None:
            addresses(value)
        need(not any(d["consequence"] == "cancel" for d in prior), "SUBJECT_WITHDRAWN",
             "A canceled stage cannot be decided again", entity=entity)
        pending = [d for d in prior if d["consequence"] == "revise"]
        need(value is None or bool(pending), "INVALID_REFERENCE", "Correction responses cite no prior rejection", entity=entity)
        need(not approving or pin not in {d["subject"]["digest"] for d in pending}, "REJECTION_UNRESOLVED",
             "This exact subject was rejected for revision; approve a new revision", entity=entity, actual=pin)
        if not pending or (value is None and not approving):
            return
        latest = pending[-1]
        expected = {r["id"] for r in latest["corrections"]}
        need(pin != latest["subject"]["digest"], "REJECTION_UNRESOLVED", "A rejected subject requires a new revision", entity=entity)
        need(value is not None and value["rejection"] == latest["id"] and {r["id"] for r in value["corrections"]} == expected,
             "CORRECTIONS_REQUIRED", "Declare every correction from the latest rejection", entity=entity,
             expected={"rejection": latest["id"], "corrections": sorted(expected)})

    def stage_history(self, entity, *, decisions=None):
        """Rejected stage checkpoints of a change with their revision, supersession and open state."""
        records = [d for d in (self.k.decisions(entity) if decisions is None else decisions)
                   if d["entity"] == entity and is_stage(d)]
        result = []
        for index, record in enumerate(records):
            if record["outcome"] != "rejected":
                continue
            later = [d for d in records[index + 1:] if stage_key(d) == stage_key(record)]
            linked = [d for d in later if (d.get("addresses") or {}).get("rejection") == record["id"]
                      and d["subject"]["digest"] != record["subject"]["digest"]
                      and {x["id"] for x in d["addresses"]["corrections"]} == {x["id"] for x in record["corrections"]}]
            resolved = linked[-1] if linked else None
            revision = {"digest": resolved["subject"]["digest"], "addresses": resolved["addresses"],
                        "decision": resolved["id"]} if resolved else None
            superseding = next((d for d in later if d["outcome"] == "rejected"), None)
            superseded_by = superseding["id"] if revision is None and superseding is not None else None
            result.append({**record, "revision": revision, "superseded_by": superseded_by,
                           "open": record["consequence"] == "revise" and revision is None and superseded_by is None})
        return result

    def history(self, kind, entity, *, value=None, pin=None, decisions=None):
        records = self.k.decisions(entity) if decisions is None else decisions
        revisions = []
        for d in records:
            if d["kind"] in {"foundation", "checkpoint", "change-approve", "rejection"} and d.get("addresses") and not is_stage(d):
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
            accepted = any(d["kind"] == accepting_kind and not (d["kind"] == "checkpoint" and is_stage(d))
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
            if is_stage(record):
                # Hook checkpoints have their own chain per change component, in decision order.
                prior = [d for d in records[:records.index(record)] if is_stage(d) and d["outcome"] == "rejected"
                         and stage_key(d) == stage_key(record)]
                approving = record["outcome"] == "approved"
                if approving or "addresses" in record:
                    self.require_stage(prior, record["subject"]["digest"], record.get("addresses"),
                                       approving=approving, entity=record["id"])
                preceding[chain] = record
                continue
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
            if is_stage(record) and record["outcome"] == "rejected":
                if "fut" in record:
                    self.k.inspect_fut(record["fut"])
                need(record["consequence"] != "cancel" or any(
                    d["kind"] == "change-cancel" and d["entity"] == record["entity"] and record["component"] in d["components"]
                    for d in records), "INVALID_REFERENCE", "Canceling stage rejection lacks its change cancellation", entity=record["id"])
                continue
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
