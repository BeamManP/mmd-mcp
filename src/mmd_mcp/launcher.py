"""Explicit MMD launch outside the caller's Windows job and console lifetime."""
import argparse
import json
import subprocess
from pathlib import Path

import psutil
import pythoncom
import win32com.client
import win32api
import win32con
import win32job
import win32process


def _create_suspended(path, flags):
    # Local WMI is a Windows service broker, outside Codex's process ancestry.
    # Break away from WMI's own provider job as well.
    pythoncom.CoInitialize()
    process = None
    try:
        service = win32com.client.GetObject('winmgmts:root\\cimv2')
        startup = service.Get('Win32_ProcessStartup').SpawnInstance_()
        startup.Properties_('ShowWindow').Value = win32con.SW_SHOWNORMAL
        startup.Properties_('CreateFlags').Value = flags
        params = service.Get('Win32_Process').Methods_('Create').InParameters.SpawnInstance_()
        params.Properties_('CommandLine').Value = subprocess.list2cmdline([str(path)])
        params.Properties_('CurrentDirectory').Value = str(path.parent)
        params.Properties_('ProcessStartupInformation').Value = startup
        output = service.ExecMethod('Win32_Process', 'Create', params)
        code = output.Properties_('ReturnValue').Value
        if code:
            raise RuntimeError(f'Windows WMI process creation returned {code}.')
        pid = int(output.Properties_('ProcessId').Value)
        try:
            process = win32api.OpenProcess(
                win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_TERMINATE, False, pid)
        except Exception as error:
            raise RuntimeError(f'Cannot inspect newly created suspended MMD PID {pid}.') from error
        threads = psutil.Process(pid).threads()
        if len(threads) != 1:
            raise RuntimeError('Expected one initial thread in suspended MMD.')
        thread = win32api.OpenThread(win32con.THREAD_SUSPEND_RESUME, False, threads[0].id)
        return process, thread, pid
    except Exception:
        if process is not None:
            try:
                win32api.TerminateProcess(process, 1)
            finally:
                process.Close()
        raise
    finally:
        pythoncom.CoUninitialize()


def launch_mmd(executable: str) -> dict:
    """Start a new, empty MMD; never attach to or close an existing instance.

    The local WMI broker avoids the host process ancestry. Check job membership while the new
    process is suspended, before it can open a project or accept user edits.
    No ordinary-launch fallback: console detachment alone does not escape jobs.
    """
    path = Path(executable)
    if not path.is_absolute() or path.name.casefold() != 'mikumikudance.exe' or not path.is_file():
        raise ValueError('Provide the absolute path to MikuMikuDance.exe.')
    path = path.resolve()
    flags = (subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.DETACHED_PROCESS
             | win32con.CREATE_SUSPENDED)
    process = thread = None
    resumed = False
    try:
        process, thread, pid = _create_suspended(path, flags)
        if win32job.IsProcessInJob(process, None):
            raise RuntimeError('New MMD still belongs to a Windows job; refusing dependent launch.')
        win32process.ResumeThread(thread)
        resumed = True
        return {'pid': pid, 'executable': str(path), 'job_independent': True,
                'status': 'started', 'window_ready': False, 'launch_method': 'local_wmi'}
    except Exception as error:
        raise RuntimeError(
            'Independent MMD launch failed. No ordinary-launch fallback was used. '
            'Launch MMD manually from Explorer if this host forbids job breakaway. '
            f'Details: {error}') from error
    finally:
        # Only our own still-suspended process can be terminated here.
        try:
            if process is not None and not resumed:
                win32api.TerminateProcess(process, 1)
        finally:
            if thread is not None:
                thread.Close()
            if process is not None:
                process.Close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', help='Absolute path to MikuMikuDance.exe')
    args = parser.parse_args()
    print(json.dumps(launch_mmd(args.executable), ensure_ascii=False))


if __name__ == '__main__':
    main()
