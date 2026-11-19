"""Windows process CPU (kernel+user, GetProcessTimes) and peak working set
(GetProcessMemoryInfo) for a subprocess.Popen handle. Same method as checkpoint.py."""
import ctypes
from ctypes import wintypes


class Memory(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [(x, ctypes.c_size_t) for x in
        ['PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
         'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage']]


_k = ctypes.WinDLL('kernel32', use_last_error=True)
_gettimes = _k.GetProcessTimes
_gettimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
_getmem = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
_getmem.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]


def measurements(p):
    """Returns (cpu_seconds, peak_working_set_bytes); 'unknown' where unavailable."""
    ft = [wintypes.FILETIME() for _ in range(4)]
    cpu = 'unknown'
    if _gettimes(wintypes.HANDLE(int(p._handle)), *[ctypes.byref(x) for x in ft]):
        cpu = sum((x.dwHighDateTime << 32) + x.dwLowDateTime for x in ft[2:]) / 1e7
    mem = Memory(); mem.cb = ctypes.sizeof(mem)
    peak = mem.PeakWorkingSetSize if _getmem(wintypes.HANDLE(int(p._handle)), ctypes.byref(mem), mem.cb) else 'unknown'
    return cpu, peak


def lifetime(p):
    """Process exit minus creation FILETIME (seconds), or 'unknown'."""
    ft = [wintypes.FILETIME() for _ in range(4)]
    if not _gettimes(wintypes.HANDLE(int(p._handle)), *[ctypes.byref(x) for x in ft]):
        return 'unknown'
    t = [(x.dwHighDateTime << 32) + x.dwLowDateTime for x in ft[:2]]
    return (t[1] - t[0]) / 1e7 if t[1] else 'unknown'
