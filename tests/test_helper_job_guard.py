"""Windows Job-object lifetime binding tests."""

from app.firewall_helper import job_guard


class _Kernel32:
    def __init__(self, *, configure=True, process=22, assign=True):
        self.configure = configure
        self.process = process
        self.assign = assign
        self.closed = []

    def CreateJobObjectW(self, _attrs, _name):
        return 11

    def SetInformationJobObject(self, *_args):
        return self.configure

    def OpenProcess(self, *_args):
        return self.process

    def AssignProcessToJobObject(self, *_args):
        return self.assign

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


def test_job_guard_rejects_invalid_pid() -> None:
    assert job_guard.bind_helper_to_parent_lifetime(0, kernel32=_Kernel32()) is False


def test_job_guard_retains_successful_job_handle(monkeypatch) -> None:
    fake = _Kernel32()
    monkeypatch.setattr(job_guard, "_JOB_HANDLES", [])

    assert job_guard.bind_helper_to_parent_lifetime(1234, kernel32=fake) is True
    assert fake.closed == [22]
    assert job_guard._JOB_HANDLES == [11]


def test_job_guard_closes_job_when_assignment_fails(monkeypatch) -> None:
    fake = _Kernel32(assign=False)
    monkeypatch.setattr(job_guard, "_JOB_HANDLES", [])

    assert job_guard.bind_helper_to_parent_lifetime(1234, kernel32=fake) is False
    assert fake.closed == [22, 11]
    assert job_guard._JOB_HANDLES == []
