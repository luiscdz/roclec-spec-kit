from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import test_post_release as fixtures
from roclec_spec_kit.reviews import fingerprint, report_path
from roclec_spec_kit.config import load_project
from roclec_spec_kit.workflow import scan
from roclec_spec_kit.adapter import generate_adapter


class ReviewTest(unittest.TestCase):
    setUp = fixtures.PostReleaseTest.setUp
    call = fixtures.PostReleaseTest.call
    ok = fixtures.PostReleaseTest.ok
    git = fixtures.PostReleaseTest.git
    finish = fixtures.PostReleaseTest.finish

    def inspect(self):
        return json.loads(self.ok('inspect', '001', '--json'))

    def report(self, component='engine', verdict='ready'):
        project = load_project(self.root)
        spec = scan(project).specs[0]
        inputs = []
        for name in ('spec.md', 'plan.md', 'tasks.md'):
            p = self.folder / name
            inputs.append({'root': 'project', 'path': str(p.relative_to(self.root)), 'sha256': fingerprint(p, name != 'plan.md')})
        p = self.repos[component] / 'tests/test_feature.py'
        inputs.append({'root': component, 'path': str(p.relative_to(self.repos[component])), 'sha256': fingerprint(p)})
        data = {'target': spec.target, 'independent': True, 'verdict': verdict, 'inputs': inputs}
        target = report_path(spec, component)
        target.parent.mkdir(exist_ok=True)
        target.write_text('# Review\n\n```roclec-review\n' + json.dumps(data) + '\n```\n')
        return target

    def test_opt_in_fresh_stale_and_disabled(self):
        self.assertEqual(self.inspect()['reviews']['engine']['state'], 'disabled')
        self.ok('review', 'enable', '001', '--reason', 'User request')
        self.assertEqual(self.inspect()['reviews']['engine']['state'], 'missing')
        p = self.report()
        self.assertEqual(self.inspect()['reviews']['engine']['state'], 'ready')
        tasks = self.folder / 'tasks.md'
        tasks.write_text(tasks.read_text().replace('[x]', '[X]'))
        self.assertEqual(self.inspect()['reviews']['engine']['state'], 'ready')
        code = self.repos['engine'] / 'tests/test_feature.py'
        code.write_text(code.read_text() + '# Changed assertion\n')
        self.assertEqual(self.inspect()['reviews']['engine']['state'], 'stale')
        self.ok('review', 'disable', '001', '--reason', 'User ended pilot')
        self.assertEqual(self.inspect()['reviews']['engine']['state'], 'disabled')
        self.assertTrue(p.exists())
        history = json.loads((self.folder / 'reviews/policy.json').read_text())['original']['history']
        self.assertEqual(len(history), 2)

    def test_verdicts_and_bad_manifest(self):
        self.ok('review', 'enable', '001', '--reason', 'User request')
        for verdict in ('incomplete', 'changes-needed'):
            self.report(verdict=verdict)
            self.assertEqual(self.inspect()['reviews']['engine']['state'], verdict)
        p = self.report()
        p.write_text(p.read_text().replace('"independent": true', '"independent": false'))
        self.assertEqual(self.inspect()['reviews']['engine']['state'], 'incomplete')
        p = self.report()
        p.write_text(p.read_text().replace('tests/test_feature.py', '../outside.py'))
        self.assertEqual(self.inspect()['reviews']['engine']['state'], 'incomplete')

    def test_component_context_and_ambiguous_repo(self):
        data = json.loads(self.ok('inspect', '001', '--component', 'engine', '--json'))
        self.assertEqual(data['session_context']['acceptance_ids'], ['AC-01'])
        config = self.root / '.roclec/project.toml'
        config.write_text(config.read_text().replace('repo = "viewer"', 'repo = "engine"'))
        with patch('pathlib.Path.cwd', return_value=self.repos['engine']):
            self.assertEqual(self.call('inspect', '001', '--json')[0], 2)
            self.ok('inspect', '001', '--component', 'engine', '--json')

    def test_unmanaged_reference_preserved_and_alias_reference_resolves(self):
        ref = self.root / '.agents/skills/roclec-reviewer/references/report-template.md'
        ref.write_text('Consumer owned\n')
        before = (self.root / '.agents/skills/roclec-implement/SKILL.md').read_bytes()
        self.assertEqual(self.call('skills')[0], 2)
        self.assertEqual(ref.read_text(), 'Consumer owned\n')
        self.assertEqual(before, (self.root / '.agents/skills/roclec-implement/SKILL.md').read_bytes())
        with tempfile.TemporaryDirectory() as temp:
            _, extension = generate_adapter(load_project(self.root), Path(temp))
            body = (extension / 'commands/speckit.roclec.reviewer.md').read_text()
            self.assertIn(str(ref), body)
