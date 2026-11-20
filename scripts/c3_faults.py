"""C3 journal/revalidation failures injected only into disposable test processes."""
from __future__ import annotations

import json

try:
    from .c1_scenarios import tree
    from .c2_scenarios import prepared_fixture, commit, git
except ImportError:
    from c1_scenarios import tree
    from c2_scenarios import prepared_fixture, commit, git


INJECTOR = '''
import sys
from unittest.mock import patch
from roclec_spec_kit.store import Store
from roclec_spec_kit.cli import main
original = Store._atomic
stage = sys.argv[1]
def fail(store, relative, content):
    if stage == "receipt" and relative.startswith(".roclec/receipts/"):
        raise OSError("C3 fixture interruption before receipt")
    result = original(store, relative, content)
    if stage == "launcher" and relative == ".roclec/run":
        raise OSError("C3 fixture interruption after launcher bytes")
    return result
with patch.object(Store, "_atomic", fail):
    raise SystemExit(main(sys.argv[2:]))
'''


def scenarios(workspace, invoke, inject, check):
    root, base, integration_plan = prepared_fixture(workspace / "c3-recovery", invoke)
    prefix = ["--project", str(root), "--json"]

    def call(label, *args, expect=0, issue=None):
        before = tree(root)
        result = invoke([*prefix, *map(str, args)])
        check(label, result.returncode == expect, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        if issue:
            check(label + ": issue", issue in [i["code"] for i in payload["issues"]], result.stdout)
        if expect in (1, 2, 3):
            check(label + ": preserves bytes/modes", before == tree(root), result.stdout)
        return payload.get("data")

    def fail(label, stage, *args):
        result = inject(INJECTOR, [stage, *prefix, *map(str, args)])
        payload = json.loads(result.stdout)
        check(label, result.returncode == 4 and payload["data"]["partial"], result.stdout + result.stderr)
        return payload["data"]["operation_id"]

    call("C3 recovery fixture integrates", "operation", "apply", integration_plan)
    run = call("C3 recovery fixture verifies release", "run", "verify", "--release", "v1.0.0", "--component", "engine", "--base", base)["run"]
    commit(root)
    plan = workspace / "c3-recover-prepare.json"
    prepared = call("C3 recovery exports preparation", "release", "prepare", "engine", "v1.0.0", "--run", run["id"], "--out", plan)["plan"]
    preparation, shipped = prepared["inputs"]["preparation"], prepared["inputs"]["candidate"]["head"]
    operation = fail("C3 preparation interruption is recoverable", "receipt", "operation", "apply", plan)
    (root / "src/new.py").write_text("# divergent candidate\n")
    call("C3 preparation recovery rejects changed candidate", "operation", "recover", operation, expect=3, issue="OPERATION_CONFLICT")
    (root / "src/new.py").unlink()
    call("C3 preparation recovery completes exact operation", "operation", "recover", operation)
    commit(root)
    remote = workspace / "recovery-remote.git"
    remote.mkdir()
    git(remote, "init", "--bare", "-q")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "tag", "v1.0.0", shipped)
    git(root, "push", "origin", "refs/tags/v1.0.0")
    record_plan = workspace / "c3-recover-record.json"
    call("C3 recovery exports publication record", "release", "record", "engine", "v1.0.0", "--preparation", preparation,
         "--commit", shipped, "--tag", "v1.0.0", "--remote", "origin", "--actor", "fixture", "--reason", "Disposable remote", "--out", record_plan)
    wrong = git(root, "rev-parse", f"{shipped}^")
    git(remote, "update-ref", "refs/tags/v1.0.0", wrong)
    call("I-030 changed remote tag rejects exported plan", "operation", "apply", record_plan, expect=1, issue="TAG_MISMATCH")
    git(remote, "update-ref", "refs/tags/v1.0.0", shipped)
    operation = fail("C3 publication interruption preserves journal", "receipt", "operation", "apply", record_plan)
    git(remote, "update-ref", "refs/tags/v1.0.0", wrong)
    call("C3 publication recovery revalidates remote", "operation", "recover", operation, expect=3, issue="OPERATION_CONFLICT")
    git(remote, "update-ref", "refs/tags/v1.0.0", shipped)
    call("C3 publication recovery completes matching record", "operation", "recover", operation)
    before = tree(root)
    call("C3 recovered publication replay is idempotent", "operation", "apply", record_plan)
    check("C3 recovered publication replay writes nothing", before == tree(root))
    operation = fail("I-033 instruction installation interruption journaled", "launcher", "skills")
    call("I-033 instruction installation recovers", "operation", "recover", operation)
    check("I-033 recovery restores executable launcher", (root / ".roclec/run").stat().st_mode & 0o111)
    call("C3 recovered consumer remains structurally valid", "check")
