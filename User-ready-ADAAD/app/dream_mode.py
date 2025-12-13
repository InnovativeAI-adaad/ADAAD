import time
from pathlib import Path

class DreamMode:
    def __init__(self, base: Path, cryo):
        self.base = Path(base)
        self.cryo = cryo
        self._enabled = False

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def shutdown(self):
        self._enabled = False

    def discover_tasks(self):
        return []

    def background_housekeeping(self):
        while self._enabled:
            time.sleep(5)
