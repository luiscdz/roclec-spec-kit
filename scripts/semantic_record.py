"""Record a future subject's native CLI invocation without evaluating its answer."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def classify(exit_code, stdout):
    """Classify a captured CLI envelope without grading its semantic outcome."""
    envelope = None
    try:
        candidate = json.loads(stdout.decode("utf-8", "replace"))
        if isinstance(candidate, dict) and isinstance(candidate.get("ok"), bool):
            envelope = candidate
    except (json.JSONDecodeError, UnicodeError):
        pass
    issues = envelope.get("issues", []) if envelope else []
    codes = [item.get("code") for item in issues if isinstance(item, dict) and isinstance(item.get("code"), str)]
    if exit_code == 0:
        outcome = "success"
    elif exit_code == 1 and envelope is not None and codes:
        outcome = "domain-gate"
    elif exit_code == 2 or "INVALID_INPUT" in codes:
        outcome = "invalid-invocation"
    elif exit_code in {4, 124, 130} or any(code in {"IO_ERROR", "IO_PARTIAL", "INTERRUPTED"} for code in codes):
        outcome = "io-or-environment"
    else:
        outcome = "unclassified"
    return {"envelope_ok": envelope.get("ok") if envelope else None, "issue_codes": codes,
            "exit_class": outcome, "next_action": envelope.get("next_action") if envelope else None}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        raise SystemExit("usage: semantic_record.py OUTPUT_DIRECTORY EXECUTABLE [ARG...]")
    directory = Path(args[0])
    directory.mkdir(parents=True, exist_ok=True)
    command = args[1:]
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    started = datetime.now(timezone.utc).isoformat()
    clock = time.monotonic()
    try:
        result = subprocess.run(command, env=env, capture_output=True)
    except OSError as exc:
        result = subprocess.CompletedProcess(command, 4, stdout=b"", stderr=str(exc).encode("utf-8", "replace"))
    classification = classify(result.returncode, result.stdout)
    event = {"schema": 1, "kind": "subject-native-cli", "started_at": started,
             "duration_seconds": round(time.monotonic() - clock, 6), "argv": command,
             "cwd": str(Path.cwd()), "exit": result.returncode,
             "stdout": result.stdout.decode("utf-8", "replace"), "stderr": result.stderr.decode("utf-8", "replace"),
             "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
             "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(), **classification}
    (directory / (uuid.uuid4().hex + ".json")).write_text(json.dumps(event, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
