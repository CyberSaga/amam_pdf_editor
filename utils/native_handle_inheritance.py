from __future__ import annotations

import os
import sys

# UCRT lowio descriptors have a separate capacity from _getmaxstdio(). The
# observed 512-stream setting does not exclude descriptors above 511.
_CRT_DESCRIPTOR_LIMIT = 8192
_FILE_TYPE_DISK = 1
_RACE_RETRIES = 3


def _clear_descriptor(fd, get_handle, file_type, is_inheritable, set_inheritable) -> int:
    # Other threads may open or close files during the scan. A descriptor that vanishes has
    # nothing left to leak; one that is swapped is re-read a bounded number of times.
    for _attempt in range(_RACE_RETRIES):
        try:
            handle = get_handle(fd)
        except OSError:
            return 0  # Unallocated descriptor slots are expected.
        try:
            if handle < 0 or file_type(handle) != _FILE_TYPE_DISK:
                return 0
            if not is_inheritable(handle):
                return 0
            if get_handle(fd) != handle:
                continue
            set_inheritable(handle, False)
            return 1
        except OSError as exc:
            try:
                current = get_handle(fd)
            except OSError:
                return 0
            if current == handle:
                raise exc
    raise RuntimeError('Native disk descriptor changed during child launch preparation')


def _prepare_disk_handles(get_handle, file_type, is_inheritable, set_inheritable) -> int:
    return sum(_clear_descriptor(fd, get_handle, file_type, is_inheritable, set_inheritable)
               for fd in range(3, _CRT_DESCRIPTOR_LIMIT))


def prepare_owned_qprocess_start() -> int:
    """Prevent observed UCRT disk readers from leaking into an owned child.

    Standard descriptors and non-disk handles stay untouched. Changes are
    permanent; errors propagate so callers do not launch with a known unsafe
    handle. No path lookup, file read or reader close occurs. This is a bounded
    CRT-table mitigation, not atomic isolation from concurrent native opens or
    a guarantee about handles managed by another runtime/table.
    """
    if sys.platform != 'win32':
        return 0
    import ctypes
    import msvcrt

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    get_type = kernel.GetFileType
    get_type.argtypes = [ctypes.c_void_p]
    get_type.restype = ctypes.c_uint32
    return _prepare_disk_handles(msvcrt.get_osfhandle, get_type,
                                 os.get_handle_inheritable, os.set_handle_inheritable)
