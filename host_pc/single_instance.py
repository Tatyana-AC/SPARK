import tempfile
from pathlib import Path

from PyQt6.QtCore import QLockFile


class SingleInstanceGuard:
    """Prevent concurrent app instances from starting in the same user session."""

    def __init__(self, lock_path: str | Path, stale_lock_ms: int = 30_000):
        self.lock_path = Path(lock_path)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = QLockFile(str(self.lock_path))
        self._lock.setStaleLockTime(stale_lock_ms)

    @classmethod
    def for_app(cls, app_name: str, stale_lock_ms: int = 30_000) -> "SingleInstanceGuard":
        lock_path = Path(tempfile.gettempdir()) / f"{app_name}.lock"
        return cls(lock_path, stale_lock_ms=stale_lock_ms)

    def acquire(self) -> bool:
        return self._lock.tryLock()

    def release(self) -> None:
        if self._lock.isLocked():
            self._lock.unlock()
