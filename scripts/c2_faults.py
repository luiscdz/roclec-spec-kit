"""Deterministic fault injection used only by tests and the installed-wheel harness."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

try:
    from .c1_scenarios import digest, file_hash, put_json, tree
    from .c2_scenarios import PRODUCER, commit, git, prepared_fixture, setup
except ImportError:
    from c1_scenarios import digest, file_hash, put_json, tree
    from c2_scenarios import PRODUCER, commit, git, prepared_fixture, setup


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
    if stage == "rollback" and relative == ".roclec/current.json":
        raise OSError("fixture interruption while restoring prior index")
    if relative.startswith(".roclec/receipts/"):
        if stage == "receipt":
            raise OSError("fixture interruption before receipt")
        if stage == "confirmed":
            original(store, relative, content)
            raise OSError("fixture interruption after receipt")
    return original(store, relative, content)
with patch.object(Store, "_atomic", failing):
    raise SystemExit(main(sys.argv[2:]))
'''

INTERRUPTOR = '''
import sys
from unittest.mock import patch
from roclec_spec_kit import run_logs
from roclec_spec_kit.cli import main
with patch.object(run_logs, "collect", side_effect=KeyboardInterrupt):
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

LOG_WRITE_FAILURE = '''
import sys
from unittest.mock import patch
from roclec_spec_kit.run_logs import Capture
from roclec_spec_kit.cli import main
with patch.object(Capture, "append", side_effect=OSError("fixture log disk error")):
    raise SystemExit(main(sys.argv[1:]))
'''

MEASURE_CAPTURE = '''
import resource, sys
from roclec_spec_kit.cli import main
unit = 1 if sys.platform == "darwin" else 1024
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
result = main(sys.argv[1:])
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print((after - before) * unit, file=sys.stderr)
raise SystemExit(result)
'''


def capture_scenarios(workspace, invoke, inject, check):
    secret_key = "ROCLEC_FIXTURE_CAPTURE_SECRET"
    secret = "synthetic-log-secret"
    quota = 256 * 1024
    excerpt_limit = 48
    max_check_seconds = 25
    max_capture_growth = 32 * 1024 * 1024
    sample_records = 250
    original_env = os.environ.get(secret_key)
    os.environ[secret_key] = secret
    try:
        root, base = setup(workspace / "log-capture", invoke, names=("engine",),
                           check_code="import os\nassert 'ROCLEC_FIXTURE_CAPTURE_SECRET' not in os.environ\nprint('complete')\n")
        prefix = ["--project", str(root), "--json"]
        run_args = ["run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER]
        def run_command(runner=invoke):
            result = runner([*prefix, *run_args])
            return result, json.loads(result.stdout)["data"]["run"]
        passed, run = run_command()
        check("F3 default environment excludes unlisted variables", passed.returncode == 0, passed.stdout)
        stdout = run["results"][0]["stdout"]
        check("F3 default manifest has no excerpt", "excerpt" not in stdout and (root / stdout["path"]).is_file(), "")
        commit(root)
        clone = workspace / "without-logs"
        git(root, "clone", "--no-local", str(root), str(clone))
        cloned = ["--project", str(clone), "--json"]
        result = invoke([*cloned, "check"])
        check("F3 clone reports unavailable local captures with success",
              result.returncode == 0 and any(i["code"] == "LOG_UNAVAILABLE" for i in json.loads(result.stdout)["issues"]), result.stdout)
        result = invoke([*cloned, "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify"])
        check("F3 clone gate accepts versioned results without logs", result.returncode == 0, result.stdout)

        profile = root / ".roclec/project.toml"
        body = profile.read_text().replace("[components.engine]",
               f'log_quota_bytes = {quota}\nmax_log_bytes = {excerpt_limit}\nsecret_env = ["{secret_key}"]\n'
               'redact_patterns = ["fixture-[0-9]+"]\n[components.engine]')
        profile.write_text(body.replace('verification = [{', f'verification = [{{env=["{secret_key}"],'))
        script = root / "src/check.py"
        script.write_text(f'import os\nprint(os.environ[{secret_key!r}], "fixture-849", "x" * 200)\n')
        passed, run = run_command()
        check("F3 opt-in extract run succeeds", passed.returncode == 0, passed.stdout)
        stdout = run["results"][0]["stdout"]
        raw = (root / stdout["path"]).read_bytes()
        check("F3 full raw output is local and digested", secret.encode() in raw and stdout["sha256"] == file_hash(raw)
              and stdout["size"] == len(raw) and stdout["complete"], "")
        excerpt = stdout["excerpt"]
        check("F3 extract is redacted and bounded", len(excerpt.encode()) <= excerpt_limit and len(raw) > excerpt_limit
              and secret not in excerpt and "fixture-849" not in excerpt and "[REDACTED]" in excerpt, "")
        check("F3 secret stays out of the committed manifest", secret.encode() not in
              (root / ".roclec/runs" / run["id"] / "manifest.json").read_bytes(), "")

        script.write_text('import os\nwhile True:\n    os.write(1, b"x" * 65536)\n')
        failed, run = run_command(lambda args: inject(MEASURE_CAPTURE, args))
        check("F3 quota terminates the producer and records incomplete capture",
              failed.returncode == 1 and run["status"] == "incomplete" and not run["results"][0]["stdout"]["complete"]
              and sum(run["results"][0][label]["size"] for label in ("stdout", "stderr")) == quota, failed.stdout)
        growth = int(failed.stderr.strip())
        check("F3 capture memory growth meets the preset bound", growth < max_capture_growth,
              f"{growth} bytes added to peak RSS, bound {max_capture_growth}")
        failed, run = run_command(lambda args: inject(LOG_WRITE_FAILURE, args))
        check("F3 disk write failure cannot satisfy verification",
              failed.returncode == 1 and run["status"] == "incomplete" and not run["results"][0]["stdout"]["complete"], failed.stdout)

        template = json.loads((root / ".roclec/runs" / run["id"] / "start.json").read_bytes())
        previous = run["id"]
        for number in range(sample_records):
            run_id = f"RUN-{number:026d}"
            attempt = {**template, "id": run_id, "supersedes": [previous]}
            attempt["digest"] = digest({k: v for k, v in attempt.items() if k != "digest"})
            put_json(root / ".roclec/runs" / run_id / "start.json", attempt)
            previous = run_id
        start = time.monotonic()
        result = invoke([*prefix, "check"])
        elapsed = time.monotonic() - start
        check("F3 check indexes hundreds of attempts within the preset budget",
              result.returncode == 0 and elapsed < max_check_seconds
              and len(json.loads(result.stdout)["data"]["unfinished_runs"]) == sample_records,
              f"{sample_records} attempts, {elapsed:.3f}s, budget {max_check_seconds}s")
    finally:
        if original_env is None:
            os.environ.pop(secret_key, None)
        else:
            os.environ[secret_key] = original_env


def lock_scenarios(workspace, invoke, check):
    root, _ = setup(workspace / "lock-owner", invoke, names=("engine",))
    commit(root)
    git(root, "checkout", "-qb", "fixture-branch")
    owner = root / ".roclec/runtime/lock/owner.json"
    args = ["--project", str(root), "--json", "operation", "unlock", "--if-stale"]
    deceased = subprocess.Popen([sys.executable, "-c", "pass"])
    deceased.wait(timeout=10)
    info = {"host": socket.gethostname(), "at": "2026-11-19T12:00:00Z", "pid": deceased.pid, "operation": "views"}
    put_json(owner, info)
    result = invoke(args)
    check("F3 branch cannot unlock a trunk operation",
          result.returncode == 3 and json.loads(result.stdout)["issues"][0]["code"] == "OFF_TRUNK" and owner.is_file(), result.stdout)
    put_json(owner, {**info, "operation": "run-verify", "pid": os.getpid()})
    result = invoke(args)
    check("F3 live owner retains its lock", result.returncode == 3 and owner.is_file(), result.stdout)
    put_json(owner, {**info, "operation": "run-verify"})
    result = invoke(args)
    check("F3 dead branch-operation owner releases its lock", result.returncode == 0 and not owner.parent.exists(), result.stdout)


def scenarios(workspace, invoke, inject, check):
    for stage in ("index", "confirmed"):
        root, _, plan = prepared_fixture(workspace / ("target-moved-" + stage), invoke)
        prefix = ["--project", str(root), "--json"]
        before = tree(root)
        failed = inject(INJECTOR, [stage, *prefix, "operation", "apply", str(plan)])
        operation_id = json.loads(failed.stdout)["data"]["operation_id"]
        check("F2 target recovery injected failure " + stage, failed.returncode == 4, failed.stdout)
        git(root, "update-ref", "-d", "refs/remotes/fixture/main")
        if stage == "index":
            index = root / ".roclec/current.json"
            expected = index.read_bytes()
            index.write_bytes(expected + b" ")
            divergent = tree(root)
            result = invoke([*prefix, "operation", "recover", operation_id])
            check("F2 rollback rejects divergent file before any restore", result.returncode == 3 and tree(root) == divergent, result.stdout)
            index.write_bytes(expected)
            failed = inject(INJECTOR, ["rollback", *prefix, "operation", "recover", operation_id])
            check("F2 rollback interruption retains recovery journal", failed.returncode == 4, failed.stdout)
            git(root, "update-ref", "refs/remotes/fixture/main", git(root, "rev-parse", "HEAD"))
        result = invoke([*prefix, "operation", "recover", operation_id])
        check("F2 target moved recovery " + stage, result.returncode == 0, result.stdout)
        outcome = json.loads(result.stdout)["data"]["receipt"]
        if stage == "index":
            check("F2 unconfirmed integration rolls back exact bytes", outcome["status"] == "rolled-back" and tree(root) == before, result.stdout)
            repeated = invoke([*prefix, "operation", "recover", operation_id])
            check("F2 no receipt retained after rollback", repeated.returncode == 1, repeated.stdout)
        else:
            repeated = invoke([*prefix, "operation", "recover", operation_id])
            check("F2 confirmed receipt remains unchanged", repeated.returncode == 0 and json.loads(repeated.stdout)["data"]["receipt"] == outcome, repeated.stdout)
        result = invoke([*prefix, "check"])
        check("F2 project coherent after target recovery", result.returncode == 0, result.stdout)

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
    result = inject(INTERRUPTOR, [*prefix, "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER])
    payload = json.loads(result.stdout)
    check("I-015 interrupted process records an interrupted run", result.returncode == 130 and payload["data"]["recorded"]
          and payload["data"]["run"]["status"] == "interrupted", result.stdout + result.stderr)
    result = invoke([*prefix, "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify"])
    check("I-015 interrupted run cannot satisfy verify", result.returncode == 1, result.stdout)
    result = invoke([*prefix, "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER])
    check("I-015 retry allocates another successful run", result.returncode == 0, result.stdout)
    result = inject(ABRUPT, [*prefix, "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER])
    check("I-015 abrupt termination preserves a durable start", result.returncode == 130
          and len(list((root / ".roclec/runs").glob("RUN-*/start.json"))) == 3, result.stdout + result.stderr)
    before = tree(root)
    result = invoke([*prefix, "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify"])
    check("I-015 unfinished retry does not reuse an older pass", result.returncode == 1 and tree(root) == before
          and "CANDIDATE_INCOMPLETE" in [i["code"] for i in json.loads(result.stdout)["issues"]], result.stdout)
