from pathlib import Path
import json
import tempfile
import unittest

from test_workflow import run
from roclec_spec_kit.adapter import generate_adapter
from roclec_spec_kit import __version__
from roclec_spec_kit.config import load_project
from roclec_spec_kit.workflow import parse_front_matter


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assertEqual(run('init', str(self.root), '--name', 'Example')[0], 0)
        self.assertEqual(self.call('new', '001-example', '--title', 'A # B')[0], 0)
        self.folder = self.root / 'specs/001-example'
        self.spec = self.folder / 'spec.md'

    def call(self, *args):
        return run('--project', str(self.root), *args)

    def clarify(self):
        self.spec.write_text(self.spec.read_text().replace('effort: TBD', 'effort: S').replace(
            '[NEEDS CLARIFICATION: define testable AC-NN scenarios before marking ready.]', '**AC-01** Given input, when saved, then it can be read.'))
        code, output = self.call('transition', '001', 'clarified')
        self.assertEqual(code, 0, output)
        self.assertEqual(self.call('artifact', '001', 'plan')[0], 0)
        self.assertEqual(self.call('transition', '001', 'ready')[0], 0)

    def test_selection_is_explicit_and_optional_context_mirrored(self):
        self.assertEqual(json.loads(self.call('inspect', '--json')[1])['spec'], '001-example')
        (self.root / '.specify').mkdir()
        self.assertEqual(self.call('use', '001')[0], 0)
        self.assertEqual(json.loads((self.root / '.specify/feature.json').read_text())['feature_directory'], 'specs/001-example')
        (self.root / '.roclec/feature.json').write_text('{"spec": []}')
        self.assertEqual(self.call('inspect')[0], 2)
        (self.root / '.roclec/feature.json').unlink()
        self.assertEqual(self.call('inspect')[0], 2)
        self.assertEqual(self.call('inspect', '001', '--json')[0], 0)

    def test_rejected_transition_preserves_state_and_template_comments_are_not_criteria(self):
        original = self.spec.read_bytes()
        self.assertEqual(self.call('transition', '001', 'in-progress')[0], 2)
        self.assertEqual(self.call('transition', '001', 'clarified')[0], 2)
        self.assertEqual(self.spec.read_bytes(), original)
        body = self.spec.read_text().replace('[NEEDS CLARIFICATION: define testable AC-NN scenarios before marking ready.]', '').replace('effort: TBD', 'effort: S')
        self.spec.write_text(body)
        code, output = self.call('check', '--gate', '001')
        self.assertEqual(code, 1)
        self.assertIn('no AC-NN', output)

    def test_task_gate_rejects_empty_duplicate_owner_and_unknown_references(self):
        self.clarify()
        self.assertEqual(self.call('artifact', '001', 'tasks')[0], 0)
        self.assertIn('at least one task', self.call('check', '--release-gate', '001')[1])
        self.assertEqual(self.call('release', 'plan', 'app', 'v0.1.0', '001')[0], 2)  # Invalid candidates leave no release file.
        tasks = self.folder / 'tasks.md'
        bad = '- [ ] T001 [app] [specs] bad [001/AC-99]\n- [ ] T001 [app] duplicate\n'
        tasks.write_text(bad)
        code, output = self.call('transition', '001', 'in-progress')
        self.assertEqual(code, 2)
        for expected in ('exactly one', 'duplicate task', 'unknown [001/AC-99]', 'do not cover'):
            self.assertIn(expected, output)
        tasks.write_text('- [ ] T001 [app] [US1] [P] Implement src/save.py [001/AC-01]\n')
        self.assertEqual(self.call('release', 'plan', 'app', 'v0.1.0', '001')[0], 0)
        code, output = self.call('transition', '001', 'in-progress')
        self.assertEqual(code, 0, output)
        self.assertEqual(self.call('transition', '001', 'done')[0], 2)
        tasks.write_text(tasks.read_text().replace('[ ]', '[x]'))
        self.assertIn('test does not cite', self.call('transition', '001', 'done')[1])
        (self.root / 'tests').mkdir()
        (self.root / 'tests/test_save.py').write_text('# [001/AC-01]\n')
        self.assertEqual(self.call('transition', '001', 'done')[0], 0)

    def test_owned_templates_and_constitution_survive_refresh(self):
        template = self.root / '.roclec/templates/plan-template.md'
        constitution = self.root / '.roclec/constitution.md'
        template.write_text('# Custom plan\n')
        constitution.write_text('# Custom governance\n')
        self.assertEqual(self.call('skills')[0], 0)
        self.assertEqual(template.read_text(), '# Custom plan\n')
        self.assertEqual(constitution.read_text(), '# Custom governance\n')
        self.clarify()
        self.assertEqual((self.folder / 'plan.md').read_text(), '# Custom plan\n')

    def test_front_matter_preserves_quoted_hash_and_reports_duplicate_keys(self):
        meta, _ = parse_front_matter(self.spec.read_text())
        self.assertEqual(meta['title'], 'A # B')
        self.spec.write_text(self.spec.read_text().replace('status: draft', 'status: draft\nstatus: done'))
        code, output = self.call('check')
        self.assertEqual(code, 1)
        self.assertIn('duplicate front matter key status', output)

    def test_optional_commands_are_generated_from_native_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            preset, extension = generate_adapter(load_project(self.root), Path(directory))
            native = (self.root / '.agents/skills/roclec-plan/SKILL.md').read_text().split('\n---\n', 1)[1].lstrip()
            self.assertTrue((preset / 'commands/speckit.plan.md').read_text().endswith(native))
            self.assertTrue((extension / 'commands/speckit.roclec.coordinator.md').is_file())
            manifest = json.loads((preset / 'preset.yml').read_text())
            self.assertEqual(manifest['preset']['version'], __version__)
