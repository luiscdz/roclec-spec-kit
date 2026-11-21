"""Consumer architecture decision records (ADR), read through the kernel.

An ADR is consumer Markdown registered as a reference with role ``decision``.
Its state is derived from references.json, foundation agreements and the file
bytes; nothing in this module writes. Changes declare the ADRs they apply in
``semantic.architecture_decisions`` and pin their bytes at approval.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
import re

from .model import ModelError, fields, fingerprint, need, sha, strings, text

ADR_ID = r"ADR-[0-9]{3,}"
# Derived states in rule order (first match wins, see Adrs.view); later lifecycle
# states such as rejected or withdrawn are inserted where they belong.
STATES = ("superseded", "proposed", "stale", "accepted")
PENDING = ("proposed", "stale")
DECLARE = ('Add "architecture_decisions" to the change semantic as {"adrs": [{"id": "ADR-NNN"}]} or '
           '{"none": "reason"}, then seal the bundle again and approve the new proposal digest.')
REPIN = ("Pin the current ADR bytes again (remove the entry's sha256 and run change seal, which fills it), "
         "then approve the new proposal digest.")
SUPERSESSION = "Declare only other registered ADRs in supersedes, without cycles, using reference update ADR-NNN --supersedes."


def is_adr(value):
    return isinstance(value, str) and re.fullmatch(ADR_ID, value) is not None


def adr_ids(values):
    """A sorted, unique list of ADR IDs (``supersedes``)."""
    strings(values)
    need(all(is_adr(v) for v in values), "INVALID_INPUT", "supersedes must list ADR-NNN IDs", exit_code=2, actual=values,
         remediation=SUPERSESSION)
    return values


def in_folder(path, folder):
    """A Markdown file strictly inside the configured ADR folder."""
    parts, base = PurePosixPath(path).parts, PurePosixPath(folder).parts
    return path.endswith(".md") and len(parts) > len(base) and parts[:len(base)] == base


def declaration(value, *, sealed=True):
    """``{"adrs": [{id, sha256}, ...]}`` (sorted by ID) or ``{"none": reason}``; unsealed entries may omit sha256."""
    need(isinstance(value, dict) and len(value) == 1 and set(value) <= {"adrs", "none"}, "INVALID_INPUT",
         "architecture_decisions needs exactly one of adrs or none", exit_code=2,
         actual=sorted(value) if isinstance(value, dict) else value, remediation=DECLARE)
    if "none" in value:
        need(text(value["none"]), "INVALID_INPUT", "Declaring no ADR needs a non-empty reason", exit_code=2, remediation=DECLARE)
        return value
    entries = value["adrs"]
    need(isinstance(entries, list) and bool(entries), "INVALID_INPUT",
         "architecture_decisions.adrs must list at least one ADR; use none with a reason otherwise", exit_code=2,
         remediation=DECLARE)
    for entry in entries:
        fields(entry, ("id", "sha256") if sealed else ("id",), () if sealed else ("sha256",))
        need(is_adr(entry["id"]), "INVALID_INPUT", "Cited ADR needs an ADR-NNN ID", exit_code=2, actual=entry["id"])
        if "sha256" in entry:
            fingerprint(entry["sha256"])
    ids = [entry["id"] for entry in entries]
    need(len(ids) == len(set(ids)) and (not sealed or ids == sorted(ids)), "INVALID_INPUT",
         "Cited ADRs must be unique and sorted by ID", exit_code=2, actual=ids)
    return value


def supersession(refs):
    """Every superseded ID is another registered ADR and the graph has no cycle."""
    decisions = {i: r for i, r in refs.items() if r["role"] == "decision"}
    for adr_id, ref in sorted(decisions.items()):
        for target in ref["supersedes"]:
            need(target != adr_id and target in decisions, "ADR_SUPERSESSION_INVALID",
                 "An ADR can supersede only another registered ADR", entity=adr_id, actual=target,
                 remediation=SUPERSESSION)
    done, active = set(), []

    def visit(adr_id):
        if adr_id in active:
            raise ModelError("ADR_SUPERSESSION_INVALID", "ADR supersession forms a cycle", entity=adr_id,
                             actual=active[active.index(adr_id):] + [adr_id], remediation=SUPERSESSION)
        if adr_id in done:
            return
        active.append(adr_id)
        for target in decisions[adr_id]["supersedes"]:
            visit(target)
        active.pop()
        done.add(adr_id)

    for adr_id in sorted(decisions):
        visit(adr_id)


def headings(markdown):
    """ATX headings as (level, title) outside fenced code blocks."""
    fence = None
    for line in markdown.splitlines():
        opener = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if fence:
            stripped = line.strip()
            if opener and set(stripped) == {fence[0]} and len(stripped) >= len(fence):
                fence = None
            continue
        if opener:
            fence = opener.group(1)
            continue
        heading = re.match(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$", line)
        if heading:
            title = re.sub(r"(?:^|[ \t]+)#+$", "", heading.group(2) or "").strip()
            yield len(heading.group(1)), title


class Adrs:
    def __init__(self, kernel):
        self.k = kernel

    def view(self):
        """Derived state per registered ADR, keyed and sorted by ID."""
        refs = {i: r for i, r in self.k.references().items() if r["role"] == "decision"}
        agreed = {d["id"]: d for d in self.k.decisions() if d["kind"] == "foundation" and is_adr(d["entity"])}
        agreements, current = {}, {}
        for adr_id, ref in refs.items():
            record = agreed.get(ref["decision_id"])
            agreements[adr_id] = None if record is None or record["entity"] != adr_id else {
                "decision_id": record["id"], "sha256": record["sources"][adr_id], "supersedes": record["supersedes"]}
            path = self.k.store.path(ref["path"])
            current[adr_id] = sha(path.read_bytes()) if path.is_file() else None
        # Only an agreement that itself records the supersession makes it effective.
        replaces, replaced_by = defaultdict(list), defaultdict(list)
        for adr_id, ref in refs.items():
            agreement = agreements[adr_id]
            for older in ref["supersedes"]:
                if agreement is not None and older in agreement["supersedes"]:
                    replaces[adr_id].append(older)
                    replaced_by[older].append(adr_id)
        result = {}
        for adr_id in sorted(refs):
            ref, agreement = refs[adr_id], agreements[adr_id]
            # One branch per entry of STATES, in order; a later state gets its own branch here.
            if replaced_by[adr_id]:
                state = "superseded"
            elif ref["decision_id"] is None:
                state = "proposed"
            elif (agreement is None or current[adr_id] != agreement["sha256"]
                  or agreement["supersedes"] != ref["supersedes"]):
                state = "stale"
            else:
                state = "accepted"
            result[adr_id] = {
                "id": adr_id, "path": ref["path"], "components": ref["components"], "state": state,
                "sha256": current[adr_id],
                "agreement": None if agreement is None else {k: agreement[k] for k in ("decision_id", "sha256")},
                "supersedes": ref["supersedes"], "superseded_by": sorted(replaced_by[adr_id]),
                "replaces": sorted(replaces[adr_id])}
        return result

    def get(self, adr_id, view=None):
        view = self.view() if view is None else view
        need(adr_id in view, "INVALID_REFERENCE", "Unknown ADR reference", entity=adr_id,
             remediation="Register it with reference add ADR-NNN --path FILE --component NAME --role decision.")
        return view[adr_id]

    def list(self):
        return [{k: entry[k] for k in ("id", "path", "components", "state", "supersedes", "superseded_by")}
                for entry in self.view().values()]

    def pending(self, component, view=None):
        view = self.view() if view is None else view
        return [{"id": e["id"], "state": e["state"]} for e in view.values()
                if component in e["components"] and e["state"] in PENDING]

    def inspect(self, adr_id):
        view = self.view()
        entry = self.get(adr_id, view)
        ref = self.k.references()[adr_id]

        def closure(key):
            found, pending = set(), list(view[adr_id][key])
            while pending:
                other = pending.pop()
                if other not in found:
                    found.add(other)
                    pending.extend(view[other][key])
            return sorted(found)

        changes = []
        for path in sorted(self.k.store.path(".roclec/changes").glob("*/change.json")):
            change_id = path.parent.name
            cited = self.citations(change_id, adr_id)
            status = self.k.inspect_change(change_id)["status"] if cited else None
            changes.extend({"id": change_id, "revision": revision, "integrated_components": components, "status": status,
                            "sha256": pin, "pin_current": pin == entry["sha256"]} for revision, components, pin in cited)
        return {"adr": ref, "state": entry["state"], "sha256": entry["sha256"], "agreement": entry["agreement"],
                "supersedes": entry["supersedes"], "superseded_by": entry["superseded_by"],
                "chain": {"replaces": closure("replaces"), "replaced_by": closure("superseded_by")}, "changes": changes}

    def citations(self, change_id, adr_id):
        """(revision, integrated components, pinned sha) for the current proposal and every integrated
        revision snapshot citing the ADR: integrated participants keep their historical citation."""
        def pin(record):
            value = record["semantic"].get("architecture_decisions") or {}
            return next((e["sha256"] for e in value.get("adrs", []) if e["id"] == adr_id), None)

        current, _, _ = self.k.change(change_id)
        integrated = defaultdict(list)
        directory = self.k.store.path(f".roclec/integrations/{change_id}")
        for folder in sorted(directory.iterdir()) if directory.is_dir() else []:
            record = self.k.integration(change_id, folder.name)
            if record is not None:
                integrated[record["proposal_digest"]].append(folder.name)
        pins = {current["proposal_digest"]: pin(current)}
        for revision in integrated:
            if revision not in pins:
                source = self.k.store.path(f".roclec/changes/{change_id}/revisions/{revision}")
                snapshot, _, _ = self.k.change(change_id, source=source, historical=True)
                pins[revision] = pin(snapshot)
        return [(revision, sorted(integrated.get(revision, [])), pins[revision])
                for revision in sorted(pins) if pins[revision] is not None]

    def declared(self, record):
        """The change's declaration with each cited ADR's derived state, or None when undeclared."""
        value = record["semantic"].get("architecture_decisions")
        if value is None or "none" in value:
            return value
        view = self.view()
        return {"adrs": [{"id": e["id"], "sha256": e["sha256"], "state": view[e["id"]]["state"] if e["id"] in view else None,
                          "pin_current": e["id"] in view and view[e["id"]]["sha256"] == e["sha256"]}
                         for e in value["adrs"]]}

    def approvable(self, record):
        """Approval requires the declaration and pins equal to the current ADR bytes (proposed ADRs allowed)."""
        value = record["semantic"].get("architecture_decisions")
        need(value is not None, "ADR_UNDECLARED", "The change does not declare its architecture decisions",
             entity=record["id"], remediation=DECLARE)
        if "adrs" not in value:
            return
        view = self.view()
        stale = [{"id": e["id"], "pinned": e["sha256"], "current": view[e["id"]]["sha256"]}
                 for e in value["adrs"] if view[e["id"]]["sha256"] != e["sha256"]]
        need(not stale, "ADR_PIN_STALE", "Pinned ADR bytes differ from the current ADR files", entity=record["id"],
             actual=stale, remediation=REPIN)

    def gate(self, record):
        """Implement/verify/integrate: every cited ADR is accepted with the pinned bytes."""
        value = record["semantic"].get("architecture_decisions")
        if value is None or "adrs" not in value:
            return
        view = self.view()
        failures = []
        for cited in value["adrs"]:
            entry = self.get(cited["id"], view)
            agreed = entry["agreement"]["sha256"] if entry["agreement"] else None
            if entry["state"] == "accepted" and cited["sha256"] == agreed:
                continue
            remediation = {
                "proposed": f"Ask the user to accept it with foundation agree --ref {cited['id']} --actor NAME --reason TEXT.",
                "stale": f"Re-agree the edited ADR with foundation agree --ref {cited['id']}, or restore its agreed content and supersedes.",
                "superseded": f"Cite the replacing ADR ({', '.join(entry['superseded_by'])}) in a new proposal revision and approve it again.",
                "accepted": REPIN,
            }[entry["state"]]
            failures.append({"id": cited["id"], "state": entry["state"], "pinned": cited["sha256"], "agreed": agreed,
                             "superseded_by": entry["superseded_by"], "remediation": remediation})
        if failures:
            code = "ADR_NOT_ACCEPTED" if any(f["state"] != "accepted" for f in failures) else "ADR_PIN_STALE"
            raise ModelError(code, "Cited ADRs must be accepted with the pinned content", entity=record["id"],
                             actual=failures, remediation=" ".join(dict.fromkeys(f["remediation"] for f in failures)))

    def superseded_citations(self, change, view=None):
        """Release limitations: ADRs an approved member applied that are now superseded."""
        value = change["semantic"].get("architecture_decisions") or {}
        if "adrs" not in value:
            return []
        view = self.view() if view is None else view
        return [{"code": "ADR_SUPERSEDED", "change_id": change["id"], "adr": e["id"],
                 "superseded_by": view[e["id"]]["superseded_by"]}
                for e in value["adrs"] if e["id"] in view and view[e["id"]]["state"] == "superseded"]

    def structure(self):
        """Non-blocking ADR_STRUCTURE warnings: location, required ## sections and >= 2 ### options."""
        config = self.k.profile.adr
        folder, sections, options = config["path"], config["required_sections"], config["options_section"]
        warnings = []

        def warn(entry, message, **context):
            issue = ModelError("ADR_STRUCTURE", message, entity=entry["id"], path=entry["path"], **context).issue
            warnings.append({**issue, "severity": "warning"})

        for entry in self.view().values():
            if not in_folder(entry["path"], folder):
                warn(entry, "ADR is not a Markdown file inside the configured ADR folder", expected=folder,
                     actual=entry["path"], remediation="Move the ADR under the [adr] path and update its reference.")
            path = self.k.store.path(entry["path"])
            if not path.is_file():
                warn(entry, "ADR file is missing", remediation="Restore the ADR file or update its reference path.")
                continue
            found = list(headings(path.read_bytes().decode("utf-8", "replace")))
            titles = {title.casefold() for level, title in found if level == 2}
            missing = [s for s in sections if s.casefold() not in titles]
            if missing:
                warn(entry, "ADR lacks required sections", expected=sections, actual=missing,
                     remediation="Add each missing ## section from .roclec/templates/adr-template.md, or adapt [adr] required_sections.")
            if options.casefold() in titles:
                inside, count = False, 0
                for level, title in found:
                    if level <= 2:
                        inside = level == 2 and title.casefold() == options.casefold()
                    elif level == 3 and inside:
                        count += 1
                if count < 2:
                    warn(entry, "ADR describes fewer than two considered options", expected=2, actual=count,
                         remediation=f"Describe at least two real options as ### subsections of ## {options}.")
        return warnings
