"""The public schema-2 CLI. Legacy feature folders are never auto-dispatched."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import traceback

from . import __version__
from .config import ConfigError, load_profile
from .external_skills import SkillLockError
from .kernel import Kernel
from .model import ModelError, need, read_json
from .store import Store


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ModelError("INVALID_INPUT", message, exit_code=2, remediation=self.format_usage().strip())


def build_parser():
    parser = Parser(prog="roclec", description="Native contract/change/release workflow, profile 3")
    parser.add_argument("--project", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--debug", action="store_true", help="Print unexpected error tracebacks to stderr")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Summarize component activity and pending gates")
    listing = sub.add_parser("list", help="List model records")
    listing.add_argument("category", choices=("adrs", "changes", "futs", "releases", "runs", "findings"))
    scope = listing.add_mutually_exclusive_group()
    scope.add_argument("--change")
    scope.add_argument("--release")
    listing.add_argument("--component")
    listing.add_argument("--open", action="store_true", help="Show only open or still-open findings")
    listing.add_argument("--origin", help="Filter changes by source identifier")
    init = sub.add_parser("init", help="Initialize a profile-3 project on its configured Git trunk")
    init.add_argument("path")
    init.add_argument("--profile", required=True, type=Path)
    inspect = sub.add_parser("inspect", help="Read integrated, proposed or historical state")
    selectors = inspect.add_mutually_exclusive_group(required=True)
    for name in ("adr", "capability", "change", "fut", "release"):
        selectors.add_argument(f"--{name}")
    inspect.add_argument("--component")
    inspect.add_argument("--at")
    inspect.add_argument("--deep", action="store_true", help="Evaluate live verification gates for a change")
    foundation = sub.add_parser("foundation")
    fsub = foundation.add_subparsers(dest="action", required=True)
    fcheck = fsub.add_parser("check")
    fcheck.add_argument("--component", required=True)
    fcheck.add_argument("--change")
    agree = fsub.add_parser("agree")
    for name in ("ref", "actor", "reason"):
        agree.add_argument(f"--{name}", required=True)
    reference = sub.add_parser("reference")
    rsub = reference.add_subparsers(dest="action", required=True)
    for name in ("add", "update"):
        editor = rsub.add_parser(name)
        editor.add_argument("id")
        editor.add_argument("--path", required=True)
        editor.add_argument("--component", action="append", required=True)
        editor.add_argument("--role", required=True)
        editor.add_argument("--supersedes", action="append", default=[], metavar="ADR-ID",
                            help="ADR replaced by this decision reference (repeatable; role decision only)")
    change = sub.add_parser("change")
    csub = change.add_subparsers(dest="action", required=True)
    new = csub.add_parser("new")
    new.add_argument("--file", required=True, type=Path)
    seal = csub.add_parser("seal")
    seal.add_argument("directory", type=Path)
    seal.add_argument("--check", action="store_true")
    approve = csub.add_parser("approve")
    approve.add_argument("id")
    approve.add_argument("--digest", required=True)
    for command in (approve, csub.add_parser("cancel")):
        if command is not approve:
            command.add_argument("id")
        command.add_argument("--actor", required=True)
        command.add_argument("--reason", required=True)
    start = csub.add_parser("start")
    start.add_argument("id")
    start.add_argument("--component", required=True)
    start.add_argument("--actor", required=True)
    fut = sub.add_parser("fut")
    fsub = fut.add_subparsers(dest="action", required=True)
    capture = fsub.add_parser("capture")
    capture.add_argument("--file", required=True, type=Path)
    decide = fsub.add_parser("decide")
    decide.add_argument("id")
    decide.add_argument("--outcome", choices=("evaluating", "promoted", "discarded", "duplicate"), required=True)
    decide.add_argument("--actor", required=True)
    decide.add_argument("--reason", required=True)
    decide.add_argument("--target")
    release = sub.add_parser("release")
    rsub = release.add_subparsers(dest="action", required=True)
    plan = rsub.add_parser("plan")
    plan.add_argument("component")
    plan.add_argument("version")
    plan.add_argument("--kind", choices=("release", "hotfix", "bugfix"), default="release")
    plan.add_argument("--base-tag")
    members = plan.add_mutually_exclusive_group(required=True)
    members.add_argument("--change", action="append", default=[])
    members.add_argument("--clear", action="store_true", help="Explicitly clear a planning release's membership")
    prepare_release = rsub.add_parser("prepare")
    prepare_release.add_argument("component")
    prepare_release.add_argument("version")
    prepare_release.add_argument("--run", required=True)
    prepare_release.add_argument("--out", required=True, type=Path)
    record_release = rsub.add_parser("record")
    record_release.add_argument("component")
    record_release.add_argument("version")
    for flag in ("preparation", "commit", "tag", "remote", "actor", "reason"):
        record_release.add_argument("--" + flag, required=True)
    record_release.add_argument("--out", required=True, type=Path)
    check = sub.add_parser("check")
    check.add_argument("--change")
    check.add_argument("--component")
    check.add_argument("--gate", choices=("approve", "implement", "verify", "integrate", "release"))
    check.add_argument("--release")
    views = sub.add_parser("views")
    views.add_argument("--write", action="store_true")
    operation = sub.add_parser("operation")
    osub = operation.add_subparsers(dest="action", required=True)
    for name in ("inspect", "recover"):
        command = osub.add_parser(name)
        command.add_argument("id")
    apply = osub.add_parser("apply")
    apply.add_argument("file")
    unlock = osub.add_parser("unlock")
    unlock.add_argument("--if-stale", action="store_true", required=True)
    run = sub.add_parser("run")
    verify = run.add_subparsers(dest="action", required=True).add_parser("verify")
    verify.add_argument("id", nargs="?")
    verify.add_argument("--release")
    verify.add_argument("--component", required=True)
    verify.add_argument("--base", required=True)
    verify.add_argument("--role", required=True, help="Declared producer role: implementer, coordinator or human")
    verify.add_argument("--context", required=True, help="Actual session or tool identity that produced the run")
    evidence = sub.add_parser("evidence")
    record = evidence.add_subparsers(dest="action", required=True).add_parser("record")
    record.add_argument("--file", required=True, type=Path)
    review = sub.add_parser("review")
    policy = review.add_subparsers(dest="action", required=True).add_parser("policy")
    policy.add_argument("--change", required=True)
    policy.add_argument("--enabled", choices=("true", "false"), required=True)
    policy.add_argument("--actor", required=True)
    policy.add_argument("--reason", required=True)
    integrate = sub.add_parser("integrate")
    prepare = integrate.add_subparsers(dest="action", required=True).add_parser("prepare")
    prepare.add_argument("id")
    prepare.add_argument("--component", required=True)
    prepare.add_argument("--run", required=True)
    prepare.add_argument("--out", required=True, type=Path)
    skills = sub.add_parser("skills")
    skills.add_argument("--into")
    skills.add_argument("--restore", action="store_true")
    sub.add_parser("speckit")
    view = sub.add_parser("view", help="Open the local read-only project viewer (needs the 'viewer' extra)")
    view.add_argument("--no-open", action="store_true", help="Print the URL without opening a browser")
    view.add_argument("--port", type=int, default=0, help="Local port (default: any available port)")
    for name in ("product",):
        unavailable = sub.add_parser(name, help="Consumer-specific views; no schema-1 fallback")
        unavailable.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def execute(args):
    command, action = args.command, getattr(args, "action", None)
    if command == "init":
        return Kernel.initialize(Path(args.path).resolve(), args.profile.resolve())
    if command == "operation" and action in {"inspect", "recover", "unlock"}:
        # Recovery must remain possible when a partially written project cannot load.
        root = Path(args.project).resolve()
        store = Store(root)
        if action == "unlock":
            return store.unlock_stale()
        if action == "recover":
            return {"receipt": store.recover(args.id)}
        from .model import fingerprint
        fingerprint(args.id)
        for relative in (f".roclec/runtime/{args.id}.json", f".roclec/receipts/{args.id}.json"):
            if store.path(relative).is_file():
                return {"operation": read_json(store.path(relative))}
        raise ModelError("INVALID_REFERENCE", "Unknown operation", entity=args.id)
    if command == "view":
        need(0 <= args.port <= 65535, "INVALID_INPUT", "Port must be between 0 and 65535", exit_code=2)
        from .viewer import serve
        return serve(Path(args.project), port=args.port, open_browser=not args.no_open)
    kernel = Kernel(load_profile(Path(args.project)))
    read_only = {"inspect", "check", "status", "list", "integrate", "product"}
    branch_commands = {("change", "start"), ("run", "verify"), ("evidence", "record")}
    external_output = {("change", "seal"), ("release", "prepare"), ("release", "record"), ("foundation", "check")}
    if (command not in read_only | {"skills", "speckit"} and (command, action) not in branch_commands | external_output
            and (command != "views" or args.write)):
        kernel.store.guard_branch(command)
    if command == "status":
        return kernel.status()
    if command == "list":
        if args.category == "findings":
            need(args.origin is None, "INVALID_INPUT", "--origin applies only to changes", exit_code=2)
            return {"findings": list_findings(kernel, args)}
        need(all(value is None for value in (args.change, args.release, args.component)) and not args.open,
             "INVALID_INPUT", "Finding filters require list findings", exit_code=2)
        return {args.category: kernel.list_records(args.category, origin=args.origin)}
    if command == "product":
        raise ModelError("FEATURE_UNAVAILABLE", "Product views require explicit consumer adoption; no schema-1 fallback")
    if command in {"skills", "speckit"}:
        from .installation import install
        return install(kernel, into=getattr(args, "into", None), restore=getattr(args, "restore", False), adapter=command == "speckit")
    if command == "release" and action != "plan":
        from .releases import Releases
        inputs = ({"run_id": args.run} if action == "prepare" else
                  {k: getattr(args, k) for k in ("preparation", "commit", "tag", "remote", "actor", "reason")})
        return Releases(kernel).export("release-" + action, args.component, args.version, args.out, **inputs)
    if command in {"run", "evidence", "review"}:
        from .verification import Verification
        verification = Verification(kernel, release={"component": args.component, "version": args.release} if command == "run" and args.release else None)
        if command == "run":
            need((args.id is None) != (args.release is None), "INVALID_INPUT", "Select a change or --release, exclusively", exit_code=2)
            return verification.run(args.id, args.component, args.base, args.role, args.context)
        if command == "evidence":
            return verification.record_evidence(args.file.resolve())
        return verification.set_policy(args.change, args.enabled == "true", args.actor, args.reason)
    if command == "integrate" or (command == "operation" and action == "apply"):
        from .integration import Integration
        integration = Integration(kernel)
        if command == "integrate":
            return integration.prepare(args.id, args.component, args.run, args.out)
        return integration.apply(Path(args.file).resolve())
    if command == "inspect":
        need(args.at is None or args.capability is not None, "INVALID_INPUT", "--at applies only to a capability", exit_code=2)
        need(not args.deep or args.change is not None, "INVALID_INPUT", "--deep applies only to a change", exit_code=2)
        if args.capability:
            return kernel.inspect_capability(args.capability, args.component, args.at)
        if args.change:
            return kernel.inspect_change(args.change, deep=args.deep)
        if args.fut:
            return kernel.inspect_fut(args.fut)
        if args.adr:
            from .adr import Adrs
            return Adrs(kernel).inspect(args.adr)
        need(args.component is not None, "AMBIGUOUS_COMPONENT", "Select a release component", exit_code=2)
        result = kernel.release(args.component, args.release)
        from .verification import Verification
        from .releases import Releases
        actual_version = result["record"]["version"]
        result["review_policy"] = Verification(kernel, release={"component": args.component, "version": actual_version}).policy(None)
        result["preparations"] = [{"id": p.stem, "record": Releases(kernel).preparation(args.component, actual_version, p.stem)}
                                  for p in sorted(kernel.store.path(f".roclec/releases/{args.component}/{actual_version}/preparations").glob("*.json"))]
        return result
    if command == "foundation":
        if action == "agree":
            return kernel.agree_foundation(args.ref, args.actor, args.reason)
        return kernel.foundation(args.component, args.change)
    if command == "reference":
        return kernel.write_reference(action, args.id, args.path, args.component, args.role, args.supersedes)
    if command == "change":
        if action == "seal":
            from .authoring import seal
            return seal(kernel, args.directory.resolve(), check=args.check)
        if action == "new":
            return kernel.new_change(args.file.resolve())
        if action == "approve":
            return kernel.approve(args.id, args.digest, args.actor, args.reason)
        if action == "start":
            return kernel.start(args.id, args.component, args.actor)
        return kernel.cancel(args.id, args.actor, args.reason)
    if command == "fut":
        if action == "capture":
            return kernel.capture(args.file.resolve())
        return kernel.decide_fut(args.id, args.outcome, args.actor, args.reason, args.target)
    if command == "release":
        return kernel.release_plan(args.component, args.version, args.kind, args.change, args.base_tag)
    if command == "views":
        return kernel.views(args.write)
    if command == "check":
        need(args.gate is None or args.change is not None or args.gate == "release", "INVALID_INPUT", "--gate requires --change except release", exit_code=2)
        need(args.gate != "release" or args.release is not None, "INVALID_INPUT", "Release gate needs --release", exit_code=2)
        need(args.release is None or args.gate == "release", "INVALID_INPUT", "--release requires the release gate", exit_code=2)
        if args.gate:
            return kernel.gate(args.change, args.component, args.gate, args.release)
        if args.change:
            return kernel.gate(args.change, args.component, "approve")
        return kernel.check()
    raise ModelError("INVALID_INPUT", "Unknown command", exit_code=2)


def list_findings(kernel, args):
    need((args.change is None) != (args.release is None), "INVALID_INPUT",
         "Select --change or --release for findings", exit_code=2)
    if args.release is not None:
        from .releases import Releases
        need(args.component is not None, "AMBIGUOUS_COMPONENT", "Select a release component", exit_code=2)
        findings = Releases(kernel).findings(args.component, args.release)
    else:
        need(args.component is None, "INVALID_INPUT", "--component applies to release findings", exit_code=2)
        from .verification import Verification
        record, _, _ = kernel.change(args.change)
        verifier = Verification(kernel)
        findings = [row for component in sorted(record["semantic"]["components"])
                    for row in verifier.findings(args.change, component)]
    if args.open:
        findings = [row for row in findings if row["status"] in {"open", "still-open"}]
    return findings


def findings_table(rows, indent):
    headings = ("Key", "Component", "Severity", "Location", "Status", "State record")
    cells = [headings]
    for row in rows:
        location = row["location"]
        cells.append((row["key"], row["component"], row["severity"],
                      f"{location['path']}:{location['line']}" if location else "—",
                      row["status"], ", ".join(row["state_records"])))
    widths = [max(map(len, column)) for column in zip(*cells)]
    for line in cells:
        print(indent + "  ".join(cell.ljust(width) for cell, width in zip(line, widths)).rstrip())


def human_output(value, depth=0):
    indent = "  " * depth
    if isinstance(value, dict) and value:
        for key, item in value.items():
            if key == "findings" and isinstance(item, list) and item and all(
                    isinstance(row, dict) and "state_records" in row for row in item):
                print(f"{indent}{key}:")
                findings_table(item, indent + "  ")
            elif isinstance(item, (dict, list)) and item:
                print(f"{indent}{key}:")
                human_output(item, depth + 1)
            else:
                print(f"{indent}{key}: {item if item is not None else '—'}")
    elif isinstance(value, list) and value:
        for item in value:
            if isinstance(item, dict):
                print(f"{indent}-")
                human_output(item, depth + 1)
            else:
                print(f"{indent}- {item}")
    else:
        print(f"{indent}{value}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in argv
    command = None
    result, issues, next_action, exit_code = None, [], None, 0
    try:
        parser = build_parser()
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured) if json_mode else contextlib.nullcontext():
                args = parser.parse_args(argv)
        except SystemExit as exc:
            if not json_mode:
                return int(exc.code)
            result = {"help": captured.getvalue()}
            args = None
        if args is not None:
            command = args.command + (" " + args.action if hasattr(args, "action") else "")
            result = execute(args)
            if args.command == "run":
                issues = result.pop("issues")
                exit_code = result.pop("exit_code")
            if args.command == "check" and "warnings" in result:
                issues = result.pop("warnings")
            if args.command == "foundation" and args.action == "check" and result["issues"]:
                issues = result.pop("issues")
                exit_code = 1
            if args.command == "inspect" and args.change:
                status = result["status"]
                if status != "canceled":
                    actions = {
                        "draft": ("change approve", "Review the proposal and approve the current digest"),
                        "approved": ("check --gate implement", "Check foundation, dependencies and release assignment"),
                        "in-progress": ("run verify", "Run checks for the implementation candidate"),
                        "verified": ("integrate prepare", "Prepare integration using the current run"),
                        "partially-integrated": ("status", "Inspect the gates remaining for other components"),
                        "integrated": ("run verify --release", "Verify the final release contract"),
                    }
                    next_command, reason = actions[status]
                    next_action = {"command": next_command, "reason": reason}
    except ModelError as exc:
        issues, exit_code = [exc.issue], exc.exit_code
        if hasattr(exc, "operation_id"):
            result = {"operation_id": exc.operation_id, "partial": exc.partial}
    except ConfigError as exc:
        issues, exit_code = [ModelError("INVALID_REFERENCE", str(exc)).issue], 2
    except SkillLockError as exc:
        issues, exit_code = [ModelError(exc.code, str(exc)).issue], 1
    except (OSError, subprocess.TimeoutExpired) as exc:
        issues, exit_code = [ModelError("IO_ERROR", str(exc)).issue], 4
        result = {"partial": False}
    except KeyboardInterrupt:
        issues, exit_code = [ModelError("INTERRUPTED", "Operation interrupted; inspect runtime journals before continuing").issue], 130
        parsed = locals().get("args")
        if parsed is not None:
            root = Path(parsed.path if parsed.command == "init" else parsed.project).resolve()
            pending = sorted((root / ".roclec/runtime").glob("*.json"))
            result = {"partial": bool(pending), "operation_id": pending[0].stem if len(pending) == 1 else None}
    except Exception:
        if "--debug" in argv:
            traceback.print_exc(file=sys.stderr)
        issues = [ModelError("INTERNAL_ERROR", "Unexpected internal error",
                             remediation="Repeat with --debug to inspect the traceback.").issue]
        exit_code = 70
    envelope = {"model_schema": 2, "ok": exit_code == 0, "command": command,
                "data": result, "issues": issues, "next_action": next_action}
    if json_mode:
        print(json.dumps(envelope, ensure_ascii=False, sort_keys=True, allow_nan=False))
    else:
        print(f"{command or 'roclec'}: {'OK' if exit_code == 0 else 'failed'}")
        if result is not None:
            human_output(result)
        for issue in issues:
            print(f"{issue['code']}: {issue['message']}")
            if issue["remediation"]:
                print(issue["remediation"])
        if next_action:
            print(f"Next: {next_action['command']} — {next_action['reason']}")
    return exit_code
