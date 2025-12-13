import concurrent.futures

class WarmPool:
    def __init__(self, max_workers=4):
        self._ex = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)

    def submit(self, fn, *a, **kw):
        return self._ex.submit(fn, *a, **kw)

    def shutdown(self):
        self._ex.shutdown(wait=False)
