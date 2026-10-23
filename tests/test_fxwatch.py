import datetime as dt
import os
import tempfile
import unittest
from unittest import mock

from fxwatch import main, providers, rates

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 1 GBP = 10.00 HKD, 1.30 USD, 200 JPY, 1.15 EUR
GBP = {"HKD": 10.0, "USD": 1.3, "JPY": 200.0, "EUR": 1.15}


def fake_latest(base, symbols):
    in_gbp = {"GBP": 1.0, **GBP}  # units of ccy per 1 GBP
    return {s: in_gbp[s] / in_gbp[base] for s in set(symbols) - {base}}


def fake_get_json(url, params=None, timeout=20):
    if "wise.com" in url:
        assert params["sourceCurrency"] == "HKD"
        return {"providers": [
            {"name": "Wise", "quotes": [{"rate": 0.0995, "fee": 40, "receivedAmount": 4965.0}]},
            {"name": "Some Bank", "quotes": [{"rate": 0.097, "fee": 0, "receivedAmount": 4850.0},
                                             {"rate": 0.0975, "fee": 0, "receivedAmount": 4875.0}]},
            {"name": "No quotes", "quotes": []},
        ]}
    raise AssertionError(url)


def alert(**kw):
    a = {"name": "HKD -> GBP", "pair": "GBP/HKD", "sell": "HKD", "buy": "GBP",
         "amount": 50000, "target": 10.1, "basis": "best"}
    a.update(kw)
    return a


CFG = {"settings": {}, "wise_comparison": {"enabled": True},
       "provider": [{"name": "Broker", "margin_pct": 0.1, "fee": 2, "fee_currency": "USD"},
                    {"name": "EUR only", "margin_pct": 0, "currencies": ["GBP", "EUR"]}]}


@mock.patch("fxwatch.providers.get_json", fake_get_json)
@mock.patch("fxwatch.rates.history", lambda b, q, d: [("d1", 9.8), ("d2", 10.4)])
@mock.patch("fxwatch.rates.latest_rates", fake_latest)
class EvaluateTest(unittest.TestCase):
    def test_quotes_ranked_and_converted(self):
        r = main.evaluate(alert(), CFG)
        self.assertAlmostEqual(r.mid, 10.0)
        names = [q.provider for _, q in r.quotes]
        self.assertEqual(names, ["Broker", "Wise", "Some Bank"])  # "EUR only" filtered out
        # Broker: (50000 - 2 USD in HKD) * 0.1 * (1 - 0.001)
        fee_hkd = 2 / 1.3 * 10
        self.assertAlmostEqual(r.quotes[0][1].received, (50000 - fee_hkd) * 0.1 * 0.999)
        # Bank keeps its best quote; rate is HKD per GBP
        self.assertAlmostEqual(r.quotes[2][0], 50000 / 4875)
        self.assertEqual((r.low, r.high), (9.8, 10.4))

    def test_hit_direction_buying_base(self):
        self.assertTrue(main.evaluate(alert(target=10.1), CFG).hit)   # best ~10.01 <= 10.1
        self.assertFalse(main.evaluate(alert(target=10.0), CFG).hit)
        self.assertTrue(main.evaluate(alert(target=10.0, basis="mid"), CFG).hit)

    def test_hit_direction_selling_base(self):
        cfg = {**CFG, "wise_comparison": {"enabled": False}}
        jpy = alert(name="JPY", pair="GBP/JPY", sell="GBP", buy="JPY", amount=1000, basis="mid")
        self.assertTrue(main.evaluate({**jpy, "target": 199}, cfg).hit)
        self.assertFalse(main.evaluate({**jpy, "target": 201}, cfg).hit)

    def test_wise_failure_is_not_fatal(self):
        with mock.patch("fxwatch.providers.get_json", side_effect=OSError("blocked")):
            r = main.evaluate(alert(), CFG)
        self.assertEqual([q.provider for _, q in r.quotes], ["Broker"])
        self.assertIn("blocked", r.errors[0])


class CooldownTest(unittest.TestCase):
    def setUp(self):
        self.r = main.Result(alert(target=10.1, basis="mid"), mid=10.0)
        self.now = dt.datetime(2026, 10, 23, 12, tzinfo=dt.timezone.utc)
        self.settings = {"cooldown_hours": 12, "realert_improvement_pct": 0.5}

    def state(self, hours_ago, rate):
        return {"HKD -> GBP": {"sent_at": (self.now - dt.timedelta(hours=hours_ago)).isoformat(), "rate": rate}}

    def test_first_hit_notifies(self):
        self.assertTrue(main.should_notify(self.r, {}, self.settings, self.now))

    def test_cooldown_suppresses_repeat(self):
        self.assertFalse(main.should_notify(self.r, self.state(1, 10.02), self.settings, self.now))
        self.assertTrue(main.should_notify(self.r, self.state(13, 10.02), self.settings, self.now))

    def test_big_improvement_breaks_cooldown(self):
        self.assertTrue(main.should_notify(self.r, self.state(1, 10.1), self.settings, self.now))
        # a worse rate never re-alerts early
        self.assertFalse(main.should_notify(self.r, self.state(1, 9.9), self.settings, self.now))

    def test_no_hit_no_notify(self):
        r = main.Result(alert(target=9.0, basis="mid"), mid=10.0)
        self.assertFalse(main.should_notify(r, {}, self.settings, self.now))


class ConfigTest(unittest.TestCase):
    def test_shipped_config_is_valid(self):
        cfg = main.load_config(os.path.join(ROOT, "config.toml"))
        self.assertGreaterEqual(len(cfg["alert"]), 1)

    def test_mismatched_pair_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write('[[alert]]\nname="x"\npair="GBP/HKD"\nsell="USD"\nbuy="GBP"\namount=1\ntarget=1\n')
        try:
            with self.assertRaises(ValueError):
                main.load_config(f.name)
        finally:
            os.unlink(f.name)


@mock.patch("fxwatch.providers.get_json", fake_get_json)
@mock.patch("fxwatch.rates.history", lambda b, q, d: [])
@mock.patch("fxwatch.rates.latest_rates", fake_latest)
class RunTest(unittest.TestCase):
    def test_run_notifies_once_and_saves_state(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path, state_path = os.path.join(d, "c.toml"), os.path.join(d, "s", "state.json")
            with open(cfg_path, "w") as f:
                f.write('[[alert]]\nname="HKD -> GBP"\npair="GBP/HKD"\nsell="HKD"\nbuy="GBP"\n'
                        'amount=50000\ntarget=10.1\n')
            with mock.patch("fxwatch.notify.send", return_value="whatsapp") as send, \
                 mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": os.path.join(d, "summary.md")}):
                self.assertEqual(main.run(["--config", cfg_path, "--state", state_path, "--settings", os.path.join(d, "settings.json")]), 0)
                self.assertEqual(main.run(["--config", cfg_path, "--state", state_path, "--settings", os.path.join(d, "settings.json")]), 0)
            self.assertEqual(send.call_count, 1)
            self.assertIn("Wise", send.call_args[0][0])
            with open(os.path.join(d, "summary.md")) as f:
                self.assertIn("**HIT**", f.read())


class RatesTest(unittest.TestCase):
    def test_falls_back_to_er_api(self):
        def get(url, params=None):
            if "frankfurter" in url:
                raise OSError("down")
            return {"rates": {"GBP": 0.1, "USD": 0.128}}
        with mock.patch("fxwatch.rates.get_json", get):
            self.assertEqual(rates.latest_rates("HKD", ["GBP", "USD", "HKD"]), {"GBP": 0.1, "USD": 0.128})


if __name__ == "__main__":
    unittest.main()
