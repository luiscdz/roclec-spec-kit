from pathlib import Path
import tempfile
import unittest

from test_workflow import run
from roclec_spec_kit.config import load_project, ConfigError


class ProductDesignTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assertEqual(run('init', str(self.root), '--name', 'Example', '--component', 'console=.', '--user-facing', 'console')[0], 0)
        self.config = self.root / '.roclec/project.toml'

    def call(self, *args):
        return run('--project', str(self.root), *args)

    def sources(self):
        folder = self.root / 'product'
        folder.mkdir()
        (folder / 'core.md').write_text('# Shared\n\n## Users\n\nOperators\n\n## Product Purpose\n\nManage records\n')
        (folder / 'console.md').write_text('# Console\n\n## Platform\n\nweb\n\n## Stack\n\nConsumer chosen stack\n\n## Users\n\nStaff\n')
        self.config.write_text(self.config.read_text() + '\n[components.console.product]\n')

    def test_optional_views_stale_then_generate_and_check(self):
        self.assertEqual(self.call('product')[0], 0)
        self.sources()
        self.assertEqual(self.call('product')[0], 1)
        self.assertEqual(self.call('check')[0], 1)
        self.assertEqual(self.call('product', '--write')[0], 0)
        p = self.root / 'components/console/PRODUCT.md'
        self.assertIn('Operators\n\nStaff', p.read_text())
        self.assertEqual(self.call('check')[0], 0)
        original = p.read_bytes()
        self.assertEqual(self.call('product', '--write')[0], 0)
        self.assertEqual(original, p.read_bytes())
        core = self.root / 'product/core.md'
        core.write_text(core.read_text() + '\n## Product Principles\n\nConsistency\n')
        self.assertIn('stale', self.call('check', '--write')[1])
        self.assertEqual(p.read_bytes(), original)

    def test_preflight_preserves_unmanaged_views_and_invalid_sources(self):
        self.sources()
        p = self.root / 'components/console/PRODUCT.md'
        p.parent.mkdir(parents=True)
        p.write_text('Project-owned existing product\n')
        self.assertEqual(self.call('product', '--write')[0], 2)
        self.assertEqual(p.read_text(), 'Project-owned existing product\n')
        p.unlink()
        core = self.root / 'product/core.md'
        core.write_text(core.read_text() + '\n## Stack\n\nWrong shared stack\n')
        self.assertEqual(self.call('product', '--write')[0], 2)
        self.assertFalse(p.exists())

    def test_paths_and_shared_output_conflicts_rejected(self):
        self.sources()
        self.config.write_text(self.config.read_text() + 'output = "../outside.md"\n')
        with self.assertRaises(ConfigError):
            load_project(self.root)
        self.config.write_text(self.config.read_text().replace('../outside.md', 'product/core.md'))
        with self.assertRaises(ConfigError):
            load_project(self.root)

    def test_custom_paths_and_duplicate_sections(self):
        self.sources()
        self.config.write_text(self.config.read_text() + 'output = "context/console.md"\ndesign = "context/design.md"\n')
        self.assertEqual(self.call('product', '--write')[0], 0)
        self.assertTrue((self.root / 'context/console.md').exists())
        source = self.root / 'product/console.md'
        source.write_text(source.read_text() + '\n## Users\n\nDuplicate\n')
        before = (self.root / 'context/console.md').read_bytes()
        self.assertIn('duplicate', self.call('product', '--write')[1])
        self.assertEqual(before, (self.root / 'context/console.md').read_bytes())

    def ready(self, name):
        self.assertEqual(self.call('new', name, '--title', 'Maintenance')[0], 0)
        folder = self.root / 'specs' / name
        p = folder / 'spec.md'
        p.write_text(p.read_text().replace('status: draft', 'status: clarified').replace('effort: TBD', 'effort: S').replace('[NEEDS CLARIFICATION: define testable AC-NN scenarios before marking ready.]', '**AC-01** Works.'))
        (folder / 'ux.md').write_text('# UX\nExisting screen states.\n')
        (folder / 'prototype').mkdir()
        (folder / 'prototype/review.md').write_text('**Status:** approved\n**Reviewer:** Fixture\n')
        return folder

    def test_reused_prototypes_require_both_approvals_and_stay_inside_project(self):
        original = self.ready('001-original')
        (original / 'prototype/index.html').write_text('<title>Original approved screen</title>')
        current = self.ready('002-maintenance')
        references = current / 'prototype/references.md'
        references.write_text('[Existing](../../001-original/prototype/index.html)\n')
        self.assertEqual(self.call('check', '--gate', '002')[0], 0)
        (original / 'prototype/review.md').write_text('**Status:** pending\n')
        self.assertIn('original approval', self.call('check', '--gate', '002')[1])
        (original / 'prototype/review.md').write_text('**Status:** approved\n')
        (current / 'prototype/review.md').write_text('**Status:** pending\n')
        self.assertIn('user approval', self.call('check', '--gate', '002')[1])
        references.write_text('[Outside](../../../../outside.html)\n')
        self.assertIn('invalid reused prototype', self.call('check', '--gate', '002')[1])

    def test_symlinked_prototype_escape_is_rejected(self):
        current = self.ready('002-maintenance')
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'screen.html'
            target.write_text('<title>Outside</title>')
            original = self.root / 'specs/001-original/prototype'
            original.mkdir(parents=True)
            (original / 'index.html').symlink_to(target)
            (current / 'prototype/references.md').write_text('[Existing](../../001-original/prototype/index.html)\n')
            self.assertIn('invalid reused prototype', self.call('check', '--gate', '002')[1])
