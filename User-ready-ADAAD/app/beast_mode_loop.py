import time

class BeastModeLoop:
    def __init__(self, *_, **__):
        self._enabled = False

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def heartbeat_loop(self):
        while self._enabled:
            time.sleep(5)

    def shutdown(self):
        self._enabled = False
