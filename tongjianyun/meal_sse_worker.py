"""Honor timeout=0 for SSE on the bench's patched Gunicorn gthread worker."""
from gunicorn.workers.gthread import ThreadWorker


class SSEThreadWorker(ThreadWorker):
    def _wrap_future(self, future, connection, slow=False):
        super()._wrap_future(future, connection, slow=slow)
        # This bench's gthread patch assigns now + timeout even when timeout is
        # zero. Restrict the compatibility fix to this dedicated worker class.
        if self.cfg.timeout == 0:
            future._request_timeout = float('inf')
