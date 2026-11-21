"""Prepare importable change bundles outside the project store."""
from pathlib import Path
from tempfile import TemporaryDirectory

from .model import canonical, digest, encoded, fields, fingerprint, identifier, local_path, need, read_json, sha, text
from .origins import captured_paths
from .store import Store


def ordered(values, key=None):
    need(isinstance(values, list), "INVALID_INPUT", "Expected a list", exit_code=2)
    return sorted(values, key=key or canonical)


def objects(values, *keys):
    need(isinstance(values, list) and all(isinstance(row, dict) and all(text(row.get(k)) for k in keys)
                                         for row in values),
         "INVALID_INPUT", "Expected records with text keys", exit_code=2, expected=list(keys))
    return sorted(values, key=lambda row: tuple(row[k] for k in keys))


def contents(root, paths):
    result = {}
    for relative in paths:
        path = local_path(root, relative)
        need(path.is_file(), "INVALID_REFERENCE", "Bundle file is missing", path=relative)
        result[relative] = path.read_bytes()
    return result


def seal(kernel, folder, *, check=False):
    managed = kernel.store.path(".roclec")
    need(folder.is_dir() and managed not in (folder, *folder.parents), "INVALID_PATH",
         "Seal requires a bundle outside .roclec", path=folder, exit_code=2)
    record = read_json(local_path(folder, "change.json"))
    fields(record, ("model_schema", "id", "kind", "semantic"), ("proposal_digest",))
    change_id = identifier(record["id"], "CHG")
    need(not any(d["kind"] == "change-approve" for d in kernel.decisions(change_id)),
         "OPERATION_CONFLICT", "Cannot seal a change with an approved snapshot", entity=change_id, exit_code=3)
    need(not kernel.store.path(f".roclec/changes/{change_id}").exists(),
         "ID_COLLISION", "Change ID already exists", entity=change_id)
    semantic = record["semantic"]
    fields(semantic, ("intention", "components", "bases", "deltas", "proposed", "dependencies", "references"),
           ("files", "baseline_release", "fixes", "origins", "coverage"))
    manifest = semantic.get("files", {})
    need(isinstance(manifest, dict), "INVALID_INPUT", "files must be an object", exit_code=2)
    captures = captured_paths(semantic["origins"], entity=change_id) if "origins" in semantic else ()
    files = contents(folder, [semantic["intention"], *manifest, *captures])
    semantic["files"] = {p: sha(b) for p, b in files.items()}
    generated = {}
    for key in ("components", "deltas", "dependencies", "fixes"):
        if key in semantic:
            semantic[key] = ordered(semantic[key])
    for delta in semantic["deltas"]:
        if isinstance(delta, dict):
            for key in ("retire_acceptance_ids", "add_acceptance_ids"):
                if key in delta:
                    delta[key] = ordered(delta[key])
    semantic["bases"] = objects(semantic["bases"], "capability_id", "component")
    semantic["references"] = objects(semantic["references"], "id")
    semantic["proposed"] = objects(semantic["proposed"], "capability_id")
    for entry in semantic["proposed"]:
        fields(entry, ("capability_id", "components"), ("revision",))
        cap = identifier(entry["capability_id"], "CAP")
        revision = entry.get("revision")
        old = local_path(folder, f"proposed/{cap}/{fingerprint(revision) if revision is not None else 'draft'}")
        descriptor = read_json(local_path(old, "contract.json"))
        fields(descriptor, ("model_schema", "capability_id", "requirements", "acceptance", "references"), ("files",))
        descriptor["requirements"] = objects(descriptor["requirements"], "id", "statement")
        descriptor["acceptance"] = objects(descriptor["acceptance"], "id", "scenario")
        descriptor["references"] = objects(descriptor["references"], "id")
        for row in [*descriptor["requirements"], *descriptor["acceptance"]]:
            need("components" in row, "INVALID_INPUT", "Missing contract components", exit_code=2)
            row["components"] = ordered(row["components"])
            if "acceptance_ids" in row:
                row["acceptance_ids"] = ordered(row["acceptance_ids"])
        documents = contents(old, [row["statement"] for row in descriptor["requirements"]]
                             + [row["scenario"] for row in descriptor["acceptance"]])
        descriptor["files"] = {p: sha(b) for p, b in documents.items()}
        entry["components"] = ordered(entry["components"])
        entry["revision"] = digest(descriptor)
        prefix = f"proposed/{cap}/{entry['revision']}"
        generated.update({f"{prefix}/{path}": data for path, data in documents.items()})
        generated[f"{prefix}/contract.json"] = encoded(descriptor)
    record["proposal_digest"] = digest({key: record[key] for key in ("id", "kind", "semantic")})
    generated["change.json"] = encoded(record)
    with TemporaryDirectory(prefix="roclec-seal-") as temporary:
        stage = Path(temporary)
        for relative, data in {**files, **generated}.items():
            path = local_path(stage, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        kernel.change(change_id, source=stage, check_base=True)
    changed = []
    for relative, data in generated.items():
        path = local_path(folder, relative)
        need(not path.exists() or path.is_file(), "INVALID_PATH", "Bundle destination must be a file", path=relative)
        if not path.exists() or path.read_bytes() != data:
            changed.append(relative)
    if not check:
        store = Store(folder)
        for relative in changed:
            store._atomic(relative, generated[relative])
    return {"id": change_id, "proposal_digest": record["proposal_digest"], "changed": sorted(changed), "check": check}
