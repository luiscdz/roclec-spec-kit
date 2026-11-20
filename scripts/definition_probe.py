#!/usr/bin/env python3
"""Characterize three known 0.7 gaps in disposable wheel-installed consumers.

This is a definition baseline, not a passing regression suite or an agent evaluation.
Use --expect fixed to turn the same observations into a future rejection check.
No model calls, external notifications, deployments or consumer-tree edits occur.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def execute(command: list[str | Path], cwd: Path) -> tuple[int, str]:
    result = subprocess.run([str(x) for x in command], cwd=cwd, capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout + result.stderr


def require(command: list[str | Path], cwd: Path) -> str:
    code, output = execute(command, cwd)
    if code:
        raise RuntimeError(f"fixture setup failed: {' '.join(map(str, command[:4]))}: {output}")
    return output


class Consumer:
    def __init__(self, workspace: Path, cli: Path):
        self.root = workspace / 'specs'
        self.root.mkdir(parents=True)
        self.cli = cli
        self.repos = {name: workspace / name for name in ('engine', 'viewer')}
        self.commits = {}
        for component, repo in self.repos.items():
            repo.mkdir()
            (repo / 'tests').mkdir()
            (repo / 'tests/test_feature.py').write_text('# [001/AC-01]\n', encoding='utf-8')
            for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'synthetic published baseline']):
                require(['git', *args], repo)
            self.commits[component] = require(['git', 'rev-parse', 'HEAD'], repo).strip()
        self.ok('init', '.', '--name', 'Definition fixture', '--component', 'engine=../engine', '--component', 'viewer=../viewer')
        self.ok('new', '001-feature', '--title', 'Synthetic feature')
        self.folder = self.root / 'specs/001-feature'
        self.spec = self.folder / 'spec.md'
        body = self.spec.read_text(encoding='utf-8')
        body = body.replace('status: draft', 'status: ready').replace('effort: TBD', 'effort: S')
        body = body.replace('[NEEDS CLARIFICATION: define testable AC-NN scenarios before marking ready.]', '**AC-01** Original promised behavior.')
        self.spec.write_text(body, encoding='utf-8')
        (self.folder / 'plan.md').write_text('# Plan\nSynthetic two-component behavior.\n', encoding='utf-8')
        self.tasks = self.folder / 'tasks.md'
        self.tasks.write_text('- [x] T001 [engine] Original behavior [001/AC-01]\n- [x] T002 [viewer] Original behavior [001/AC-01]\n', encoding='utf-8')
        for component in self.repos:
            self.ok('release', 'plan', component, 'v1.0.0', '001')
        self.spec.write_text(self.spec.read_text(encoding='utf-8').replace('status: ready', 'status: done'), encoding='utf-8')
        for component in self.repos:
            self.complete_release_text(component, 'v1.0.0')
            self.ok('release', 'close', component, 'v1.0.0', '--commit', self.commits[component])

    def call(self, *arguments: str) -> tuple[int, str]:
        return execute([self.cli, '--project', self.root, *arguments], self.root)

    def ok(self, *arguments: str) -> str:
        code, output = self.call(*arguments)
        if code:
            raise RuntimeError(f"fixture setup failed ({arguments[:3]}): {output}")
        return output

    def complete_release_text(self, component: str, version: str) -> None:
        path = self.root / 'roadmap/releases' / component / f'{version}.md'
        body = path.read_text(encoding='utf-8').replace('- [ ] RC-01 Define publication and compatibility criteria here.', '- [x] RC-01 Synthetic fixture publication recorded.')
        path.write_text(body + '- Synthetic release notes; no real publication.\n', encoding='utf-8')


def digest(path: Path, administrative: bool = False) -> str:
    data = path.read_bytes()
    if administrative:
        text = re.sub(r'^status:.*$', 'status: <administrative>', data.decode('utf-8'), flags=re.M)
        text = re.sub(r'^(- \[)[ xX](\] T\d+\b)', r'\1 \2', text, flags=re.M)
        data = text.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def coverage_probe(consumer: Consumer) -> dict:
    consumer.spec.write_text(consumer.spec.read_text(encoding='utf-8') + '\n## Amendments\n\n### A1 — Reclaim original AC (2026-11-09)\n\n- **Components:** engine\n- **AC:** AC-01\n', encoding='utf-8')
    consumer.tasks.write_text(consumer.tasks.read_text(encoding='utf-8') + '- [ ] T003 [engine] [A1] Reuse original criterion [001/AC-01]\n', encoding='utf-8')
    for repo in consumer.repos.values():
        (repo / 'tests/test_feature.py').write_text('# No acceptance citations remain\n', encoding='utf-8')
    code, _ = consumer.call('check', '--coverage', '--write')
    return {'id': 'DEF-001', 'known_gap_observed': code == 0, 'observed_exit_code': code,
            'observation': 'Pending amendment reclaims original AC; no test cites original AC.',
            'required_behavior': 'Reject reassignment or preserve original integrated coverage obligation.'}


def review_probe(consumer: Consumer) -> dict:
    consumer.ok('review', 'enable', '001', '--reason', 'Synthetic fixture opt-in, not a real independent review')
    inputs = []
    for name in ('spec.md', 'plan.md', 'tasks.md'):
        path = consumer.folder / name
        inputs.append({'root': 'project', 'path': str(path.relative_to(consumer.root)), 'sha256': digest(path, name != 'plan.md')})
    test = consumer.repos['engine'] / 'tests/test_feature.py'
    inputs.append({'root': 'engine', 'path': 'tests/test_feature.py', 'sha256': digest(test)})
    payload = {'target': '001-feature', 'independent': True, 'verdict': 'ready', 'inputs': inputs}
    report = consumer.folder / 'reviews/implementation-engine.md'
    report.write_text('# Synthetic report fixture; no agent review executed\n\n```roclec-review\n' + json.dumps(payload) + '\n```\n', encoding='utf-8')
    before = json.loads(consumer.ok('inspect', '001', '--json'))['reviews']['engine']['state']
    if before != 'ready':
        raise RuntimeError(f'review fixture did not establish baseline ready: {before}')
    source = consumer.repos['engine'] / 'src'
    source.mkdir()
    (source / 'new_behavior.py').write_text('def behavior():\n    return "changed candidate"\n', encoding='utf-8')
    after = json.loads(consumer.ok('inspect', '001', '--json'))['reviews']['engine']['state']
    return {'id': 'DEF-002', 'known_gap_observed': after == 'ready', 'observed_review_state': after,
            'observation': 'A new implementation file is absent from the declared review inputs.',
            'required_behavior': 'Report incomplete/stale or block until file relevance and candidate are verified.'}


def fix_probe(consumer: Consumer) -> dict:
    missing = 'a' * 40
    exists, _ = execute(['git', 'cat-file', '-e', missing + '^{commit}'], consumer.repos['engine'])
    if exists == 0:
        raise RuntimeError('synthetic missing SHA unexpectedly exists')
    consumer.ok('release', 'fix', 'engine', 'v1.1.0', '001', 'Synthetic missing fix', missing)
    consumer.complete_release_text('engine', 'v1.1.0')
    code, _ = consumer.call('release', 'close', 'engine', 'v1.1.0', '--commit', consumer.commits['engine'])
    return {'id': 'DEF-003', 'known_gap_observed': code == 0, 'observed_exit_code': code,
            'observation': 'Fix cites a nonexistent commit; candidate is the original baseline commit.',
            'required_behavior': 'Reject missing/unincluded fix or require a resolvable explicit backport relation.'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--expect', choices=('vulnerable', 'fixed'), default='vulnerable')
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    data = {'kind': 'definition-baseline-characterization', 'schema': 1,
            'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'wheel': wheel.name,
            'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(), 'expectation': args.expect,
            'agent_execution': False, 'real_publication': False, 'cases': [], 'error': None}
    try:
        with tempfile.TemporaryDirectory(prefix='roclec-definition-') as workspace:
            root = Path(workspace)
            env = root / 'env'
            require([sys.executable, '-m', 'venv', env], root)
            require([env / 'bin/python', '-m', 'pip', 'install', '--no-index', '--no-deps', wheel], root)
            for name, probe in (('coverage', coverage_probe), ('review', review_probe), ('fix', fix_probe)):
                data['cases'].append(probe(Consumer(root / name, env / 'bin/roclec')))
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        data['error'] = str(exc)
    data['known_gaps_observed'] = sum(case['known_gap_observed'] for case in data['cases'])
    data['expectation_met'] = data['error'] is None and len(data['cases']) == 3 and all(case['known_gap_observed'] == (args.expect == 'vulnerable') for case in data['cases'])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print(f"Known gaps observed: {data['known_gaps_observed']}/3. Expectation {args.expect}: {'met' if data['expectation_met'] else 'not met'}.")
    if data['error']:
        print(data['error'], file=sys.stderr)
    return 0 if data['expectation_met'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
