"""Bounded Markdown index for the viewer: files in a fixed reading scope plus normative snapshots.

Only ``docs/``, ``specs/`` and references declared by the project are readable.
Paths are validated, symlinks and oversized files are skipped, and ``.git``,
runtime state and raw logs can never enter the tree, the search or the API.
"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from ..model import ModelError, local_path
from .reader import ID_PATTERN, Reader, ViewerError, not_found, title_of

SCOPE_DIRECTORIES = ("docs", "specs")
MARKDOWN = {".md", ".markdown"}
IMAGES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
          ".webp": "image/webp", ".svg": "image/svg+xml"}
SKIPPED = {"node_modules", "__pycache__", "venv"}
MAX_DOCUMENT = 512 * 1024
MAX_ASSET = 5 * 1024 * 1024
MAX_RESULTS = 50


def snippet(text, needle, width=90):
    index = text.lower().find(needle.lower())
    if index < 0:
        return None
    start, end = max(0, index - width), min(len(text), index + len(needle) + width)
    return ("…" if start else "") + " ".join(text[start:end].split()) + ("…" if end < len(text) else "")


class DocsIndex:
    def __init__(self, reader: Reader):
        self.reader = reader
        self.root = reader.root
        self.files, self.excluded = self._files(), []
        self.entities = self._entities()

    # ---- Reading scope --------------------------------------------------

    def _declared(self):
        try:
            return {ref["path"]: ref for ref in self.reader.kernel.references().values()}
        except ModelError:
            return {}

    def _candidate_paths(self):
        found = {}
        for top in SCOPE_DIRECTORIES:
            base = self.root / top
            if not base.is_dir() or base.is_symlink():
                continue
            for folder, dirs, names in os.walk(base, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIPPED and not (Path(folder) / d).is_symlink())
                for name in sorted(names):
                    path = Path(folder) / name
                    if path.suffix.lower() in MARKDOWN:
                        found[path.relative_to(self.root).as_posix()] = top
        for relative in self._declared():
            if PurePosixPath(relative).suffix.lower() in MARKDOWN:
                found.setdefault(relative, "reference")
        return found

    def _files(self):
        result = {}
        for relative, source in sorted(self._candidate_paths().items()):
            try:
                path = local_path(self.root, relative)
                if not path.is_file() or path.stat().st_size > MAX_DOCUMENT:
                    continue
                text = path.read_text(encoding="utf-8")
            except (ModelError, OSError, UnicodeError):
                continue
            result[relative] = {"path": relative, "title": title_of(text, PurePosixPath(relative).stem), "size": len(text.encode()),
                                "source": source, "text": text}
        return result

    def scope_roots(self):
        """Directories whose documents may reference images and sibling files."""
        roots = {PurePosixPath(top) for top in SCOPE_DIRECTORIES}
        roots.update(PurePosixPath(relative).parent for relative in self._declared())
        return roots

    # ---- Normative snapshots -------------------------------------------

    def _entities(self):
        reader, found = self.reader, {}

        def add(cap, revision, descriptor, files, label, link):
            for req in descriptor["requirements"]:
                statement = files[req["statement"]].decode("utf-8")
                self._merge(found, "REQ", req["id"], cap, revision, req["components"], statement, label, link)
                for ac in descriptor["acceptance"]:
                    if ac["id"] in req["acceptance_ids"]:
                        self._merge(found, "AC", ac["id"], cap, revision, ac["components"], files[ac["scenario"]].decode("utf-8"),
                                    label, {**link, "req": req["id"]})

        try:
            current = reader.kernel.current()["components"]
        except ModelError:
            current = {}
        for component, capabilities in current.items():
            for cap, revision in capabilities.items():
                try:
                    descriptor, files = reader.kernel.contract(cap, revision)
                except ModelError:
                    continue
                add(cap, revision, descriptor, files, f"Contrato vigente · {component}", {"component": component})
        for entry in reader.releases():
            record, publication = entry["record"], entry["publication"]
            if publication:
                for cap, revision in publication["contracts"].items():
                    try:
                        descriptor, files = reader.kernel.contract(cap, revision)
                    except ModelError:
                        continue
                    add(cap, revision, descriptor, files, f"Release {record['component']} {record['version']}",
                        {"component": record["component"], "release": record["version"]})
        for path in sorted(reader.store.path(".roclec/changes").glob("*/revisions/*/change.json")):
            change_id, revision = path.parent.parent.parent.name, path.parent.name
            try:
                record, folder = reader.change_revision(change_id, revision)
                text = (folder / record["semantic"]["intention"]).read_text(encoding="utf-8")
            except (ModelError, ViewerError, OSError):
                continue
            self._merge(found, "CHG", change_id, None, revision, record["semantic"]["components"], text,
                        f"{change_id} · revisión {revision[:8]}", {"change": change_id, "intent": revision})
            for proposed in record["semantic"]["proposed"]:
                cap, contract_revision = proposed["capability_id"], proposed["revision"]
                try:
                    descriptor, files = reader.contract(cap, contract_revision, folder=folder / f"proposed/{cap}/{contract_revision}")
                except ViewerError:
                    continue
                add(cap, contract_revision, descriptor, files, f"{change_id} · propuesta aprobada",
                    {"change": change_id, "intent": revision, "component": proposed["components"][0]})
        return list(found.values())

    @staticmethod
    def _merge(found, kind, name, cap, revision, components, text, label, link):
        key = (kind, name, cap, revision)
        entry = found.setdefault(key, {"kind": kind, "id": name, "cap": cap, "revision": revision, "components": sorted(components),
                                       "title": title_of(text, name), "text": text, "contexts": [], "link": link})
        if label not in entry["contexts"]:
            entry["contexts"].append(label)

    # ---- Tree, documents, assets ----------------------------------------

    def tree(self):
        root = {"name": "", "path": "", "type": "dir", "children": []}
        for relative, info in self.files.items():
            node, parts = root, PurePosixPath(relative).parts
            for depth, part in enumerate(parts[:-1]):
                folder = next((c for c in node["children"] if c["type"] == "dir" and c["name"] == part), None)
                if folder is None:
                    folder = {"name": part, "path": "/".join(parts[:depth + 1]), "type": "dir", "children": []}
                    node["children"].append(folder)
                node = folder
            node["children"].append({"name": parts[-1], "path": relative, "type": "file", "title": info["title"], "size": info["size"]})
        return root

    def document(self, relative):
        info = self.files.get(relative)
        if info is None:
            raise not_found("Document is outside the reading scope", entity=relative)
        return {"path": relative, "title": info["title"], "size": info["size"], "source": info["source"], "content": info["text"]}

    def asset(self, relative):
        """Validated image path for a document, or ``ViewerError``."""
        suffix = PurePosixPath(relative).suffix.lower()
        try:
            path = local_path(self.root, relative)
        except ModelError as exc:
            raise not_found("Asset is outside the reading scope", entity=relative) from exc
        parent = PurePosixPath(relative).parent
        in_scope = any(parent == scope or scope in parent.parents for scope in self.scope_roots() if str(scope) != ".")
        if suffix not in IMAGES or not in_scope or not path.is_file():
            raise not_found("Asset is outside the reading scope", entity=relative)
        if path.stat().st_size > MAX_ASSET:
            raise ViewerError("not_found", "TOO_LARGE", "Asset exceeds the viewer size limit", status=413, entity=relative)
        return path, IMAGES[suffix]

    # ---- Search ---------------------------------------------------------

    def search(self, query):
        query = (query or "").strip()
        if not query:
            return {"query": "", "results": []}
        if len(query) > 200:
            raise ViewerError("invalid_query", "INVALID_INPUT", "Query is too long", status=400)
        lowered = query.lower()
        results = []
        exact = ID_PATTERN.fullmatch(query.upper()) is not None
        if exact:
            wanted = query.upper()
            for entity in self.entities:
                if entity["id"] == wanted:
                    results.append(self._entity_result(entity, 1000, None))
            for info in self.files.values():
                if wanted in info["text"].upper():
                    results.append(self._doc_result(info, 900, snippet(info["text"], wanted)))
        else:
            tokens = [t for t in lowered.split() if t]
            for info in self.files.values():
                haystack = info["text"].lower()
                if not all(t in haystack or t in info["path"].lower() for t in tokens):
                    continue
                score = sum(5 * (t in info["title"].lower()) + 3 * (t in info["path"].lower()) + min(haystack.count(t), 5) for t in tokens)
                results.append(self._doc_result(info, score, snippet(info["text"], tokens[0]) or info["title"]))
            for entity in self.entities:
                haystack = (entity["text"] + " " + entity["id"]).lower()
                if all(t in haystack for t in tokens):
                    score = sum(4 * (t in entity["title"].lower()) + min(haystack.count(t), 5) for t in tokens)
                    results.append(self._entity_result(entity, score, snippet(entity["text"], tokens[0])))
        results.sort(key=lambda r: (-r["score"], r["type"], r.get("path") or r.get("id")))
        return {"query": query, "results": results[:MAX_RESULTS], "truncated": len(results) > MAX_RESULTS}

    @staticmethod
    def _doc_result(info, score, text):
        return {"type": "doc", "path": info["path"], "title": info["title"], "snippet": text, "score": score, "source": info["source"]}

    @staticmethod
    def _entity_result(entity, score, text):
        return {"type": "entity", "kind": entity["kind"], "id": entity["id"], "title": entity["title"], "snippet": text or entity["title"],
                "cap": entity["cap"], "revision": entity["revision"], "components": entity["components"],
                "contexts": entity["contexts"], "link": entity["link"], "score": score}
