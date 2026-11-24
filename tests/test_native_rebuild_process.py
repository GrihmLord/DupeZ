"""Inert Python children exercise Windows compiler job ownership."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.native_rebuild import common
from scripts.native_rebuild import process


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows process jobs")


def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    return common.closed_environment(tmp_path / "private")


def assert_stopped(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if handle:
        try:
            assert kernel.WaitForSingleObject(handle, 0) == 0
        finally:
            kernel.CloseHandle(handle)
    else:
        assert ctypes.get_last_error() == 87  # PID no longer exists.


def test_owned_process_captures_output_and_exit(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch)
    log = tmp_path / "output.log"
    with log.open("xb") as stream:
        code = process.run_owned([sys.executable, "-I", "-c", "print('owned child');raise SystemExit(7)"],
                                 cwd=tmp_path, env=env, stdout=stream, timeout=10)
    assert code == 7
    assert log.read_text().strip() == "owned child"


@pytest.mark.parametrize("parent_exits", [False, True])
def test_owned_process_stops_descendants_before_return(tmp_path, monkeypatch, parent_exits):
    env = environment(tmp_path, monkeypatch)
    marker = tmp_path / "child.pid"
    child = "import os,time;from pathlib import Path;Path(" + repr(str(marker)) + ").write_text(str(os.getpid()));time.sleep(60)"
    parent = "import subprocess,sys,time;from pathlib import Path;subprocess.Popen([sys.executable,'-I','-c'," + repr(child) + "]);"
    parent += "p=Path(" + repr(str(marker)) + ");\nwhile not p.exists(): time.sleep(0.01)\n"
    parent += "time.sleep(60)" if not parent_exits else "raise SystemExit(0)"
    with (tmp_path / "output.log").open("xb") as stream:
        if parent_exits:
            assert process.run_owned([sys.executable, "-I", "-c", parent], cwd=tmp_path, env=env, stdout=stream, timeout=10) == 0
        else:
            with pytest.raises(subprocess.TimeoutExpired):
                process.run_owned([sys.executable, "-I", "-c", parent], cwd=tmp_path, env=env, stdout=stream, timeout=3)
    assert_stopped(int(marker.read_text()))


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), 3601])
def test_unbounded_timeout_rejected_before_launch(tmp_path, timeout):
    with pytest.raises(ValueError, match="bounded"):
        process.run_owned([sys.executable], cwd=tmp_path, env={}, stdout=None, timeout=timeout)


def test_invalid_environment_rejected_before_launch(tmp_path):
    with pytest.raises(ValueError, match="environment"):
        process.run_owned([sys.executable], cwd=tmp_path, env={"BAD=KEY": "value"}, stdout=None, timeout=1)


def test_child_does_not_inherit_unlisted_handle(tmp_path, monkeypatch):
    import msvcrt

    env = environment(tmp_path, monkeypatch)
    with (tmp_path / "unrelated").open("xb") as other, (tmp_path / "output.log").open("xb") as stream:
        handle = msvcrt.get_osfhandle(other.fileno())
        os.set_handle_inheritable(handle, True)
        script = ("import ctypes,json;from ctypes import wintypes;k=ctypes.WinDLL('kernel32',use_last_error=True);"
                  "k.GetHandleInformation.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];"
                  "flags=wintypes.DWORD();print(json.dumps({'inherited':bool(k.GetHandleInformation(" + str(handle) + ",ctypes.byref(flags)))}))")
        try:
            assert process.run_owned([sys.executable, "-I", "-c", script], cwd=tmp_path, env=env, stdout=stream, timeout=10) == 0
        finally:
            os.set_handle_inheritable(handle, False)
    assert json.loads((tmp_path / "output.log").read_text()) == {"inherited": False}


@pytest.mark.parametrize("failed_api", ["AssignProcessToJobObject", "ResumeThread"])
def test_launch_failure_terminates_suspended_process_without_running_it(tmp_path, monkeypatch, failed_api):
    env = environment(tmp_path, monkeypatch)
    marker = tmp_path / "must-not-exist"
    real_kernel = process.kernel_api()
    real_kernel.GetProcessId.argtypes = [wintypes.HANDLE]
    real_kernel.GetProcessId.restype = wintypes.DWORD
    observed = []

    class FailingKernel:
        def __getattr__(self, name):
            if name == "AssignProcessToJobObject":
                def assign(job, handle):
                    observed.append(real_kernel.GetProcessId(handle))
                    if failed_api == name:
                        ctypes.set_last_error(5)
                        return 0
                    return real_kernel.AssignProcessToJobObject(job, handle)
                return assign
            if name == failed_api:
                return lambda _handle: 0xFFFFFFFF
            return getattr(real_kernel, name)

    monkeypatch.setattr(process, "kernel_api", FailingKernel)
    with (tmp_path / "output.log").open("xb") as stream, pytest.raises(OSError):
        process.run_owned([sys.executable, "-I", "-c", "from pathlib import Path;Path(" + repr(str(marker)) + ").write_text('ran')"],
                          cwd=tmp_path, env=env, stdout=stream, timeout=10)
    assert not marker.exists()
    assert len(observed) == 1
    assert_stopped(observed[0])
