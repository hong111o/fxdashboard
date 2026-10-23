import datetime as dt
import os
import tempfile
import unittest
from unittest import mock

from fxwatch import main, signals


def series(values):
    start = dt.date(2026, 1, 1)
    return [((start + dt.timedelta(days=i)).isoformat(), v) for i, v in enumerate(values)]


def kinds(sigs):
    return sorted(s.key.split(":")[1] for s in sigs)


class ComputeTest(unittest.TestCase):
    W = {"pair": "AUD/USD"}

    def test_levels(self):
        s = series([0.66, 0.65])
        self.assertEqual(kinds(signals.compute({**self.W, "below": 0.655}, s)), ["below"])
        self.assertEqual(kinds(signals.compute({**self.W, "above": 0.65}, s)), ["above"])
        self.assertEqual(signals.compute({**self.W, "below": 0.60, "above": 0.70}, s), [])

    def test_move(self):
        w = {**self.W, "move_pct": 1.0}
        self.assertEqual(kinds(signals.compute(w, series([0.660, 0.670]))), ["move"])
        self.assertEqual(kinds(signals.compute(w, series([0.660, 0.650]))), ["move"])
        self.assertEqual(signals.compute(w, series([0.660, 0.664])), [])

    def test_breakout(self):
        w = {**self.W, "breakout_days": 3}
        self.assertEqual(kinds(signals.compute(w, series([1, 2, 3, 2.5, 3.1]))), ["high"])
        self.assertEqual(kinds(signals.compute(w, series([5, 2, 3, 2.5, 1.9]))), ["low"])
        self.assertEqual(signals.compute(w, series([1, 2, 3, 2.5, 2.9])), [])
        self.assertEqual(signals.compute(w, series([1, 2, 3])), [])  # not enough data

    def test_sma_cross(self):
        w = {**self.W, "sma_days": 3}
        self.assertEqual(kinds(signals.compute(w, series([5, 5, 5, 4, 6]))), ["sma_up"])
        self.assertEqual(kinds(signals.compute(w, series([5, 5, 5, 6, 4]))), ["sma_down"])
        self.assertEqual(signals.compute(w, series([5, 5, 5, 6, 6.5])), [])

    def test_dated_keys(self):
        sig = signals.compute({**self.W, "move_pct": 1}, series([1, 1.1]))[0]
        self.assertTrue(sig.dated)
        self.assertTrue(sig.key.endswith("2026-01-02"))

    def test_history_window(self):
        self.assertGreaterEqual(signals.calendar_days_needed({"sma_days": 50}), 51 * 7 / 5)


class WatchRunTest(unittest.TestCase):
    def run_twice(self, cfg_text, values, now_offsets=(0, 1)):
        with tempfile.TemporaryDirectory() as d:
            cfg, state = os.path.join(d, "c.toml"), os.path.join(d, "state.json")
            with open(cfg, "w") as f:
                f.write(cfg_text)
            sent = []
            with mock.patch("fxwatch.rates.history", lambda b, q, n: series(values)), \
                 mock.patch("fxwatch.notify.send", side_effect=lambda t: sent.append(t) or "telegram"):
                for _ in now_offsets:
                    self.assertEqual(main.run(["--config", cfg, "--state", state, "--settings", os.path.join(d, "settings.json")]), 0)
            return sent

    def test_dated_signal_fires_once(self):
        sent = self.run_twice('[[watch]]\npair="aud/usd"\nmove_pct=1\n', [0.66, 0.67])
        self.assertEqual(len(sent), 1)
        self.assertIn("AUD/USD", sent[0])
        self.assertIn("up +1.52%", sent[0])

    def test_level_signal_respects_cooldown(self):
        sent = self.run_twice('[[watch]]\npair="AUD/USD"\nbelow=0.7\n', [0.66, 0.67])
        self.assertEqual(len(sent), 1)

    def test_no_signal_no_message(self):
        self.assertEqual(self.run_twice('[[watch]]\npair="AUD/USD"\nmove_pct=5\n', [0.66, 0.67]), [])


class PruneTest(unittest.TestCase):
    def test_prune_old_entries(self):
        now = dt.datetime(2026, 10, 23, tzinfo=dt.timezone.utc)
        state = {"old": {"sent_at": (now - dt.timedelta(days=40)).isoformat()},
                 "new": {"sent_at": (now - dt.timedelta(days=1)).isoformat()}}
        self.assertEqual(list(main.prune_state(state, now)), ["new"])


if __name__ == "__main__":
    unittest.main()
