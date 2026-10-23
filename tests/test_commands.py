import os
import tempfile
import unittest
from unittest import mock

from fxwatch import commands, main, store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def setup():
    cfg = main.load_config(os.path.join(ROOT, "config.toml"))
    data = store.load("/nonexistent/settings.json")
    store.apply(cfg, data)
    return cfg, data


def alert(cfg, pair):
    return next(a for a in cfg["alert"] if a["pair"] == pair)


def watch(cfg, pair):
    return next(w for w in cfg["watch"] if w["pair"] == pair)


class HandleTest(unittest.TestCase):
    def test_set_target(self):
        cfg, data = setup()
        self.assertIn("OK", commands.handle("/target gbp/hkd 10,050", cfg, data))
        self.assertEqual(alert(cfg, "GBP/HKD")["target"], 10050)
        self.assertEqual(data["alerts"]["GBP/HKD"]["target"], 10050)

    def test_levels_and_clear(self):
        cfg, data = setup()
        commands.handle("/above AUD/USD 0.68", cfg, data)
        commands.handle("/below AUD/USD 0.64", cfg, data)
        self.assertEqual((watch(cfg, "AUD/USD")["above"], watch(cfg, "AUD/USD")["below"]), (0.68, 0.64))
        commands.handle("/clear AUD/USD above", cfg, data)
        self.assertNotIn("above", watch(cfg, "AUD/USD"))
        self.assertEqual(data["watches"]["AUD/USD"], {"above": None, "below": 0.64})

    def test_pause_resume(self):
        cfg, data = setup()
        commands.handle("/pause GBP/JPY", cfg, data)
        self.assertTrue(alert(cfg, "GBP/JPY")["paused"])
        self.assertIn("(paused)", commands.handle("/list", cfg, data))
        commands.handle("/resume GBP/JPY", cfg, data)
        self.assertFalse(alert(cfg, "GBP/JPY")["paused"])

    def test_errors_do_not_change_data(self):
        cfg, data = setup()
        self.assertIn("Error", commands.handle("/target XXX/YYY 1", cfg, data))
        self.assertIn("Error", commands.handle("/target GBP/HKD abc", cfg, data))
        self.assertIn("Unknown command", commands.handle("/hello", cfg, data))
        self.assertEqual(data, {"alerts": {}, "watches": {}})

    def test_bot_suffix(self):
        cfg, data = setup()
        self.assertIn("Conversion alerts", commands.handle("/list@my_fx_bot", cfg, data))


class PersistenceTest(unittest.TestCase):
    def test_saved_overrides_survive_reload(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "data", "settings.json")
            cfg, data = setup()
            commands.handle("/target GBP/USD 1.25", cfg, data)
            commands.handle("/clear AUD/USD", cfg, data)
            store.save(data, path)

            cfg2 = store.apply(main.load_config(os.path.join(ROOT, "config.toml")), store.load(path))
            self.assertEqual(alert(cfg2, "GBP/USD")["target"], 1.25)
            self.assertNotIn("above", watch(cfg2, "AUD/USD"))

    def test_run_applies_telegram_commands_and_saves(self):
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            cfg = os.path.join(d, "c.toml")
            with open(cfg, "w") as f:
                f.write('[[alert]]\nname="x"\npair="GBP/HKD"\nsell="HKD"\nbuy="GBP"\namount=1\ntarget=10\n')
            with mock.patch("fxwatch.notify.telegram_commands", return_value=(["/target GBP/HKD 9.9"], 42)), \
                 mock.patch("fxwatch.notify.telegram_reply") as reply, \
                 mock.patch("fxwatch.main.evaluate", side_effect=RuntimeError("offline")):
                main.run(["--config", cfg, "--state", os.path.join(d, "s.json"), "--settings", settings])
            reply.assert_called_once_with("OK: GBP/HKD target is now 9.9")
            saved = store.load(settings)
            self.assertEqual((saved["alerts"]["GBP/HKD"]["target"], saved["telegram_offset"]), (9.9, 42))

    def test_dry_run_saves_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            with mock.patch("fxwatch.main.evaluate", side_effect=RuntimeError("offline")), \
                 mock.patch("fxwatch.main.evaluate_watch", side_effect=RuntimeError("offline")):
                main.run(["--config", os.path.join(ROOT, "config.toml"), "--dry-run",
                          "--settings", settings, "--command", "/target GBP/HKD 9.9"])
            self.assertFalse(os.path.exists(settings))


if __name__ == "__main__":
    unittest.main()
