"""Deterministic fault injection used only by tests and the installed-wheel harness."""
from __future__ import annotations

import json

try:
    from .c1_scenarios import tree
    from .c2_scenarios import prepared_fixture, setup
except ImportError:
    from c1_scenarios import tree
    from c2_scenarios import prepared_fixture, setup


INJECTOR = '''
import sys
from unittest.mock import patch
from roclec_spec_kit.store import Store
from roclec_spec_kit.cli import main
stage = sys.argv[1]
original = Store._atomic
snapshots = 0
def failing(store, relative, content):
    global snapshots
    if relative.startswith(".roclec/contracts/"):
        snapshots += 1
        if stage == "snapshot" and snapshots == 2:
            raise OSError("fixture interruption after snapshot")
    if stage == "index" and relative.startswith(".roclec/integrations/"):
        raise OSError("fixture interruption after index")
    if stage == "receipt" and relative.startswith(".roclec/receipts/"):
        raise OSError("fixture interruption before receipt")
    return original(store, relative, content)
with patch.object(Store, "_atomic", failing):
    raise SystemExit(main(sys.argv[2:]))
'''

INTERRUPTOR = '''
import sys
from unittest.mock import patch
import subprocess
from roclec_spec_kit.cli import main
original = subprocess.Popen.communicate
interrupted = False
def interrupt(process, *args, **kwargs):
    global interrupted
    if not interrupted:
        # Only interrupt a consumer check, after candidate Git queries.
        if any(str(arg).endswith("src/check.py") for arg in process.args):
            interrupted = True
            raise KeyboardInterrupt()
    return original(process, *args, **kwargs)
with patch.object(subprocess.Popen, "communicate", interrupt):
    raise SystemExit(main(sys.argv[1:]))
'''

ABRUPT = '''
import os, sys, subprocess
from unittest.mock import patch
from roclec_spec_kit.cli import main
original = subprocess.Popen
def abrupt(*args, **kwargs):
    if args and any(str(a).endswith("src/check.py") for a in args[0]):
        os._exit(130)
    return original(*args, **kwargs)
with patch.object(subprocess, "Popen", abrupt):
    raise SystemExit(main(sys.argv[1:]))
'''


def scenarios(workspace, invoke, inject, check):
    for stage in ("snapshot", "index", "receipt"):
        root, _, plan = prepared_fixture(workspace / ("recover-" + stage), invoke)
        prefix = ["--project", str(root), "--json"]
        failed = inject(INJECTOR, [stage, *prefix, "operation", "apply", str(plan)])
        payload = json.loads(failed.stdout)
        check("I-026 " + stage + ": interrupted write is partial", failed.returncode == 4 and payload["data"]["partial"], failed.stdout + failed.stderr)
        operation_id = payload["data"]["operation_id"]
        check("I-026 " + stage + ": plan and journal share identity", operation_id == json.loads(plan.read_text())["operation_id"])
        if stage == "index":
            current = json.loads((root / ".roclec/current.json").read_text())
            check("I-026 index interruption already moved pointer", bool(current["components"]["engine"]))
            (root / "src/new.py").write_text("# divergent input\n")
            before = tree(root)
            result = invoke([*prefix, "operation", "recover", operation_id])
            check("I-026 recovery refuses divergent code without mutation", result.returncode == 3 and tree(root) == before, result.stdout)
            (root / "src/new.py").unlink()
        result = invoke([*prefix, "operation", "recover", operation_id])
        check("I-026 " + stage + ": recovery succeeds in another invocation", result.returncode == 0, result.stdout + result.stderr)
        check("I-026 " + stage + ": journal removed", not (root / ".roclec/runtime" / (operation_id + ".json")).exists())
        before = tree(root)
        result = invoke([*prefix, "operation", "apply", str(plan)])
        check("I-026 " + stage + ": replay after recovery has no effects", result.returncode == 0 and tree(root) == before, result.stdout)
        result = invoke([*prefix, "inspect", "--change", "CHG-001"])
        check("I-026 " + stage + ": recovered result is integrated", result.returncode == 0 and json.loads(result.stdout)["data"]["status"] == "integrated", result.stdout)
    root, base = setup(workspace / "run-interruption", invoke, names=("engine",))
    prefix = ["--project", str(root), "--json"]
    result = inject(INTERRUPTOR, [*prefix, "run", "verify", "CHG-001", "--component", "engine", "--base", base])
    payload = json.loads(result.stdout)
    check("I-015 interrupted process records an interrupted run", result.returncode == 130 and payload["data"]["recorded"]
          and payload["data"]["run"]["status"] == "interrupted", result.stdout + result.stderr)
    result = invoke([*prefix, "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify"])
    check("I-015 interrupted run cannot satisfy verify", result.returncode == 1, result.stdout)
    result = invoke([*prefix, "run", "verify", "CHG-001", "--component", "engine", "--base", base])
    check("I-015 retry allocates another successful run", result.returncode == 0, result.stdout)
    result = inject(ABRUPT, [*prefix, "run", "verify", "CHG-001", "--component", "engine", "--base", base])
    check("I-015 abrupt termination preserves a durable start", result.returncode == 130
          and len(list((root / ".roclec/runs").glob("RUN-*/start.json"))) == 3, result.stdout + result.stderr)
    before = tree(root)
    result = invoke([*prefix, "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify"])
    check("I-015 unfinished retry does not reuse an older pass", result.returncode == 1 and tree(root) == before
          and "CANDIDATE_INCOMPLETE" in [i["code"] for i in json.loads(result.stdout)["issues"]], result.stdout)
