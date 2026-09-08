"""Opt-in lifecycle check using a disposable empty MMD and an owned Windows job.

Never manipulates a pre-existing MMD. The test-created MMD is closed afterwards.
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import win32api
import win32con
import win32event
import win32gui
import win32job
import win32process

from mmd_mcp.launcher import launch_mmd
from mmd_mcp.windows import list_windows


def worker(executable, report):
    # Control: ordinary child inherits the disposable kill-on-close job.
    control = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],
                               creationflags=subprocess.CREATE_NO_WINDOW)
    result = launch_mmd(executable)
    result['control_pid'] = control.pid
    staged = Path(report).with_suffix('.tmp')
    staged.write_text(json.dumps(result), encoding='utf-8')
    staged.replace(report)
    time.sleep(120)


def check(executable):
    job = win32job.CreateJobObject(None, "")
    limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    limits['BasicLimitInformation']['LimitFlags'] = (
        win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK)
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
    process = thread = mmd = control = None
    window = None
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / 'launch.json'
        try:
            command = subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve()),
                                               '--worker', '--mmd-exe', executable, '--report', str(report)])
            process, thread, _, _ = win32process.CreateProcess(
                sys.executable, command, None, None, False,
                subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.CREATE_NO_WINDOW | win32con.CREATE_SUSPENDED,
                None, str(Path.cwd()), win32process.STARTUPINFO())
            win32job.AssignProcessToJobObject(job, process)
            win32process.ResumeThread(thread)
            deadline = time.monotonic() + 20
            while not report.exists() and time.monotonic() < deadline:
                if win32event.WaitForSingleObject(process, 100) == win32con.WAIT_OBJECT_0 and not report.exists():
                    raise RuntimeError('Launcher worker failed before writing its report.')
            if not report.exists():
                raise RuntimeError('Launcher worker timed out.')
            result = json.loads(report.read_text(encoding='utf-8'))
            if 'error' in result:
                raise RuntimeError(result['error'])
            access = win32con.SYNCHRONIZE | win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_TERMINATE
            mmd = win32api.OpenProcess(access, False, result['pid'])
            control = win32api.OpenProcess(access, False, result['control_pid'])
            assert not win32job.IsProcessInJob(mmd, None)
            assert win32job.IsProcessInJob(control, job)
            # Simulate host teardown, scoped strictly to the job created above.
            win32job.TerminateJobObject(job, 1)
            assert win32event.WaitForSingleObject(process, 5000) == win32con.WAIT_OBJECT_0
            assert win32event.WaitForSingleObject(control, 5000) == win32con.WAIT_OBJECT_0
            assert win32event.WaitForSingleObject(mmd, 1500) == win32con.WAIT_TIMEOUT
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                window = next((w for w in list_windows() if w.pid == result['pid']), None)
                if window:
                    break
                time.sleep(.1)
            assert window, 'MMD survived but no visible window appeared.'
            win32gui.SendMessageTimeout(window.hwnd, win32con.WM_NULL, 0, 0,
                                       win32con.SMTO_ABORTIFHUNG, 2000)
            print(json.dumps({'parent_job_terminated': True, 'ordinary_child_terminated': True,
                              'mmd_survived': True, 'mmd_window_responsive': True,
                              'mmd_pid': result['pid']}))
        finally:
            if mmd is not None:
                if window:
                    win32gui.PostMessage(window.hwnd, win32con.WM_CLOSE, 0, 0)
                if win32event.WaitForSingleObject(mmd, 3000) == win32con.WAIT_TIMEOUT:
                    win32api.TerminateProcess(mmd, 1)  # only this test's empty MMD
                mmd.Close()
            if process is not None and win32event.WaitForSingleObject(process, 0) == win32con.WAIT_TIMEOUT:
                win32api.TerminateProcess(process, 1)
            for handle in (control, thread, process, job):
                if handle is not None:
                    handle.Close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mmd-exe', required=True)
    parser.add_argument('--apply', action='store_true', help='Allow launch/close of a new disposable MMD')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--report', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        try:
            worker(args.mmd_exe, args.report)
        except Exception:
            import traceback
            Path(args.report).write_text(json.dumps({'error': traceback.format_exc()}), encoding='utf-8')
            raise
    elif args.apply:
        check(args.mmd_exe)
    else:
        parser.error('Pass --apply to run the disposable-process lifecycle check.')

