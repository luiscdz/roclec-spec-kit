"""Guarded local record writes, with receipts and recoverable journals."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import tempfile

from .model import ModelError, digest, encoded, fingerprint, local_path, need, read_json, sha


class Store:
    def __init__(self, root: Path):
        self.root = root

    def path(self, relative):
        return local_path(self.root, relative)

    def inputs(self):
        files = {}
        ignore = self.path(".gitignore")
        files[".gitignore"] = sha(ignore.read_bytes()) if ignore.is_file() else None
        directory = self.path(".roclec")
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                relative = path.relative_to(self.root).as_posix()
                if relative.startswith(".roclec/runtime/"):
                    continue
                self.path(relative)
                if path.is_file():
                    files[relative] = sha(path.read_bytes())
            references = self.path(".roclec/references.json")
            if references.exists():
                data = read_json(references)
                if isinstance(data, dict) and isinstance(data.get("references"), list):
                    for ref in data["references"]:
                        if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                            path = self.path(ref["path"])
                            files[ref["path"]] = sha(path.read_bytes()) if path.is_file() else None
        views = self.path("specs/capabilities")
        if views.exists():
            for path in sorted(views.glob("*.md")):
                relative = path.relative_to(self.root).as_posix()
                self.path(relative)
                files[relative] = sha(path.read_bytes())
        managed = ["AGENTS.md", "CLAUDE.md", ".specify", ".codex"]
        for pattern in (".agents/skills/roclec-*", ".claude/skills/roclec-*", ".agents/skills/speckit-*", ".claude/skills/speckit-*", ".claude/commands/speckit*"):
            managed.extend(p.relative_to(self.root).as_posix() for p in self.root.glob(pattern))
        for name in managed:
            path = self.path(name)
            paths = path.rglob("*") if path.is_dir() else [path]
            for item in paths:
                relative = item.relative_to(self.root).as_posix()
                self.path(relative)
                if item.is_file():
                    files[relative] = sha(item.read_bytes())
        return files

    def token(self):
        return digest(self.inputs())

    def healthy(self, *, locked=False):
        runtime = self.path(".roclec/runtime")
        need(locked or not self.path(".roclec/runtime/lock").exists(), "OPERATION_CONFLICT",
             "Another local operation owns the project lock", exit_code=3)
        if runtime.exists():
            pending = sorted(runtime.glob("*.json"))
            if pending:
                error = ModelError("IO_PARTIAL", "Recover the pending operation before continuing", exit_code=4,
                                   entity=pending[0].stem, remediation=f"operation recover {pending[0].stem}")
                error.operation_id, error.partial = pending[0].stem, True
                raise error

    def _atomic(self, relative, content):
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        handle, temporary = tempfile.mkstemp(prefix=".roclec-write-", dir=path.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            self.path(relative)  # Recheck ancestors immediately before replacement.
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _allowed(self, kind, payload, paths):
        roots = {
            "init": (".roclec/project.toml", ".roclec/current.json", ".roclec/references.json", ".roclec/identities.json", ".gitignore"),
            "change-new": (f".roclec/changes/{payload.get('id')}/", ".roclec/identities.json"),
            "change-approve": (f".roclec/changes/{payload.get('id')}/revisions/", ".roclec/decisions/", ".roclec/identities.json"),
            "change-start": (".roclec/decisions/",),
            "change-cancel": (".roclec/decisions/",),
            "fut-capture": (f".roclec/futs/{payload.get('id')}.json",),
            "fut-decide": (".roclec/decisions/",),
            "release-plan": (f".roclec/releases/{payload.get('component')}/{payload.get('version')}/release.json",),
            "views": ("specs/capabilities/",),
            "run-verify": (f".roclec/runs/{payload.get('id')}/",),
            "run-start": (f".roclec/runs/{payload.get('id')}/start.json",),
            "evidence-record": (f".roclec/evidence/{payload.get('id')}.json",),
            "review-policy": (".roclec/decisions/",),
            "integrate": (".roclec/contracts/", ".roclec/current.json", ".roclec/integrations/"),
            "release-prepare": (f".roclec/releases/{payload.get('component')}/{payload.get('version')}/preparations/",),
            "release-record": (f".roclec/releases/{payload.get('component')}/{payload.get('version')}/publication.json",),
            "skills-install": (".agents/skills/", ".claude/skills/", ".claude/commands/", ".codex/", ".specify/",
                               "AGENTS.md", "CLAUDE.md", ".gitignore", ".roclec/workflow.md", ".roclec/model.md", ".roclec/run", ".roclec/templates/",
                               ".roclec/constitution.md", ".roclec/notices/", ".roclec/link.toml", ".roclec/installation.json"),
        }
        need(kind in roots and bool(paths), "OPERATION_CONFLICT", "Unsupported write operation", exit_code=3)
        for relative in paths:
            path = self.path(relative)
            need(not path.exists() or path.is_file(), "UNMANAGED_FILE", "Write target is not a file", path=relative)
            need(any(relative.startswith(r) if r.endswith("/") else relative == r for r in roots[kind]),
                 "OPERATION_CONFLICT", "Write is outside this operation's namespace", exit_code=3, path=relative)

    def _lock(self):
        runtime = self.path(".roclec/runtime")
        runtime.mkdir(parents=True, exist_ok=True)
        lock = self.path(".roclec/runtime/lock")
        try:
            lock.mkdir()
        except FileExistsError as exc:
            raise ModelError("OPERATION_CONFLICT", "Another local operation owns the project lock",
                             exit_code=3, remediation="Wait for the operation; inspect runtime before removing a stale lock.") from exc
        return lock

    def apply(self, kind, payload, writes: dict[str, bytes], expected_token: str, *, validate=None, plan=None):
        self._allowed(kind, payload, writes)
        operation_id = digest({"kind": kind, "payload": payload, "writes": {p: sha(b) for p, b in sorted(writes.items())}})
        if plan is not None:
            operation_id = plan["operation_id"]
            need(operation_id == digest({k: v for k, v in plan.items() if k != "operation_id"}),
                 "OPERATION_CONFLICT", "Plan digest mismatch", exit_code=3)
        receipt_path = f".roclec/receipts/{operation_id}.json"
        self.path(receipt_path)
        lock = self._lock()
        try:
            self.healthy(locked=True)
            if self.path(receipt_path).is_file():
                receipt = read_json(self.path(receipt_path))
                need(all(self.path(p).is_file() and sha(self.path(p).read_bytes()) == h
                         for p, h in receipt["writes"].items()), "OPERATION_CONFLICT",
                     "Operation was applied, but later edits diverged; refusing to replay", exit_code=3)
                return receipt
            need(self.token() == expected_token, "BASE_CONFLICT", "Project inputs changed during validation", exit_code=3)
            if validate:
                validate()
            before = {p: sha(self.path(p).read_bytes()) if self.path(p).exists() else None for p in writes}
            guard = {p: h for p, h in self.inputs().items() if p not in writes and p != receipt_path}
            journal = {"model_schema": 1, "operation_id": operation_id, "kind": kind, "payload": payload,
                       "before": before, "guard": guard,
                       "writes": {p: base64.b64encode(b).decode("ascii") for p, b in writes.items()}}
            if plan is not None:
                journal["plan"] = plan
            journal["journal_digest"] = digest(journal)
            self._atomic(f".roclec/runtime/{operation_id}.json", encoded(journal))
            return self._finish(journal)
        finally:
            lock.rmdir()

    def _finish(self, journal):
        need(journal.get("journal_digest") == digest({k: v for k, v in journal.items() if k != "journal_digest"}),
             "OPERATION_CONFLICT", "Journal digest mismatch", exit_code=3)
        operation_id = journal["operation_id"]
        writes = {p: base64.b64decode(b, validate=True) for p, b in journal["writes"].items()}
        self._allowed(journal["kind"], journal["payload"], writes)
        expected_id = digest({"kind": journal["kind"], "payload": journal["payload"],
                              "writes": {p: sha(b) for p, b in sorted(writes.items())}})
        if "plan" in journal:
            plan = journal["plan"]
            expected_id = digest({k: v for k, v in plan.items() if k != "operation_id"})
            need(plan["operation_id"] == expected_id and plan["kind"] == journal["kind"]
                 and plan["writes"] == {p: sha(b) for p, b in writes.items()},
                 "OPERATION_CONFLICT", "Journal differs from its prepared plan", exit_code=3)
        need(expected_id == operation_id and journal["before"].keys() == writes.keys(),
             "OPERATION_CONFLICT", "Journal integrity mismatch", exit_code=3)
        receipt_path = f".roclec/receipts/{operation_id}.json"
        guard = {p: h for p, h in self.inputs().items() if p not in writes and p != receipt_path}
        need(guard == journal["guard"], "OPERATION_CONFLICT",
             "Other project inputs changed since the operation was prepared", exit_code=3)
        if journal["kind"] == "integrate":
            from .config import load_profile
            from .kernel import Kernel
            from .verification import Verification
            payload = journal["payload"]
            try:
                actual = Verification(Kernel(load_profile(self.root), allow_pending=True)).candidate(
                    payload["change_id"], payload["component"], payload["candidate"]["base"])
            except ModelError as exc:
                raise ModelError("OPERATION_CONFLICT", "Code candidate cannot be reconstructed during recovery",
                                 exit_code=3, actual=exc.issue) from exc
            need(actual["inputs_digest"] == payload["candidate"]["inputs_digest"]
                 and actual["head"] == payload["candidate"]["head"], "OPERATION_CONFLICT",
                 "Code candidate diverged during integration; resolve before recovery", exit_code=3)
        if journal["kind"] in {"release-prepare", "release-record"}:
            from .config import load_profile
            from .kernel import Kernel
            from .releases import Releases
            try:
                Releases(Kernel(load_profile(self.root), allow_pending=True)).recovery_guard(journal["payload"])
            except ModelError as exc:
                raise ModelError("OPERATION_CONFLICT", "Release candidate or remote diverged during recovery", exit_code=3, actual=exc.issue) from exc
        # Validate every destination before completing any interrupted write.
        for relative, content in writes.items():
            path = self.path(relative)
            current = sha(path.read_bytes()) if path.exists() else None
            need(current in (journal["before"][relative], sha(content)), "OPERATION_CONFLICT",
                 "A journal destination diverged; manual resolution required", exit_code=3, path=relative)
        try:
            for relative, content in writes.items():
                path = self.path(relative)
                if not path.exists() or sha(path.read_bytes()) != sha(content):
                    self._atomic(relative, content)
                if journal["kind"] == "skills-install" and relative == ".roclec/run":
                    os.chmod(path, 0o755)
            receipt = {"model_schema": 1, "operation_id": operation_id, "kind": journal["kind"],
                       "payload": journal["payload"], "writes": {p: sha(b) for p, b in writes.items()}}
            self._atomic(f".roclec/receipts/{operation_id}.json", encoded(receipt))
            self.path(f".roclec/runtime/{operation_id}.json").unlink()
            return receipt
        except OSError as exc:
            error = ModelError("IO_PARTIAL", "Operation interrupted; recover using its journal", exit_code=4,
                               entity=operation_id, remediation=f"operation recover {operation_id}")
            error.operation_id, error.partial = operation_id, True
            raise error from exc

    def recover(self, operation_id):
        fingerprint(operation_id)
        lock = self._lock()
        try:
            journal_path = self.path(f".roclec/runtime/{operation_id}.json")
            receipt_path = self.path(f".roclec/receipts/{operation_id}.json")
            if not journal_path.exists():
                need(receipt_path.is_file(), "INVALID_REFERENCE", "Unknown operation", entity=operation_id)
                return read_json(receipt_path)
            journal = read_json(journal_path)
            need(journal.get("operation_id") == operation_id, "OPERATION_CONFLICT", "Journal identity mismatch", exit_code=3)
            return self._finish(journal)
        finally:
            lock.rmdir()
