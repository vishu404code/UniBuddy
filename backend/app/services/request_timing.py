"""Per-request timing: authentication, profile lookup, database time and the total.

The HTTP middleware in app.main opens a record for each request. The auth dependency and the
data client add to it. The middleware then writes one log line and a Server-Timing header, so a
slow dashboard can be split into its parts from the Render logs or the browser's network panel.
Only durations and counts are recorded: no tokens, no ids, no query text.
"""

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class RequestTiming:
    started: float = field(default_factory=time.perf_counter)
    parts_ms: dict[str, float] = field(default_factory=dict)
    db_calls: int = 0

    def add(self, part: str, ms: float) -> None:
        self.parts_ms[part] = self.parts_ms.get(part, 0.0) + ms

    def total_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000

    def server_timing(self, total_ms: float) -> str:
        items = [f"{name};dur={ms:.0f}" for name, ms in self.parts_ms.items()]
        items.append(f"total;dur={total_ms:.0f}")
        return ", ".join(items)


_current: ContextVar[RequestTiming | None] = ContextVar("unibuddy_request_timing", default=None)


def start() -> tuple[RequestTiming, object]:
    timing = RequestTiming()
    return timing, _current.set(timing)


def finish(token: object) -> None:
    _current.reset(token)  # type: ignore[arg-type]


def record(part: str, ms: float, *, db_call: bool = False) -> None:
    """Adds a duration to the current request. Outside a request (worker, tests) it does nothing.

    asyncio.to_thread copies the context, so the data client's worker threads add to the same record.
    """
    timing = _current.get()
    if timing is None:
        return
    timing.add(part, ms)
    if db_call:
        timing.db_calls += 1


@contextmanager
def measure(part: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        record(part, (time.perf_counter() - started) * 1000)
