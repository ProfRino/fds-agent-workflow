import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

workflow = load('workflow')
release = load('package_release')

class WorkflowTests(unittest.TestCase):
    def test_example_and_chid(self):
        path = workflow.input_file('example_room')
        self.assertEqual(workflow.case_id(path), 'example_room')

    def test_outside_workspace_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'external.fds'
            path.write_text("&HEAD CHID='external' /")
            with self.assertRaisesRegex(ValueError, 'inside'):
                workflow.input_file(str(path))

    def test_chid_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.fds'
            path.write_text("&HEAD CHID='../other' /")
            with self.assertRaises(ValueError):
                workflow.case_id(path)

    def test_existing_output_never_runs_solver(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            (root / 'scripts/config.local.json').write_text('{"fds_install":"unused","mpi_processes":1}')
            case = root / 'simulations/case'
            case.mkdir(parents=True)
            (case / 'case.fds').write_text("&HEAD CHID='case' /")
            output = case / 'case.out'
            output.write_text('existing results')
            with patch.object(workflow, 'ROOT', root), patch('sys.argv', ['workflow','run','case','--preview-confirmed']), patch.object(workflow.subprocess, 'run') as run:
                run.return_value.returncode = 0
                with self.assertRaisesRegex(ValueError, 'Existing case outputs'):
                    workflow.main()
                self.assertEqual(run.call_count, 1)  # validator only
            self.assertEqual(output.read_text(), 'existing results')

    def test_release_excludes_local_data(self):
        names = {p.relative_to(ROOT).as_posix() for p in release.public_files()}
        self.assertNotIn('scripts/config.local.json', names)
        self.assertNotIn('scripts/run_fds.bat', names)
        self.assertFalse(any(n.startswith('visualization/') for n in names))
        self.assertEqual(release.scan(release.public_files()), [])

    def test_scanner_detects_personal_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sample.txt'
            path.write_text('C:' + chr(92) + 'Users' + chr(92) + 'ExamplePerson' + chr(92) + 'data')
            self.assertTrue(release.scan([path]))

if __name__ == '__main__':
    unittest.main()
