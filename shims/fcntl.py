"""
fcntl shim for Windows / PowerShell Grok environments.

This provides the minimal subset of fcntl constants and functions
that ADAAD/DORK code expects (mainly for file locking in ledgers/metrics).

On real Unix it just re-exports the real module.
"""

import sys
import os

if os.name == "nt":
    # Windows stubs
    F_GETFL = 3
    F_SETFL = 4
    F_GETFD = 1
    F_SETFD = 2
    FD_CLOEXEC = 1

    O_RDONLY = 0
    O_WRONLY = 1
    O_RDWR = 2
    O_APPEND = 8
    O_CREAT = 256
    O_EXCL = 1024
    O_TRUNC = 512
    O_NONBLOCK = 2048

    F_RDLCK = 0
    F_WRLCK = 1
    F_UNLCK = 2

    def fcntl(fd, cmd, arg=0):
        """Stub fcntl - does nothing on Windows but prevents ImportError."""
        return arg

    def flock(fd, op):
        """Stub flock - file locking is a no-op on Windows for our purposes."""
        pass

    def ioctl(fd, request, arg=0, mutate_flag=True):
        """Stub ioctl."""
        return 0

    def lockf(fd, cmd, len=0, start=0, whence=0):
        """Stub lockf."""
        pass

else:
    # On Unix, delegate to the real module
    from fcntl import *  # noqa: F401,F403
    import fcntl as _real
    globals().update(_real.__dict__)