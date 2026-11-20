from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .paths import app_data_dir

logger = logging.getLogger(__name__)

HOUR_SECONDS = 3600.0
DAY_SECONDS = 86400.0


@dataclass(frozen=True)
class RatePolicy:
    """Delays and caps applied while adding participants to a group.

    Delays are short on purpose: the protection comes from the caps and the
    break between runs, not from blocking the process for minutes.
    """

    name: str
    label: str
    min_delay: float
    max_delay: float
    batch_size: int
    batch_pause_min: float
    batch_pause_max: float
    hourly_cap: int
    daily_cap: int
    cooldown: float

    def next_delay(self, rng: random.Random | None = None) -> float:
        source = rng if rng is not None else random
        return source.uniform(self.min_delay, self.max_delay)

    def next_batch_pause(self, rng: random.Random | None = None) -> float:
        source = rng if rng is not None else random
        return source.uniform(self.batch_pause_min, self.batch_pause_max)


POLICIES: dict[str, RatePolicy] = {
    "cauto": RatePolicy(
        name="cauto",
        label="Cauto (recomendado)",
        min_delay=12.0,
        max_delay=22.0,
        batch_size=5,
        batch_pause_min=40.0,
        batch_pause_max=60.0,
        hourly_cap=25,
        daily_cap=60,
        cooldown=15 * 60.0,
    ),
    "normal": RatePolicy(
        name="normal",
        label="Normal",
        min_delay=7.0,
        max_delay=13.0,
        batch_size=6,
        batch_pause_min=25.0,
        batch_pause_max=40.0,
        hourly_cap=45,
        daily_cap=120,
        cooldown=8 * 60.0,
    ),
    "rapido": RatePolicy(
        name="rapido",
        label="Rapido (mayor riesgo)",
        min_delay=3.0,
        max_delay=6.0,
        batch_size=5,
        batch_pause_min=12.0,
        batch_pause_max=20.0,
        hourly_cap=80,
        daily_cap=240,
        cooldown=3 * 60.0,
    ),
}

DEFAULT_POLICY_NAME = "cauto"


def get_policy(name: str | None) -> RatePolicy:
    """Return the policy for a name, falling back to the default one."""
    return POLICIES.get(name or "", POLICIES[DEFAULT_POLICY_NAME])


def default_policy() -> RatePolicy:
    return POLICIES[DEFAULT_POLICY_NAME]


class UsageLimiter:
    """Keeps recent add timestamps on disk to enforce caps across restarts.

    Nothing here sleeps: when a cap or the cooldown is active, callers get a
    message explaining how long to wait instead of a blocked process.
    """

    def __init__(
        self,
        path: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = path or app_data_dir() / "rate-limit.json"
        self._clock = clock
        self._events: list[float] = []
        self._last_run_end = 0.0
        self._load()

    # ----------------------------------------------------------- persistence

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            logger.warning(
                "Could not read %s, starting with empty limits",
                self._path,
                exc_info=True,
            )
            return

        if not isinstance(raw, dict):
            return

        events = raw.get("events")
        if isinstance(events, list):
            self._events = [
                float(value)
                for value in events
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            ]
        last_run_end = raw.get("last_run_end")
        if isinstance(last_run_end, (int, float)) and not isinstance(last_run_end, bool):
            self._last_run_end = float(last_run_end)

    def _save(self) -> None:
        payload = {
            "events": self._events[-2000:],
            "last_run_end": self._last_run_end,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(payload, separators=(",", ":")),
                encoding="utf-8",
            )
        except OSError:
            logger.warning(
                "Could not persist rate limits to %s",
                self._path,
                exc_info=True,
            )

    # ---------------------------------------------------------------- counters

    def _recent(self, seconds: float) -> list[float]:
        now = self._clock()
        self._events = [at for at in self._events if now - at < DAY_SECONDS]
        return [at for at in self._events if now - at < seconds]

    def record(self) -> None:
        now = self._clock()
        self._events.append(now)
        self._events = [at for at in self._events if now - at < DAY_SECONDS]
        self._save()

    def mark_run_finished(self) -> None:
        self._last_run_end = self._clock()
        self._save()

    def remaining_this_hour(self, policy: RatePolicy) -> int:
        return max(0, policy.hourly_cap - len(self._recent(HOUR_SECONDS)))

    def remaining_today(self, policy: RatePolicy) -> int:
        return max(0, policy.daily_cap - len(self._recent(DAY_SECONDS)))

    # --------------------------------------------------------------- decision

    def blocked_reason(self, policy: RatePolicy) -> str | None:
        """Return why adding is not allowed right now, or None when it is."""
        now = self._clock()
        last_hour = self._recent(HOUR_SECONDS)
        last_day = self._recent(DAY_SECONDS)

        if len(last_day) >= policy.daily_cap:
            return (
                f"Limite diario alcanzado ({policy.daily_cap} agregados). "
                "Proba de nuevo manana."
            )

        if len(last_hour) >= policy.hourly_cap:
            wait = _wait_minutes(min(last_hour) + HOUR_SECONDS - now)
            return (
                f"Limite por hora alcanzado ({policy.hourly_cap} agregados). "
                f"Espera ~{wait} minutos."
            )

        if policy.cooldown > 0 and self._last_run_end:
            elapsed = now - self._last_run_end
            if elapsed < policy.cooldown:
                wait = _wait_minutes(policy.cooldown - elapsed)
                return (
                    f"Descanso entre tandas: espera ~{wait} minutos "
                    "para reducir el riesgo de bloqueo."
                )

        return None


def _wait_minutes(seconds: float) -> int:
    return max(1, int(seconds / 60) + 1)
