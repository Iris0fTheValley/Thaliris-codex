"""Creation-bound ownership for one command tree; never enumerate arbitrary PIDs."""
from __future__ import annotations

import os
import subprocess
import threading
import time


class TreeUnavailable(OSError):
    """No process is launched when creation-time ownership cannot be established."""


class WindowsProcess:
    """CreateProcessW with JOB_LIST binds ownership before any user code executes."""

    ownership = "WINDOWS_CREATION_JOB"

    def __init__(self, command, cwd):
        import ctypes as c
        from ctypes import wintypes as w
        import msvcrt

        k = self.kernel = c.WinDLL("kernel32", use_last_error=True)
        size_t, pointer = c.c_size_t, c.c_void_p

        class Startup(c.Structure):
            _fields_ = [("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR), ("title", w.LPWSTR),
                        ("x", w.DWORD), ("y", w.DWORD), ("xsize", w.DWORD), ("ysize", w.DWORD),
                        ("xchars", w.DWORD), ("ychars", w.DWORD), ("fill", w.DWORD), ("flags", w.DWORD),
                        ("show", w.WORD), ("reserved2size", w.WORD), ("reserved2", pointer),
                        ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE)]

        class ExtendedStartup(c.Structure):
            _fields_ = [("startup", Startup), ("attributes", pointer)]

        class ProcessInfo(c.Structure):
            _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]

        class BasicLimit(c.Structure):
            _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64), ("flags", w.DWORD),
                        ("min_working", size_t), ("max_working", size_t), ("active_limit", w.DWORD),
                        ("affinity", size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class IO(c.Structure):
            _fields_ = [(name, c.c_uint64) for name in ("read", "write", "other", "read_bytes", "write_bytes", "other_bytes")]

        class ExtendedLimit(c.Structure):
            _fields_ = [("basic", BasicLimit), ("io", IO), ("process_memory", size_t),
                        ("job_memory", size_t), ("peak_process", size_t), ("peak_job", size_t)]

        class Accounting(c.Structure):
            _fields_ = [("user", c.c_int64), ("kernel", c.c_int64), ("period_user", c.c_int64),
                        ("period_kernel", c.c_int64), ("faults", w.DWORD), ("total", w.DWORD),
                        ("active", w.DWORD), ("terminated", w.DWORD)]

        self.Accounting = Accounting
        signatures = {
            "CreateJobObjectW": ([pointer, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, c.c_int, pointer, w.DWORD], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, c.c_int, pointer, w.DWORD, pointer], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "InitializeProcThreadAttributeList": ([pointer, w.DWORD, w.DWORD, c.POINTER(size_t)], w.BOOL),
            "UpdateProcThreadAttribute": ([pointer, w.DWORD, size_t, pointer, size_t, pointer, pointer], w.BOOL),
            "DeleteProcThreadAttributeList": ([pointer], None),
            "CreateProcessW": ([w.LPCWSTR, w.LPWSTR, pointer, pointer, w.BOOL, w.DWORD, pointer,
                                w.LPCWSTR, c.POINTER(ExtendedStartup), c.POINTER(ProcessInfo)], w.BOOL),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "GetExitCodeProcess": ([w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            getattr(k, name).argtypes = args
            getattr(k, name).restype = result
        self.job = self.handle = None
        self.returncode = None
        descriptors = []
        attributes = None
        attributes_initialized = False
        info = ProcessInfo()
        try:
            self.job = k.CreateJobObjectW(None, None)  # unnamed; never inherited
            if not self.job:
                raise TreeUnavailable("CreateJobObjectW unavailable")
            limit = ExtendedLimit()
            limit.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway flag.
            if not k.SetInformationJobObject(self.job, 9, c.byref(limit), c.sizeof(limit)):
                raise TreeUnavailable("job limits unavailable")
            stdin = os.open(os.devnull, os.O_RDONLY)
            descriptors.append(stdin)
            stdout_read, stdout_write = os.pipe()
            descriptors.extend([stdout_read, stdout_write])
            stderr_read, stderr_write = os.pipe()
            descriptors.extend([stderr_read, stderr_write])
            for fd in (stdin, stdout_write, stderr_write):
                os.set_inheritable(fd, True)
            inherited = (w.HANDLE * 3)(*(msvcrt.get_osfhandle(fd) for fd in (stdin, stdout_write, stderr_write)))
            jobs = (w.HANDLE * 1)(self.job)
            size = size_t()
            k.InitializeProcThreadAttributeList(None, 2, 0, c.byref(size))
            attributes = c.create_string_buffer(size.value)
            if not k.InitializeProcThreadAttributeList(attributes, 2, 0, c.byref(size)):
                raise TreeUnavailable("creation attributes unavailable")
            attributes_initialized = True
            for attribute, value in ((0x20002, inherited), (0x2000D, jobs)):
                if not k.UpdateProcThreadAttribute(attributes, 0, attribute, c.cast(value, pointer),
                                                   c.sizeof(value), None, None):
                    raise TreeUnavailable("creation-time job/handle binding unavailable")
            startup = ExtendedStartup()
            startup.startup.cb = c.sizeof(startup)
            startup.startup.flags = 0x100 | 0x1  # USESTDHANDLES | USESHOWWINDOW
            startup.startup.show = 0  # hidden, noninteractive foreground operation
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = inherited
            startup.attributes = c.cast(attributes, pointer)
            line = c.create_unicode_buffer(subprocess.list2cmdline(command))
            if not k.CreateProcessW(None, line, None, None, True, 0x80000 | 0x08000000,
                                    None, str(cwd), c.byref(startup), c.byref(info)):
                raise c.WinError(c.get_last_error())
            self.handle, self.pid = info.process, info.pid
            k.CloseHandle(info.thread)
            info.thread = None
            self.stdout = os.fdopen(stdout_read, "rb", buffering=0)
            descriptors.remove(stdout_read)
            self.stderr = os.fdopen(stderr_read, "rb", buffering=0)
            descriptors.remove(stderr_read)
        except Exception:
            if self.job:
                k.CloseHandle(self.job)  # kill-on-close covers even a setup failure after creation.
                self.job = None
            if self.handle:
                k.CloseHandle(self.handle)
                self.handle = None
            raise
        finally:
            if attributes_initialized:
                k.DeleteProcThreadAttributeList(attributes)
            for fd in descriptors:
                os.close(fd)

    def poll(self):
        import ctypes as c
        from ctypes import wintypes as w
        outcome = self.kernel.WaitForSingleObject(self.handle, 0)
        if outcome == 0:
            code = w.DWORD()
            if not self.kernel.GetExitCodeProcess(self.handle, c.byref(code)):
                raise c.WinError(c.get_last_error())
            self.returncode = code.value
        elif outcome != 0x102:
            raise c.WinError(c.get_last_error())
        return self.returncode

    def wait(self, timeout=None):
        outcome = self.kernel.WaitForSingleObject(self.handle, 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000)))
        if outcome == 0x102:
            raise subprocess.TimeoutExpired("owned job", timeout)
        return self.poll()

    def close_tree(self) -> str:
        import ctypes as c
        try:
            if not self.kernel.TerminateJobObject(self.job, 1):
                raise c.WinError(c.get_last_error())
            self.wait()
            deadline = time.monotonic() + 2
            while True:
                accounting = self.Accounting()
                if not self.kernel.QueryInformationJobObject(self.job, 1, c.byref(accounting), c.sizeof(accounting), None):
                    raise c.WinError(c.get_last_error())
                if accounting.active == 0:
                    return "CONFIRMED_JOB_EMPTY"
                if time.monotonic() >= deadline:
                    return "UNKNOWN"
                threading.Event().wait(.01)
        finally:
            # Closing the non-inherited job handle also enforces kill-on-close if
            # explicit termination/accounting failed. Never downgrade to PID kill.
            self.kernel.CloseHandle(self.job)
            self.job = None
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def launch(command, cwd):
    if os.name == "nt":
        return WindowsProcess(command, cwd)
    raise TreeUnavailable("POSIX process-tree ownership unsupported; command was not launched")
