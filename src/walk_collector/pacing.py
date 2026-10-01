"""Ritmo y protección del equipo: reloj inyectable, backoff, max-repetitions
adaptativo y monitor de latencia (kill-switch)."""
from __future__ import annotations

import random
import statistics
import time
from collections import deque
from typing import Protocol


class Clock(Protocol):
    def monotonic(self) -> float: ...
    def sleep(self, s: float) -> None: ...


class RealClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, s: float) -> None:
        if s > 0:
            time.sleep(s)


class Backoff:
    """``delay(n) = min(max_s, base*2**(n-1)) * (1 ± jitter)`` para el intento n>=1."""

    def __init__(self, base_s: float, max_s: float, jitter: float,
                 rng: random.Random | None = None):
        self.base_s, self.max_s, self.jitter = base_s, max_s, jitter
        self.rng = rng or random.Random()

    def delay(self, attempt: int) -> float:
        attempt = max(1, attempt)
        raw = min(self.max_s, self.base_s * (2 ** (attempt - 1)))
        if self.jitter:
            raw *= 1.0 + self.rng.uniform(-self.jitter, self.jitter)
        return raw


class AdaptiveRepetitions:
    """max-repetitions dinámico: baja ante timeouts/tooBig y se recupera de a poco."""

    def __init__(self, ceiling: int, floor: int = 1, recover_after: int = 50):
        self.ceiling = ceiling
        self.floor = floor
        self.recover_after = recover_after
        self.current = ceiling
        self.min_used = ceiling
        self._ok_streak = 0

    def _set(self, value: int) -> None:
        self.current = max(self.floor, min(self.ceiling, value))
        self.min_used = min(self.min_used, self.current)

    def on_success(self) -> None:
        self._ok_streak += 1
        if self.current < self.ceiling and self._ok_streak >= self.recover_after:
            self._set(self.current + (self.current + 1) // 2)   # +ceil(current/2)
            self._ok_streak = 0

    def on_timeout(self, consecutive: int) -> None:
        """Desde el 2º timeout seguido se reduce a la mitad."""
        self._ok_streak = 0
        if consecutive >= 2:
            self._set(self.current // 2)

    def on_too_big(self) -> None:
        """tooBig: mitad inmediata, sin backoff."""
        self._ok_streak = 0
        self._set(self.current // 2)


class LatencyMonitor:
    """Detecta degradación sostenida del equipo (kill-switch de seguridad).

    * baseline = mediana de las primeras ``baseline_samples`` respuestas exitosas;
    * "degraded" cuando la mediana de la ventana supera ``max(min_ms, baseline*factor)``
      durante ``sustain`` chequeos seguidos, o cuando los timeouts pasan del 20% de la
      ventana (con >= 5 muestras) durante ``sustain`` chequeos seguidos.
    """

    def __init__(self, window: int, baseline_samples: int, factor: float, min_ms: float,
                 sustain: int):
        self.window = window
        self.baseline_samples = baseline_samples
        self.factor = factor
        self.min_ms = min_ms
        self.sustain = sustain
        self._base: list[float] = []
        self.baseline_ms: float | None = None
        self._win: deque[tuple[float, bool]] = deque(maxlen=window)
        self._all: list[float] = []
        self._bad_streak = 0
        self.max_ms = 0.0

    def record(self, ms: float, timed_out: bool = False) -> None:
        self._win.append((ms, timed_out))
        if not timed_out:
            self.max_ms = max(self.max_ms, ms)
            self._all.append(ms)
            if self.baseline_ms is None:
                self._base.append(ms)
                if len(self._base) >= self.baseline_samples:
                    self.baseline_ms = statistics.median(self._base)
        self._bad_streak = self._bad_streak + 1 if self._is_bad() else 0

    def _is_bad(self) -> bool:
        if not self._win:
            return False
        n = len(self._win)
        if n >= max(5, self.window // 2):       # ventana con muestras suficientes
            timeouts = sum(1 for _, t in self._win if t)
            if timeouts / n > 0.20:
                return True
        if self.baseline_ms is None:
            return False
        oks = [ms for ms, t in self._win if not t]
        if not oks:
            return False
        threshold = max(self.min_ms, self.baseline_ms * self.factor)
        return statistics.median(oks) > threshold

    def verdict(self) -> str:
        return "degraded" if self._bad_streak >= self.sustain else "ok"

    def reset_window(self) -> None:
        """Tras una pausa de seguridad: descarta la ventana (conserva el baseline)."""
        self._win.clear()
        self._bad_streak = 0

    @property
    def p50(self) -> float:
        return statistics.median(self._all) if self._all else 0.0

    @property
    def p95(self) -> float:
        if not self._all:
            return 0.0
        s = sorted(self._all)
        return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]

    def summary(self) -> dict:
        return {"baseline": round(self.baseline_ms or 0.0, 1), "p50": round(self.p50, 1),
                "p95": round(self.p95, 1), "max": round(self.max_ms, 1)}
