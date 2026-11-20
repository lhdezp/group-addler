from __future__ import annotations

import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from group_addler.limits import (
    DEFAULT_POLICY_NAME,
    HOUR_SECONDS,
    POLICIES,
    UsageLimiter,
    get_policy,
)


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class PolicyTests(unittest.TestCase):
    def test_unknown_name_falls_back_to_default(self) -> None:
        self.assertIs(get_policy("nope"), POLICIES[DEFAULT_POLICY_NAME])
        self.assertIs(get_policy(None), POLICIES[DEFAULT_POLICY_NAME])

    def test_delays_stay_inside_policy_range(self) -> None:
        policy = get_policy("cauto")
        rng = random.Random(7)

        delays = [policy.next_delay(rng) for _ in range(50)]

        self.assertTrue(
            all(policy.min_delay <= value <= policy.max_delay for value in delays)
        )
        self.assertGreater(len(set(delays)), 1)

    def test_batch_pause_stays_inside_policy_range(self) -> None:
        policy = get_policy("normal")
        rng = random.Random(3)

        pauses = [policy.next_batch_pause(rng) for _ in range(20)]

        self.assertTrue(
            all(
                policy.batch_pause_min <= value <= policy.batch_pause_max
                for value in pauses
            )
        )


class UsageLimiterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "rate-limit.json"
        self.clock = FakeClock()
        self.policy = get_policy("cauto")

    def make_limiter(self) -> UsageLimiter:
        return UsageLimiter(self.path, clock=self.clock)

    def test_records_reduce_remaining_margin(self) -> None:
        limiter = self.make_limiter()
        self.assertEqual(
            limiter.remaining_this_hour(self.policy), self.policy.hourly_cap
        )

        limiter.record()

        self.assertEqual(
            limiter.remaining_this_hour(self.policy), self.policy.hourly_cap - 1
        )
        self.assertEqual(
            limiter.remaining_today(self.policy), self.policy.daily_cap - 1
        )

    def test_hourly_cap_blocks_only_until_window_passes(self) -> None:
        limiter = self.make_limiter()
        for _ in range(self.policy.hourly_cap):
            limiter.record()
            self.clock.advance(1)

        reason = limiter.blocked_reason(self.policy)
        self.assertIsNotNone(reason)
        self.assertIn("Limite por hora", reason or "")

        self.clock.advance(HOUR_SECONDS)

        self.assertIsNone(limiter.blocked_reason(self.policy))

    def test_daily_cap_blocks(self) -> None:
        policy = replace(self.policy, hourly_cap=100, daily_cap=10)
        limiter = self.make_limiter()
        for _ in range(policy.daily_cap):
            limiter.record()

        reason = limiter.blocked_reason(policy)

        self.assertIsNotNone(reason)
        self.assertIn("diario", reason or "")

    def test_cooldown_blocks_next_run(self) -> None:
        limiter = self.make_limiter()
        limiter.record()
        limiter.mark_run_finished()

        self.assertIsNotNone(limiter.blocked_reason(self.policy))

        self.clock.advance(self.policy.cooldown + 1)

        self.assertIsNone(limiter.blocked_reason(self.policy))

    def test_state_survives_reload(self) -> None:
        limiter = self.make_limiter()
        limiter.record()
        limiter.mark_run_finished()

        reloaded = self.make_limiter()

        self.assertEqual(
            reloaded.remaining_today(self.policy), self.policy.daily_cap - 1
        )
        self.assertIsNotNone(reloaded.blocked_reason(self.policy))

    def test_corrupt_file_is_ignored(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{ not json", encoding="utf-8")

        limiter = self.make_limiter()

        self.assertEqual(
            limiter.remaining_today(self.policy), self.policy.daily_cap
        )


if __name__ == "__main__":
    unittest.main()
