"""A circuit breaker for an outside service: stop calling it while it is down.

After ``threshold`` calls in a row fail for the service's own sake, ``allow()``
answers False for ``cooldown`` seconds, and the caller fails at once with its
usual error — the cue it already treats as "fall back" or "try next run". Then
one probe is let through; a success closes the breaker, a failure opens it for
another cooldown.

One implementation, where the OpenRouter client and the mail sender each kept
a hand-written copy. In both, the probe was released only by a call that went
on to report success or failure, so any other way out — the mail sender's
"password is not ASCII" error raises before either — left it held, and the
breaker refused every call after it until the process restarted. ``guard()``
releases the probe however the call ends; a call that reports nothing leaves
the breaker as it was, ready to probe again.

Per process, like the Redis breaker: each worker finds out for itself, which
costs a few calls, not an outage's worth.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class Breaker:
    def __init__(
        self, name: str, *, threshold: int, cooldown: float, clock: Callable[[], float]
    ) -> None:
        self.name = name
        self.threshold = threshold
        self.cooldown = cooldown
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._open_until = 0.0
        self._probing = False

    def reset(self) -> None:
        """Close it. For tests, which must not inherit another's outage."""
        with self._lock:
            self._failures, self._open_until, self._probing = 0, 0.0, False

    def allow(self) -> bool:
        """Whether to call the service now. Claims the probe when one is due."""
        with self._lock:
            if not self._open_until:
                return True
            if self._clock() < self._open_until or self._probing:
                return False
            self._probing = True
            return True

    @contextmanager
    def guard(self) -> Iterator[None]:
        """Wrap the call ``allow()`` admitted, so its probe is always released."""
        try:
            yield
        finally:
            with self._lock:
                self._probing = False

    def succeeded(self) -> None:
        """The service answered — success, or a refusal of this request."""
        with self._lock:
            self._failures, self._open_until, self._probing = 0, 0.0, False

    def failed(self) -> None:
        """The service could not be reached, or failed for its own sake."""
        with self._lock:
            self._failures += 1
            was_open = bool(self._open_until)
            self._probing = False
            if self._failures >= self.threshold:
                self._open_until = self._clock() + self.cooldown
                if not was_open:
                    logger.warning(
                        "%s unavailable for %s calls in a row; not calling it for %ss",
                        self.name,
                        self._failures,
                        self.cooldown,
                        extra={"service": self.name, "failures": self._failures},
                    )
