import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mmd_mcp import launcher


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.exe = Path(self.directory.name) / 'MikuMikuDance.exe'
        self.exe.touch()

    def test_detached_breakaway_checked_before_resume_and_handles_closed(self):
        process, thread = MagicMock(), MagicMock()
        events = []
        with (patch.object(launcher, '_create_suspended', return_value=(process, thread, 123)) as create,
              patch.object(launcher.win32job, 'IsProcessInJob', side_effect=lambda *a: events.append('check') or False),
              patch.object(launcher.win32process, 'ResumeThread', side_effect=lambda *a: events.append('resume')),
              patch.object(launcher.win32api, 'TerminateProcess') as terminate):
            result = launcher.launch_mmd(str(self.exe))
        self.assertEqual(events, ['check', 'resume'])
        self.assertEqual(result['pid'], 123)
        self.assertTrue(result['job_independent'])
        args = create.call_args.args
        for flag in (launcher.subprocess.CREATE_BREAKAWAY_FROM_JOB,
                     launcher.subprocess.DETACHED_PROCESS, launcher.win32con.CREATE_SUSPENDED):
            self.assertTrue(args[1] & flag)
        self.assertEqual(args[0], self.exe)
        terminate.assert_not_called()
        process.Close.assert_called_once()
        thread.Close.assert_called_once()

    def test_nested_job_refused_before_any_mmd_code_runs(self):
        process, thread = MagicMock(), MagicMock()
        with (patch.object(launcher, '_create_suspended', return_value=(process, thread, 123)) as create,
              patch.object(launcher.win32job, 'IsProcessInJob', return_value=True),
              patch.object(launcher.win32process, 'ResumeThread') as resume,
              patch.object(launcher.win32api, 'TerminateProcess') as terminate):
            with self.assertRaisesRegex(RuntimeError, 'No ordinary-launch fallback'):
                launcher.launch_mmd(str(self.exe))
        create.assert_called_once()
        resume.assert_not_called()
        terminate.assert_called_once_with(process, 1)
        process.Close.assert_called_once()
        thread.Close.assert_called_once()

    def test_breakaway_denied_does_not_retry(self):
        with (patch.object(launcher, '_create_suspended', side_effect=OSError('denied')) as create,
              patch.object(launcher.win32api, 'TerminateProcess') as terminate):
            with self.assertRaisesRegex(RuntimeError, 'Independent MMD launch failed'):
                launcher.launch_mmd(str(self.exe))
        create.assert_called_once()
        terminate.assert_not_called()

    def test_bad_path_does_not_create_process(self):
        with patch.object(launcher, '_create_suspended') as create:
            for path in ('MikuMikuDance.exe', str(self.exe.parent/'other.exe')):
                with self.assertRaises(ValueError):
                    launcher.launch_mmd(path)
        create.assert_not_called()
