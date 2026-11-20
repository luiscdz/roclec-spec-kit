from pathlib import Path
from dataclasses import replace
import json
import subprocess
import tempfile
import unittest

from test_workflow import run
from roclec_spec_kit.config import load_project
from roclec_spec_kit.workflow import scan, check_coverage, version_key


class PostReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repos = {c: self.root / c for c in ('engine', 'viewer')}
        for repo in self.repos.values():
            repo.mkdir()
            subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
            (repo / 'tests').mkdir()
            (repo / 'tests/test_feature.py').write_text('# [001/AC-01]\n')
            self.git(repo, 'add', '.')
            self.git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'published')
        self.assertEqual(run('init', str(self.root), '--name', 'Consumer', '--component', 'engine=engine', '--component', 'viewer=viewer')[0], 0)
        self.assertEqual(self.call('new', '001-example', '--title', 'Example')[0], 0)
        self.folder = self.root / 'specs/001-example'
        spec = self.folder / 'spec.md'
        spec.write_text(spec.read_text().replace('status: draft', 'status: ready').replace('effort: TBD', 'effort: S').replace('[NEEDS CLARIFICATION: define testable AC-NN scenarios before marking ready.]', '**AC-01** Original behavior.'))
        (self.folder / 'plan.md').write_text('# Plan\n')
        self.tasks = self.folder / 'tasks.md'
        self.tasks.write_text('- [x] T001 [engine] Original [001/AC-01]\n- [x] T002 [viewer] Original [001/AC-01]\n')
        for c in self.repos:
            self.ok('release', 'plan', c, 'v1.0.0', '001')
        spec.write_text(spec.read_text().replace('status: ready', 'status: done'))
        for c in self.repos:
            self.finish(c, 'v1.0.0')
            self.git(self.repos[c], 'tag', 'v1.0.0')

    def git(self, repo, *args):
        return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()

    def call(self, *args):
        return run('--project', str(self.root), *args)

    def ok(self, *args):
        code, output = self.call(*args)
        self.assertEqual(code, 0, output)
        return output

    def finish(self, component, version):
        path = self.root / 'roadmap/releases' / component / (version + '.md')
        path.write_text(path.read_text().replace('- [ ] RC-01 Define publication and compatibility criteria here.', '- [x] RC-01 Published and compatible.') + '- Shipped user behavior.\n')
        self.ok('release', 'close', component, version, '--commit', self.git(self.repos[component], 'rev-parse', 'HEAD'))

    def amend(self, components='engine, viewer'):
        p = self.folder / 'spec.md'
        p.write_text(p.read_text() + '\n**AC-02** New behavior.\n\n## Amendments\n\n### A1 — Extension (2026-11-07)\n\n- **Components:** ' + components + '\n- **AC:** AC-02\n')
        self.tasks.write_text(self.tasks.read_text() + ''.join(f'- [ ] T00{i+3} [{c.strip()}] [A1] Extend [001/AC-02]\n' for i, c in enumerate(components.split(','))))

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file() and '.git' not in p.parts}

    def test_amendment_component_completion_does_not_reopen_original(self):
        self.amend()
        self.ok('check', '--write')
        self.assertEqual(self.call('check', '--release-gate', '001-A1')[0], 1)
        for c in self.repos:
            self.ok('release', 'plan', c, 'v1.1.0', '001-A1')
        self.ok('use', '001-A1')
        data = json.loads(self.ok('inspect', '--json'))
        self.assertEqual(data['spec'], '001-example-A1')
        self.ok('check', '--release-gate', '001-A1')
        self.tasks.write_text(self.tasks.read_text().replace('- [ ] T003', '- [x] T003'))
        (self.repos['engine'] / 'tests/test_feature.py').write_text('# [001/AC-01] [001/AC-02]\n')
        state = scan(load_project(self.root))
        self.assertEqual(check_coverage(load_project(self.root), state), [])
        self.finish('engine', 'v1.1.0')
        self.assertEqual(self.call('release', 'close', 'viewer', 'v1.1.0')[0], 2)
        self.assertIn('status: done', (self.folder / 'spec.md').read_text())

    def test_rejections_leave_consumer_unchanged(self):
        self.amend('engine')
        for args in [('release', 'plan', 'engine', 'v1.0.0', '001-A1'),
                     ('release', 'plan', 'engine', 'v1.1.2', '001-A1'),
                     ('release', 'plan', 'engine', 'v1.1', '001-A1'),
                     ('release', 'plan', 'viewer', 'v1.1.0', '001-A1')]:
            before = self.snapshot()
            self.assertEqual(self.call(*args)[0], 2)
            self.assertEqual(before, self.snapshot())

    def test_corrections_require_base_tag_only_fixes_and_publication_evidence(self):
        self.ok('release', 'fix', 'engine', 'v1.0.2', '001', 'Restore behavior', '--kind', 'bugfix', '--base-tag', 'v1.0.0')
        path = self.root / 'roadmap/releases/engine/v1.0.2.md'
        path.write_text(path.read_text().replace('- [ ] RC-01 Define publication and compatibility criteria here.', '- [x] RC-01 Published.') + '- Fixed behavior.\n')
        before = self.snapshot()
        self.assertEqual(self.call('release', 'close', 'engine', 'v1.0.2', '--commit', self.git(self.repos['engine'], 'rev-parse', 'HEAD'))[0], 2)
        self.assertEqual(before, self.snapshot())
        self.ok('release', 'fix', 'engine', 'v1.0.2', '001', 'Restore documented behavior', self.git(self.repos['engine'], 'rev-parse', 'HEAD'))
        # Remove the original unreferenced draft fix before publishing.
        path.write_text(path.read_text().replace('- [001](../../../specs/001-example/spec.md) — Restore behavior\n', ''))
        self.finish('engine', 'v1.0.2')
        self.assertFalse(self.git(self.repos['engine'], 'tag', '--list', 'v1.0.2'))

    def test_invalid_correction_lines_and_version_resets(self):
        for version, kind, base in [('v1.0.0', 'hotfix', 'v1.0.0'), ('v1.1.1', 'hotfix', 'v1.0.0'),
                                    ('v1.0.1', 'hotfix', 'v1.0.9'), ('v2.1.0', 'release', '')]:
            before = self.snapshot()
            args = ['release', 'fix', 'viewer', version, '-', 'Fix', '--kind', kind]
            if base:
                args += ['--base-tag', base]
            self.assertEqual(self.call(*args)[0], 2)
            self.assertEqual(before, self.snapshot())
        self.ok('release', 'fix', 'engine', 'v2.0.0', '-', 'Restore ancillary behavior', 'abcdef0')

    def test_duplicate_or_unknown_amendment_and_coverage_fail(self):
        self.amend()
        p = self.folder / 'spec.md'
        p.write_text(p.read_text().replace('- **AC:** AC-02', '- **AC:** AC-99'))
        self.assertIn('exclusive new AC', self.call('check')[1])
        p.write_text(p.read_text().replace('- **AC:** AC-99', '- **AC:** AC-02'))
        self.tasks.write_text(self.tasks.read_text().replace('[A1]', '[A9]'))
        self.assertIn('unknown or multiple amendment', self.call('check')[1])
        self.assertEqual(version_key('v1.2'), version_key('v1.2.0'))

    def test_tag_collision_and_unknown_commit_rejected(self):
        self.ok('release', 'fix', 'engine', 'v1.1.0', '-', 'Fix', 'abcdef0')
        p = self.root / 'roadmap/releases/engine/v1.1.0.md'
        p.write_text(p.read_text().replace('- [ ] RC-01 Define publication and compatibility criteria here.', '- [x] RC-01 Published.') + '- Fixed.\n')
        before = self.snapshot()
        self.assertEqual(self.call('release', 'close', 'engine', 'v1.1.0', '--commit', 'a'*40)[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_legacy_versions_remain_readable_and_normalized_duplicates_fail(self):
        for c in self.repos:
            p = self.root / 'roadmap/releases' / c / 'v1.0.0.md'
            body = p.read_text().replace('**Kind:** release\n', '')
            legacy = p.with_name('v1.0.md')
            p.rename(legacy)
            legacy.write_text(body.replace(f'{c} v1.0.0 —', f'{c} v1.0 —'))
        self.ok('check', '--coverage', '--write')
        original = self.root / 'roadmap/releases/engine/v1.0.md'
        duplicate = original.with_name('v1.0.0.md')
        duplicate.write_text(original.read_text().replace('engine v1.0 —', 'engine v1.0.0 —'))
        self.assertIn('ambiguous normalized version', self.call('check')[1])

    def test_latest_tag_check_does_not_invalidate_published_corrections(self):
        sha = self.git(self.repos['engine'], 'rev-parse', 'HEAD')
        self.ok('release', 'fix', 'engine', 'v1.0.1', '001', 'Restore behavior', sha, '--kind', 'hotfix', '--base-tag', 'v1.0.0')
        self.finish('engine', 'v1.0.1')
        self.git(self.repos['engine'], 'tag', 'v1.0.1')
        before = self.snapshot()
        self.assertEqual(self.call('release', 'fix', 'engine', 'v1.0.2', '001', 'Restore behavior', sha, '--kind', 'bugfix', '--base-tag', 'v1.0.0')[0], 2)
        self.assertEqual(before, self.snapshot())
        self.ok('release', 'fix', 'engine', 'v1.0.2', '001', 'Restore behavior', sha, '--kind', 'bugfix', '--base-tag', 'v1.0.1')
        self.finish('engine', 'v1.0.2')
        self.git(self.repos['engine'], 'tag', 'v1.0.2')
        self.ok('check', '--write')

    def test_multiple_amendments_have_separate_selection_and_coverage(self):
        self.amend('engine')
        p = self.folder / 'spec.md'
        p.write_text(p.read_text().replace('## Amendments', '**AC-03** Another extension.\n\n## Amendments') + '\n### A2 — Another extension (2026-11-07)\n\n- **Components:** viewer\n- **AC:** AC-03\n')
        self.tasks.write_text(self.tasks.read_text() + '- [ ] T004 [viewer] [A2] Extend [001/AC-03]\n')
        self.ok('release', 'plan', 'engine', 'v1.1.0', '001-A1')
        self.ok('release', 'plan', 'viewer', 'v1.1.0', '001-A2')
        self.ok('use', '001-A2')
        self.assertEqual(json.loads(self.ok('inspect', '--json'))['spec'], '001-example-A2')
        self.tasks.write_text(self.tasks.read_text().replace('- [ ] T003', '- [x] T003'))
        errors = check_coverage(load_project(self.root), scan(load_project(self.root)))
        self.assertEqual(len(errors), 1)
        self.assertIn('engine test does not cite [001/AC-02]', errors[0])
        self.assertNotIn('AC-03', ' '.join(errors))

    def test_existing_tag_on_different_commit_is_rejected(self):
        self.ok('release', 'fix', 'engine', 'v1.1.0', '-', 'Fix', 'abcdef0')
        repo = self.repos['engine']
        self.git(repo, 'tag', 'v1.1.0')
        (repo / 'fix.txt').write_text('Published correction')
        self.git(repo, 'add', '.')
        self.git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fix')
        p = self.root / 'roadmap/releases/engine/v1.1.0.md'
        p.write_text(p.read_text().replace('- [ ] RC-01 Define publication and compatibility criteria here.', '- [x] RC-01 Published.') + '- Fixed.\n')
        before = self.snapshot()
        code, output = self.call('release', 'close', 'engine', 'v1.1.0', '--commit', self.git(repo, 'rev-parse', 'HEAD'))
        self.assertEqual(code, 2)
        self.assertIn('tag collision', output)
        self.assertEqual(before, self.snapshot())
