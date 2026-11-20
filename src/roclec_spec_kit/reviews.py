"""Opt-in review bookkeeping. Verdict quality and independence remain semantic checks."""

import hashlib
import json
from pathlib import Path
import re



def fingerprint(path: Path, administrative: bool = False) -> str:
    data = path.read_bytes()
    if administrative:
        text = data.decode("utf-8")
        text = re.sub(r"^status:.*$", "status: <administrative>", text, flags=re.M)
        text = re.sub(r"^(- \[)[ xX](\] T\d+\b)", r"\1 \2", text, flags=re.M)
        data = text.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def policy_path(spec) -> Path:
    return spec.path / "reviews/policy.json"


def policy(spec) -> dict:
    path = policy_path(spec)
    if not path.exists():
        return {"enabled": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = data.get(spec.amendment_id or "original", {"enabled": False})
        if not isinstance(entry, dict) or not isinstance(entry.get("enabled"), bool):
            raise ValueError("invalid review entry")
        return entry
    except (ValueError, AttributeError, TypeError):
        return {"enabled": True, "error": "invalid review policy"}


def report_path(spec, component: str) -> Path:
    suffix = "-" + spec.amendment_id if spec.amendment_id else ""
    return spec.path / "reviews" / f"implementation-{component}{suffix}.md"


def review_state(project, spec, component: str) -> dict:
    current = policy(spec)
    path = report_path(spec, component)
    result = {"enabled": current.get("enabled", False), "path": str(path), "state": "disabled"}
    if not result["enabled"]:
        return result
    result["state"] = "incomplete"
    if current.get("error"):
        result["reason"] = current["error"]
        return result
    if not path.is_file():
        result["state"] = "missing"
        return result
    try:
        match = re.search(r"```roclec-review\s*\n(.*?)\n```", path.read_text(encoding="utf-8"), re.S)
        data = json.loads(match[1]) if match else {}
        if not isinstance(data, dict):
            raise ValueError("review evidence must be an object")
        if data.get("verdict") not in {"ready", "changes-needed", "incomplete"} or data.get("independent") is not True or data.get("target") != spec.target:
            raise ValueError("missing verdict, target or independent context")
        inputs = data.get("inputs", [])
        required = {str((spec.path / name).relative_to(project.root)) for name in ("spec.md", "plan.md", "tasks.md")}
        if any(project.components[c].user_facing for c in spec.work_components):
            required.add(str((spec.path / "ux.md").relative_to(project.root)))
        seen = set()
        code_seen = False
        stale = False
        for item in inputs:
            namespace = item["root"]
            root = namespace.removeprefix("component:")
            base = project.root if namespace == "project" else project.components[root].repo
            relative = Path(item["path"])
            source = (base / relative).resolve()
            if relative.is_absolute() or not source.is_relative_to(base.resolve()) or ".git" in relative.parts:
                raise ValueError("review input outside allowed root")
            if namespace == "project":
                seen.add(str(relative))
            if root == component and namespace != "project":
                code_seen = True
            admin = namespace == "project" and source in {spec.path / "spec.md", spec.path / "tasks.md"}
            if not source.is_file() or fingerprint(source, admin) != item["sha256"]:
                stale = True
        if required - seen or not code_seen:
            raise ValueError("review must fingerprint spec, plan, tasks, applicable UX and component code/tests")
        result["state"] = "stale" if stale else data["verdict"]
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        result["reason"] = str(exc)
    return result
