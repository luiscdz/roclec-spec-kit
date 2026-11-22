#!/usr/bin/env python3
"""Exercise an installed wheel through real CLI subprocesses in disposable projects.

This is a deterministic integration harness, not an LLM quality benchmark.
Git publication uses disposable local remotes. No model API, deployment or
external skill restoration is used; --spec-kit needs the pinned optional CLI.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile


def execute(command, cwd):
    env = {key: value for key, value in os.environ.items() if key not in {'PYTHONPATH', 'PYTHONHOME'}}
    return subprocess.run([str(value) for value in command], cwd=cwd, env=env, capture_output=True, text=True, timeout=60)


class ViewerServers:
    """One ``roclec view`` process per project, started from a subdirectory to prove root discovery."""

    def __init__(self, cli, workspace):
        self.cli, self.workspace, self.running = cli, workspace, {}

    def url(self, root):
        root = Path(root)
        if root not in self.running:
            cwd = root / 'src' if (root / 'src').is_dir() else root
            env = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'PYTHONHOME'}}
            process = subprocess.Popen([str(self.cli), 'view', '--no-open', '--port', '0'], cwd=cwd, env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       # A harness started as a background job inherits an ignored SIGINT; Ctrl+C must behave as in a terminal.
                                       preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
            deadline, seen, found = time.time() + 30, b'', None
            while time.time() < deadline and found is None:
                ready, _, _ = select.select([process.stderr], [], [], 1)
                if ready:
                    chunk = os.read(process.stderr.fileno(), 4096)  # unbuffered: a text readline could hold the URL line back
                    seen += chunk
                    match = re.search(rb'http://127\.0\.0\.1:[0-9]+/', seen)
                    found = match.group(0).decode() if match else None
                if process.poll() is not None and found is None:
                    raise AssertionError('roclec view exited early: ' + process.stdout.read().decode() + seen.decode())
            if found is None:
                process.kill()
                raise AssertionError('roclec view did not announce a URL: ' + seen.decode())
            self.running[root] = (process, found)
        return self.running[root][1]

    def fetch(self, root, path):
        try:
            with urllib.request.urlopen(self.url(root).rstrip('/') + path, timeout=60) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            body = error.read()
            try:
                return error.code, json.loads(body)
            except ValueError:
                return error.code, None

    def stop_all(self):
        codes = []
        for process, _ in self.running.values():
            process.send_signal(signal.SIGINT)
            try:
                codes.append(process.wait(timeout=15))
            except subprocess.TimeoutExpired:
                process.kill()
                codes.append(-9)
        self.running.clear()
        return codes


def viewer_harness(wheel: Path, workspace: Path, cases: list[dict]):
    """Base wheel without the extra, then with it: the CLI stays usable and the viewer matches the CLI."""
    from c1_scenarios import init_trunk, profile
    from viewer_scenarios import partial_provenance_scenarios, published_scenarios, scenarios

    def check(name, condition, evidence=''):
        cases.append({'scope': 'viewer-native', 'name': name, 'passed': bool(condition), 'evidence': evidence})
        if not condition:
            raise AssertionError(f'{name}: {evidence}')

    workspace.mkdir()
    env = workspace / 'venv'
    check('viewer virtualenv created', execute([sys.executable, '-m', 'venv', env], workspace).returncode == 0)
    result = execute([env / 'bin/python', '-m', 'pip', 'install', '--no-index', '--no-deps', wheel], workspace)
    check('base wheel installs without the extra', result.returncode == 0, result.stdout + result.stderr)
    cli = env / 'bin/roclec'
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        check('wheel includes the compiled interface', 'roclec_spec_kit/viewer/static/index.html' in names
              and any(n.startswith('roclec_spec_kit/viewer/static/assets/') and n.endswith('.js') for n in names))
        check('wheel includes fonts and brand symbol for offline use', sum(n.endswith('.woff2') for n in names) == 2
              and any(n.endswith('.svg') and 'static/assets/roclec' in n for n in names))
        check('wheel ships no Node sources or modules', not any('node_modules' in n or n.endswith('.tsx') for n in names))
    project = workspace / 'without-extra'
    init_trunk(project)
    config = workspace / 'viewer-profile.toml'
    profile(config)
    check('viewer fixture initializes', execute([cli, '--json', 'init', project, '--profile', config], workspace).returncode == 0)
    result = execute([cli, '--json', '--project', project, 'view', '--no-open'], workspace)
    payload = json.loads(result.stdout)
    check('view without the extra explains how to install it', result.returncode == 1
          and payload['issues'][0]['code'] == 'VIEWER_UNAVAILABLE' and 'roclec-spec-kit[viewer]' in payload['issues'][0]['remediation'], result.stdout)
    check('CLI stays operational without the extra', execute([cli, '--json', '--project', project, 'check'], workspace).returncode == 0)
    result = execute([env / 'bin/python', '-m', 'pip', 'install', f'{wheel}[viewer]'], workspace)
    check('wheel installs with the viewer extra', result.returncode == 0, result.stdout[-400:] + result.stderr[-400:])
    servers = ViewerServers(cli, workspace)
    try:
        invoke = lambda argv: execute([cli, *argv], workspace)  # noqa: E731
        status, body = servers.fetch(project, '/api/v1/project')
        check('view finds the project root from a subdirectory', status == 200 and Path(body['data']['root']) == project.resolve())
        with urllib.request.urlopen(servers.url(project), timeout=30) as response:
            page = response.read().decode()
            check('interface is served locally with its security headers', response.status == 200 and '<div id="root">' in page
                  and "default-src 'self'" in response.headers['Content-Security-Policy'])
        asset = page.split('/assets/')[1].split('"')[0]
        with urllib.request.urlopen(servers.url(project) + 'assets/' + asset, timeout=30) as response:
            check('compiled assets are served without Node', response.status == 200)
        scenarios(workspace, invoke, check, servers.fetch)
        published_scenarios(workspace / 'published', invoke, check, servers.fetch)
        partial_provenance_scenarios(workspace, invoke, check, servers.fetch)
    finally:
        codes = servers.stop_all()
    check('viewer processes close cleanly on Ctrl+C', codes and all(code == 0 for code in codes), str(codes))


def native_harness(wheel: Path, workspace: Path, cases: list[dict], compatibility=False):
    from c1_scenarios import bundle, init_trunk, rejection_scenarios, scenarios, tree

    def check(name, condition, evidence=''):
        cases.append({'scope': 'C1-native', 'name': name, 'passed': bool(condition), 'evidence': evidence})
        if not condition:
            raise AssertionError(f'{name}: {evidence}')

    workspace.mkdir()
    env = workspace / 'venv'
    result = execute([sys.executable, '-m', 'venv', env], workspace)
    check('native virtualenv created', result.returncode == 0, result.stderr)
    result = execute([env / 'bin/python', '-m', 'pip', 'install', '--no-index', '--no-deps', wheel], workspace)
    check('native wheel installs without runtime dependencies', result.returncode == 0, result.stdout + result.stderr)
    cli = env / 'bin/roclec'
    with zipfile.ZipFile(wheel) as archive:
        for name in ('model.py', 'store.py', 'kernel.py', 'native_cli.py', 'verification.py', 'integration.py', 'releases.py', 'installation.py',
                     'agents.py', 'adr.py', 'findings.py', 'rejection.py', 'flow.py', 'sessions.py', 'assets/project/flow.toml',
                     'assets/project/flow-retro.md', 'assets/templates/adr-template.md',
                     'assets/project/model.md', 'assets/skills/roclec-reviewer/references/report-template.md',
                     *(f'assets/skills/roclec-{skill}/SKILL.md' for skill in ('analyze', 'clarify', 'coordinator', 'prototype', 'specify')),
                     *(f'assets/agents/{role}.md' for role in ('coordinator', 'specifier', 'implementer', 'reviewer'))):
            check('wheel includes ' + name, 'roclec_spec_kit/' + name in archive.namelist())
    scenarios(workspace, lambda argv: execute([cli, *argv], workspace), check)
    from c1_scenarios import adr_scenarios as c1_adr_scenarios
    c1_adr_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), check)
    rejection_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), check,
                        lambda code, argv: execute([env / 'bin/python', '-c', code, *argv], workspace))
    from c2_scenarios import (scenarios as c2_scenarios, execution_scenarios, conflict_scenarios, edge_scenarios,
                              branch_scenarios, findings_scenarios, flow_scenarios, session_scenarios)

    def c2_check(name, condition, evidence=''):
        cases.append({'scope': 'C2-native', 'name': name, 'passed': bool(condition), 'evidence': evidence})
        if not condition:
            raise AssertionError(f'{name}: {evidence}')

    c2_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c2_check)
    branch_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c2_check)
    findings_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c2_check)
    flow_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c2_check)
    session_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c2_check)
    execution_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c2_check)
    from c2_faults import capture_scenarios, lock_scenarios, scenarios as fault_scenarios
    fault_scenarios(workspace, lambda argv: execute([cli, *argv], workspace),
                    lambda code, argv: execute([env / 'bin/python', '-c', code, *argv], workspace), c2_check)
    capture_scenarios(workspace, lambda argv: execute([cli, *argv], workspace),
                      lambda code, argv: execute([env / 'bin/python', '-c', code, *argv], workspace), c2_check)
    lock_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c2_check)
    def race(commands):
        clean_env = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'PYTHONHOME'}}
        processes = [subprocess.Popen([str(cli), *argv], cwd=workspace, env=clean_env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for argv in commands]
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=60)
            results.append(subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr))
        return results
    conflict_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c2_check, race=race)
    edge_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c2_check)
    from c2_scenarios import adr_scenarios as c2_adr_scenarios
    c2_adr_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c2_check)
    from c3_scenarios import combined_and_fix_scenarios as c3_scenarios
    def c3_check(name, condition, evidence=''):
        cases.append({'scope': 'C3-native', 'name': name, 'passed': bool(condition), 'evidence': evidence})
        if not condition:
            raise AssertionError(f'{name}: {evidence}')
    c3_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c3_check)
    from c3_scenarios import review_scenarios
    review_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c3_check)
    from c3_scenarios import adr_scenarios as c3_adr_scenarios
    c3_adr_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c3_check)
    from c3_scenarios import hook_scenarios
    hook_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c3_check)
    from c3_scenarios import session_release_scenarios
    session_release_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c3_check)
    from c3_installation import scenarios as install_scenarios, verified_restore_scenarios
    verified_restore_scenarios(workspace, lambda argv: execute([cli, *argv], workspace),
                               lambda code, argv: execute([env / 'bin/python', '-c', code, *argv], workspace), c3_check)
    install_scenarios(workspace, lambda argv: execute([cli, *argv], workspace), c3_check, compatibility=compatibility)
    from c3_faults import scenarios as c3_faults
    c3_faults(workspace, lambda argv: execute([cli, *argv], workspace),
              lambda code, argv: execute([env / 'bin/python', '-c', code, *argv], workspace), c3_check)
    # Inject a deterministic IO failure into the installed wheel, then recover
    # using the unmodified public CLI in a separate process. This is test setup,
    # not a production fault-injection option or a source-tree import.
    recovery_root = workspace / 'recovery'
    init_trunk(recovery_root)
    profile = workspace / 'profile.toml'
    result = execute([cli, '--json', 'init', recovery_root, '--profile', profile], workspace)
    check('recovery fixture initialized', result.returncode == 0, result.stdout + result.stderr)
    source = workspace / 'recovery-input'
    bundle(source)
    injector = '''
import sys
from unittest.mock import patch
from roclec_spec_kit.store import Store
from roclec_spec_kit.cli import main
original = Store._atomic
count = 0
def failing(store, path, content):
    global count
    count += 1
    if count == 3:
        raise OSError("harness injected IO failure")
    return original(store, path, content)
with patch.object(Store, "_atomic", failing):
    raise SystemExit(main(sys.argv[1:]))
'''
    args = ['--project', str(recovery_root), '--json']
    failed = execute([env / 'bin/python', '-c', injector, *args, 'change', 'new', '--file', source / 'change.json'], workspace)
    record = json.loads(failed.stdout)
    check('installed wheel reports partial write', failed.returncode == 4 and record['data']['partial'], failed.stdout + failed.stderr)
    operation_id = record['data']['operation_id']
    result = execute([cli, *args, 'operation', 'recover', operation_id], workspace)
    check('public CLI recovers installed-wheel failure', result.returncode == 0, result.stdout + result.stderr)
    before = tree(recovery_root)
    result = execute([cli, *args, 'operation', 'recover', operation_id], workspace)
    check('repeated recovery has no additional effects', result.returncode == 0 and tree(recovery_root) == before, result.stdout)
    result = execute([cli, *args, 'check'], workspace)
    check('recovered project validates', result.returncode == 0, result.stdout + result.stderr)
    check('C1 never advances an integrated contract itself', not (recovery_root / '.roclec/contracts').exists())


def legacy_harness(wheel: Path, workspace: Path, cases: list[dict], compatibility: bool):
    workspace.mkdir()
    def check(name, condition, evidence=''):
        cases.append({'scope': 'legacy-regression-not-C1-adapter', 'name': name, 'passed': bool(condition), 'evidence': evidence})
        if not condition:
            raise AssertionError(f'{name}: {evidence}')

    with zipfile.ZipFile(wheel) as archive:
        contents = archive.namelist()
        check('wheel includes native stages and attribution', all(any(item.endswith(suffix) for item in contents) for suffix in (
            'skills/roclec-constitution/SKILL.md', 'skills/roclec-checklist/SKILL.md',
            'skills/roclec-reviewer/references/report-template.md', 'templates/spec-template.md', 'notices/spec-kit-LICENSE.txt', 'notices/spec-kit-provenance.json')))
    root = workspace / 'product specs'
    backend = workspace / 'service'
    client = workspace / 'client'
    for folder in (root, backend, client):
        folder.mkdir()
    result = execute([sys.executable, '-m', 'venv', root / '.venv'], workspace)
    check('project virtualenv created', result.returncode == 0, result.stderr)
    result = execute([root / '.venv/bin/python', '-m', 'pip', 'install', '--no-index', '--no-deps', wheel], root)
    check('wheel installs without runtime dependencies', result.returncode == 0, result.stdout + result.stderr)
    cli = root / '.venv/bin/roclec'
    # A shim only inside this disposable regression venv. The actual installed
    # public entrypoint is exercised separately by native_harness above.
    python = root / '.venv/bin/python'
    entrypoint = 'from roclec_spec_kit.cli import legacy_main; raise SystemExit(legacy_main())'
    cli.write_text('#!/bin/sh\nexec ' + shlex.quote(str(python)) + ' -c ' + shlex.quote(entrypoint) + ' "$@"\n')

    def call(name, *arguments, expect=0, cwd=root, needle=None, launcher=None):
        result = execute([launcher or cli, *arguments], cwd)
        output = result.stdout + result.stderr
        check(name, result.returncode == expect and (needle is None or needle in output), output)
        return output

    (root / 'AGENTS.md').write_text('# Existing team rules\n', encoding='utf-8')
    call('initialize arbitrary components', 'init', '.', '--name', 'Harness', '--component', 'service=../service',
         '--component', 'client=../client', '--user-facing', 'client')
    call('install skills and link code repository', 'skills', '--into', str(backend))
    check('consumer instructions preserved', (root / 'AGENTS.md').read_text().startswith('# Existing team rules'))
    check('local feature selection ignored by git', '.roclec/feature.json' in (root / '.gitignore').read_text())
    for host in ('.agents', '.claude'):
        check(f'{host} has all native stages', len(list((root / host / 'skills').glob('roclec-*/SKILL.md'))) == 17)
    call('create selected draft', 'new', '001-save', '--title', 'Save # record')
    folder = root / 'specs/001-save'
    spec = folder / 'spec.md'
    tasks = folder / 'tasks.md'
    review = folder / 'prototype/review.md'
    release_service = root / 'roadmap/releases/service/v0.1.0.md'
    release_client = root / 'roadmap/releases/client/v0.1.0.md'
    call('linked launcher reads shared selection', 'inspect', '--json', cwd=backend, launcher=backend / '.roclec/run', needle='001-save')

    def snapshot():
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file() and '.venv' not in p.parts and '.git' not in p.parts}

    before = snapshot()
    call('reject stage skip', 'transition', '001', 'in-progress', expect=2, needle='cannot transition')
    check('rejected transition changes no lifecycle files', snapshot() == before)
    call('reject unresolved clarification', 'transition', '001', 'clarified', expect=2, needle='clarification')
    body = spec.read_text().replace('[NEEDS CLARIFICATION: define testable AC-NN scenarios before marking ready.]', '')
    spec.write_text(body.replace('effort: TBD', 'effort: S'))
    call('commented AC example does not satisfy gate', 'check', '--gate', '001', expect=1, needle='no AC-NN')
    spec.write_text(spec.read_text().replace('## Acceptance Criteria', '## Acceptance Criteria\n\n**AC-01** Given a record, when saved, then both clients can read it.'))
    call('settle draft scope', 'transition', '001', 'clarified')
    (folder / 'ux.md').write_text('# UX\nSave confirmation and recoverable errors.\n')
    review.parent.mkdir()
    (folder / 'prototype/index.html').write_text('<!doctype html><title>Save</title><button>Save</button>')
    review.write_text('**Status:** pending\n')
    call('reject pending prototype review', 'check', '--gate', '001', expect=1, needle='user approval')
    review.write_text('**Status:** approved\n**Reviewer:** Harness fixture\n**Decision:** Synthetic approval for tests.\n')
    call('ready inputs pass', 'check', '--gate', '001')
    call('create shared plan artifact', 'artifact', '001', 'plan')
    call('refuse to overwrite plan', 'artifact', '001', 'plan', expect=2, needle='will not overwrite')
    (folder / 'plan.md').write_text('# Plan\nservice owns persistence; client reads the saved record.\n')
    call('mark plan ready', 'transition', '001', 'ready')
    call('create shared task artifact', 'artifact', '001', 'tasks')
    call('commented task example does not satisfy gate', 'check', '--release-gate', '001', expect=1, needle='at least one task')
    tasks.write_text('- [ ] T001 [service] [US1] Implement save.py [001/AC-01]\n- [ ] T002 [client] [US1] Implement save.ts [001/AC-01]\n')

    def fault(name, path, mutation, arguments, needle, expected=1):
        original = path.read_text()
        path.write_text(mutation(original))
        before = snapshot()
        try:
            call(name, *arguments, expect=expected, needle=needle)
            check(name + ': no state mutation', snapshot() == before)
        finally:
            path.write_text(original)

    fault('reject unresolved effort', spec, lambda s: s.replace('effort: S', 'effort: TBD'), ('check', '--gate', '001'), 'effort must be estimated')
    fault('reject duplicate task IDs', tasks, lambda s: s.replace('T002', 'T001'), ('check', '--release-gate', '001'), 'duplicate task id')
    fault('reject multiple task owners', tasks, lambda s: s.replace('[service]', '[service] [specs]'), ('check', '--release-gate', '001'), 'exactly one')
    fault('reject unknown AC citations', tasks, lambda s: s.replace('AC-01', 'AC-99'), ('check', '--release-gate', '001'), 'unknown [001/AC-99]')
    call('reject implementation without releases', 'transition', '001', 'in-progress', expect=2, needle='release assignment')
    call('select service release', 'release', 'plan', 'service', 'v0.1.0', '001')
    call('reject partial component release coverage', 'transition', '001', 'in-progress', expect=2, needle='missing client release')
    call('select independent client release', 'release', 'plan', 'client', 'v0.1.0', '001')
    duplicate = root / 'roadmap/releases/service/v0.2.0.md'
    duplicate.write_text(release_service.read_text().replace('service v0.1.0', 'service v0.2.0'))
    before = snapshot()
    call('reject duplicate release assignment', 'transition', '001', 'in-progress', expect=2, needle='assigned to service')
    check('duplicate assignment rejection does not mutate state', snapshot() == before)
    duplicate.unlink()
    call('all implementation prerequisites pass', 'check', '--release-gate', '001')
    call('begin implementation from linked repo', 'transition', '001', 'in-progress', cwd=backend, launcher=backend / '.roclec/run')
    call('reject done with open tasks', 'transition', '001', 'done', expect=2, needle='every task checked')
    tasks.write_text(tasks.read_text().replace('[ ]', '[x]'))
    call('reject done without test traceability', 'transition', '001', 'done', expect=2, needle='test does not cite')
    for repo in (backend, client):
        tests = repo / 'tests'
        tests.mkdir()
        (tests / 'test_record.py').write_text('import unittest\n\nclass SaveTest(unittest.TestCase):\n    def test_save_roundtrip(self):\n        # [001/AC-01]\n        records = {}\n        records[1] = {"name": "Record"}\n        self.assertEqual(records[1]["name"], "Record")\n')
        result = execute([root / '.venv/bin/python', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], repo)
        check(f'{repo.name} fixture tests execute', result.returncode == 0, result.stdout + result.stderr)
    call('complete spec after citations exist', 'transition', '001', 'done')
    call('validate done coverage and views', 'check', '--coverage')
    call('reject open release criteria', 'release', 'close', 'service', 'v0.1.0', expect=2, needle='release criteria')
    for component, release in (('service', release_service), ('client', release_client)):
        release.write_text(release.read_text().replace('- [ ] RC-01 Define publication and compatibility criteria here.', '- [x] RC-01 Published with backward-compatible rollout.'))
        call(f'reject {component} closure without notes', 'release', 'close', component, 'v0.1.0', expect=2, needle='Release Notes')
        release.write_text(release.read_text() + '- Record saving published.\n')
        repo = backend if component == 'service' else client
        for command in (['git', 'init', '-q'], ['git', 'add', '.'], ['git', '-c', 'user.name=Harness', '-c', 'user.email=harness@example.invalid', 'commit', '-qm', 'shipped']):
            result = execute(command, repo)
            check('code git fixture ' + component + command[1], result.returncode == 0, result.stderr)
        sha = execute(['git', 'rev-parse', 'HEAD'], repo).stdout.strip()
        call(f'close published {component} fixture', 'release', 'close', component, 'v0.1.0', '--commit', sha)
    call('refuse adding specs to released version', 'release', 'plan', 'service', 'v0.1.0', '001', expect=2, needle='immutable')
    for command in (['git', 'init', '-q'], ['git', 'add', '.'], ['git', '-c', 'user.name=Harness', '-c', 'user.email=harness@example.invalid', 'commit', '-qm', 'published fixture']):
        result = execute(command, root)
        check('git fixture ' + command[1], result.returncode == 0, result.stderr)
    fault('detect edited published release', release_service, lambda s: s + '\nmanual edit\n', ('check', '--immutable-base', 'HEAD'), 'released file changed')
    roadmap = root / 'roadmap/ROADMAP.md'
    fault('detect hand-edited generated view', roadmap, lambda s: s + '\nmanual edit\n', ('check',), 'stale')
    template = root / '.roclec/templates/plan-template.md'
    template.write_text('# Project-custom plan\n')
    call('refresh managed skills', 'skills')
    check('refresh preserves project-owned template', template.read_text() == '# Project-custom plan\n')
    reviewer_reference = root / '.agents/skills/roclec-reviewer/references/report-template.md'
    check('review reference installed', reviewer_reference.is_file())
    call('opt in review without global closure gate', 'review', 'enable', '001', '--reason', 'Synthetic user request')
    review_data = json.loads(call('inspect optional review', 'inspect', '001', '--json'))
    check('missing opted-in reviews reported', review_data['reviews']['service']['state'] == 'missing')
    call('end optional review preserves evidence', 'review', 'disable', '001', '--reason', 'Synthetic pilot ended')
    spec.write_text(spec.read_text() + '\n**AC-02** Existing record can be corrected.\n\n## Amendments\n\n### A1 — Correct record (2026-11-07)\n\n- **Components:** service\n- **AC:** AC-02\n')
    tasks.write_text(tasks.read_text() + '- [ ] T003 [service] [A1] Correct record [001/AC-02]\n')
    call('original remains done with pending amendment', 'check', '--write')
    before = snapshot()
    call('amendment implementation requires assignment', 'check', '--release-gate', '001-A1', expect=1, needle='release assignment')
    check('amendment gate rejection leaves files intact', snapshot() == before)
    call('plan independent amendment release', 'release', 'plan', 'service', 'v0.2.0', '001-A1')
    call('select amendment explicitly', 'use', '001-A1')
    amendment = json.loads(call('inspect saved amendment', 'inspect', '--json'))
    check('amendment identity survives selection', amendment['spec'] == '001-save-A1')
    call('amendment implementation gate passes', 'check', '--release-gate', '001-A1')
    tasks.write_text(tasks.read_text().replace('- [ ] T003', '- [x] T003'))
    fixture_test = backend / 'tests/test_record.py'
    fixture_test.write_text(fixture_test.read_text() + '\n# [001/AC-02] Synthetic amendment traceability\n')
    call('completed amendment needs its component test citation', 'check', '--coverage', '--write')
    amendment_release = root / 'roadmap/releases/service/v0.2.0.md'
    amendment_release.write_text(amendment_release.read_text().replace('- [ ] RC-01 Define publication and compatibility criteria here.', '- [x] RC-01 Published correction feature.') + '- Record correction available.\n')
    execute(['git', 'add', '.'], backend)
    result = execute(['git', '-c', 'user.name=Harness', '-c', 'user.email=harness@example.invalid', 'commit', '-qm', 'amendment fixture'], backend)
    check('amendment fixture committed', result.returncode == 0, result.stderr)
    sha = execute(['git', 'rev-parse', 'HEAD'], backend).stdout.strip()
    call('close amendment-only release', 'release', 'close', 'service', 'v0.2.0', '--commit', sha)
    result = execute(['git', 'tag', 'v0.2.0', sha], backend)
    check('synthetic published base tag prepared', result.returncode == 0, result.stderr)
    call('plan bugfix-only release', 'release', 'fix', 'service', 'v0.2.1', '001', 'Restore promised behavior', sha, '--kind', 'bugfix', '--base-tag', 'v0.2.0')
    correction = root / 'roadmap/releases/service/v0.2.1.md'
    correction.write_text(correction.read_text().replace('- [ ] RC-01 Define publication and compatibility criteria here.', '- [x] RC-01 Published bugfix.') + '- Restored behavior.\n')
    call('close bugfix-only release', 'release', 'close', 'service', 'v0.2.1', '--commit', sha)
    check('closing does not create tags', not execute(['git', 'tag', '--list', 'v0.2.1'], backend).stdout.strip())
    config = root / '.roclec/project.toml'
    config.write_text(config.read_text() + '\n[components.client.product]\n')
    (root / 'product').mkdir()
    (root / 'product/core.md').write_text('# Shared\n\n## Users\n\nOperators\n')
    (root / 'product/client.md').write_text('# Client\n\n## Platform\n\nweb\n\n## Stack\n\nFixture stack\n')
    call('product detects missing generated view', 'product', expect=1, needle='stale')
    call('generate optional component product', 'product', '--write')
    check('optional product view installed', (root / 'components/client/PRODUCT.md').is_file())
    call('create maintenance draft', 'new', '002-maintenance', '--title', 'Maintenance', '--component', 'client')
    maintenance = root / 'specs/002-maintenance'
    maintenance_spec = maintenance / 'spec.md'
    maintenance_spec.write_text(maintenance_spec.read_text().replace('effort: TBD', 'effort: S').replace('[NEEDS CLARIFICATION: define testable AC-NN scenarios before marking ready.]', '**AC-01** Existing screen remains usable.'))
    (maintenance / 'ux.md').write_text('# UX\nExisting screen states only.\n')
    (maintenance / 'prototype').mkdir()
    (maintenance / 'prototype/review.md').write_text('**Status:** approved\n**Reviewer:** Harness fixture\n**Decision:** Existing prototype covers this synthetic scope.\n')
    (maintenance / 'prototype/references.md').write_text('[Existing](../../001-save/prototype/index.html)\n')
    call('maintenance reuses approved prototype', 'check', '--gate', '002')
    call('clarify maintenance fixture', 'transition', '002', 'clarified')
    call('write final views after maintenance', 'check', '--write')
    call('final native project is consistent' , 'check', '--coverage', '--immutable-base', 'HEAD')
    if compatibility:
        for integration in ('codex', 'claude'):
            compat = workspace / f'compat-{integration}'
            compat.mkdir()
            result = execute(['specify', 'init', '--here', '--integration', integration, '--ignore-agent-tools'], compat)
            check(f'initialize optional {integration} integration', result.returncode == 0, result.stdout + result.stderr)
            call(f'initialize Roclec for {integration}', 'init', '.', '--name', 'Compatibility', cwd=compat)
            call(f'install generated {integration} aliases', 'speckit', cwd=compat)
            call(f'create {integration} selected feature', 'new', '001-native', '--title', 'Native alias', cwd=compat)
            context = json.loads((compat / '.specify/feature.json').read_text())
            check(f'{integration} feature context mirrored', context['feature_directory'] == 'specs/001-native')
            preset_body = (compat / '.specify/presets/roclec/commands/speckit.plan.md').read_text()
            native_body = (compat / '.agents/skills/roclec-plan/SKILL.md').read_text().split('\n---\n', 1)[1].lstrip()
            check(f'{integration} alias uses canonical native instructions', preset_body.endswith(native_body))
            reviewer = (compat / '.specify/extensions/roclec/commands/speckit.roclec.reviewer.md').read_text()
            check(f'{integration} reviewer reference resolves', str(compat / '.agents/skills/roclec-reviewer/references/report-template.md') in reviewer and (compat / '.agents/skills/roclec-reviewer/references/report-template.md').is_file())
            call(f'refresh {integration} aliases without duplicates', 'speckit', cwd=compat)
            rendered = list((compat / ('.agents' if integration == 'codex' else '.claude') / 'skills').glob('speckit-plan/SKILL.md'))
            check(f'{integration} installed plan skill references guarded transition', bool(rendered) and 'transition NNN ready' in rendered[0].read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--spec-kit', action='store_true', help='Also verify optional aliases with installed specify-cli 0.13.4')
    parser.add_argument('--viewer', action='store_true', help='Also verify `roclec view` from the wheel with the viewer extra (needs a package index for Flask)')
    parser.add_argument('--viewer-only', action='store_true', help='With --viewer, skip the native CLI harness')
    parser.add_argument('--legacy', action='store_true', help='Also retain pre-redesign regressions; no schema-1 public CLI')
    args = parser.parse_args()
    cases = []
    failure = None
    try:
        with tempfile.TemporaryDirectory(prefix='roclec-harness-') as directory:
            if not (args.viewer and args.viewer_only):
                native_harness(args.wheel.resolve(), Path(directory) / 'native', cases, args.spec_kit)
            if args.viewer:
                viewer_harness(args.wheel.resolve(), Path(directory) / 'viewer', cases)
            if args.legacy or args.spec_kit:
                legacy_harness(args.wheel.resolve(), Path(directory) / 'legacy', cases, args.spec_kit)
    except (AssertionError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        failure = str(exc)
    report = {'schema': 1, 'timestamp': datetime.now(timezone.utc).isoformat(), 'wheel': args.wheel.name,
              'wheel_sha256': hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
              'kind': 'deterministic integration; no agent execution', 'spec_kit': args.spec_kit,
              'native_adapter': 'canonical profile-3 C3 skills/aliases; Codex/Claude integration exercised with --spec-kit',
              'publication_scope': 'real Git operations on disposable local remotes; no package/product publication or deployment',
              'passed': failure is None, 'cases': cases, 'failure': failure}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f"{sum(case['passed'] for case in cases)}/{len(cases)} checks passed; report: {args.report.resolve()}")
    if failure:
        print(failure, file=sys.stderr)
    return 0 if failure is None else 1


if __name__ == '__main__':
    raise SystemExit(main())
