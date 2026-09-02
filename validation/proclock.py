"""Process-level lockfiles: guarantee two instances of the same task never run
concurrently (which would race on key state and double-process papers).

A lock file state/<task>.lock holds the owner PID. If the owner is alive, a
second instance refuses to start. If the owner is dead (crash), the stale lock
is removed automatically.
"""
import errno
import os

import config


def acquire(task: str) -> None:
    path = config.STATE_DIR / f"{task}.lock"
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            return
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
            # lock exists: stale (dead owner) or genuinely running?
            try:
                pid = int(path.read_text().strip())
                os.kill(pid, 0)          # raises ProcessLookupError if dead
                raise SystemExit(
                    f"[{task}] another process (PID {pid}) is already running "
                    "this task. Wait for it, or kill it, then rerun.")
            except (ValueError, ProcessLookupError, PermissionError):
                path.unlink(missing_ok=True)   # stale lock from a dead run


def release(task: str) -> None:
    (config.STATE_DIR / f"{task}.lock").unlink(missing_ok=True)
