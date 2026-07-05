import unittest
from unittest.mock import patch

from adb_automation import stochastic
from adb_automation.errors import AutomationError


class FakeDriver:
    def __init__(self, outputs=None):
        self.outputs = outputs or {}
        self.scripts = []
        self.quit_called = False

    def execute_script(self, script, payload):
        self.scripts.append((script, payload))
        key = (payload["command"], tuple(payload["args"]))
        result = self.outputs.get(key)
        if isinstance(result, Exception):
            raise result
        return result or ""

    def quit(self):
        self.quit_called = True


class FirstRng:
    def sample(self, population, count):
        return list(population)[:count]


class MockDriverFactoryError:
    def __call__(self, serial, server_url):
        raise AutomationError("UiAutomation not connected")


class StochasticDiscoveryTests(unittest.TestCase):
    def test_discover_launchable_apps_prefers_safe_non_system_packages(self):
        driver = FakeDriver(
            {
                ("pm", ("list", "packages", "-3")): (
                    "package:com.example.notes\n"
                    "package:com.example.mail\n"
                    "package:com.whatsapp\n"
                    "package:io.appium.uiautomator2.server\n"
                    "package:com.google.android.youtube\n"
                ),
                (
                    "cmd",
                    (
                        "package",
                        "query-activities",
                        "-a",
                        "android.intent.action.MAIN",
                        "-c",
                        "android.intent.category.LAUNCHER",
                    ),
                ): (
                    "ActivityInfo{abc com.example.notes/.MainActivity}\n"
                    "packageName=com.example.mail\n"
                    "packageName=com.whatsapp\n"
                    "packageName=com.google.android.youtube\n"
                ),
            }
        )

        packages = stochastic.discover_launchable_apps(
            driver,
            "192.168.10.21:5555",
            run_adb_command=lambda command, serial=None: "",
        )

        self.assertEqual(packages, ["com.example.notes", "com.example.mail"])

    def test_discover_launchable_apps_falls_back_to_adb_when_appium_shell_fails(self):
        driver = FakeDriver(
            {
                ("pm", ("list", "packages", "-3")): Exception("mobile shell disabled"),
                (
                    "cmd",
                    (
                        "package",
                        "query-activities",
                        "-a",
                        "android.intent.action.MAIN",
                        "-c",
                        "android.intent.category.LAUNCHER",
                    ),
                ): Exception("mobile shell disabled"),
            }
        )

        def fake_run_adb(command, serial=None):
            if command[:4] == ["shell", "pm", "list", "packages"]:
                return "package:com.example.notes\n"
            if command[:3] == ["shell", "cmd", "package"]:
                return "packageName=com.example.notes\n"
            return ""

        with patch("builtins.print"):
            packages = stochastic.discover_launchable_apps(
                driver,
                "192.168.10.21:5555",
                run_adb_command=fake_run_adb,
            )

        self.assertEqual(packages, ["com.example.notes"])


class StochasticRunTests(unittest.TestCase):
    def test_run_stochastic_actions_uses_adb_discovery_without_appium(self):
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append(command)
            if command[:4] == ["shell", "pm", "list", "packages"]:
                return (
                    "package:com.example.notes\n"
                    "package:com.example.mail\n"
                    "package:com.example.music\n"
                )
            if command[:3] == ["shell", "cmd", "package"]:
                return (
                    "packageName=com.example.notes\n"
                    "packageName=com.example.mail\n"
                    "packageName=com.example.music\n"
                )
            return ""

        with patch("builtins.print"):
            stochastic.run_stochastic_actions(
                "192.168.10.21:5555",
                rng=FirstRng(),
                run_adb_command=fake_run_adb,
                driver_factory=MockDriverFactoryError(),
                sleep=lambda seconds: None,
            )

        self.assertIn(
            ["shell", "am", "force-stop", "com.whatsapp"],
            commands,
        )
        self.assertIn(
            ["shell", "am", "force-stop", "com.whatsapp.w4b"],
            commands,
        )
        self.assertIn(
            [
                "shell",
                "monkey",
                "-p",
                "com.example.notes",
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
            commands,
        )
        self.assertIn(
            [
                "shell",
                "monkey",
                "-p",
                "com.example.mail",
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
            commands,
        )
        self.assertIn(
            ["shell", "input", "keyevent", "KEYCODE_SLEEP"],
            commands,
        )
        self.assertIn(
            ["shell", "input", "keyevent", "KEYCODE_WAKEUP"],
            commands,
        )

    def test_run_stochastic_actions_falls_back_to_appium_when_adb_discovery_fails(self):
        driver = FakeDriver(
            {
                ("pm", ("list", "packages", "-3")): (
                    "package:com.example.notes\n"
                    "package:com.example.mail\n"
                ),
                (
                    "cmd",
                    (
                        "package",
                        "query-activities",
                        "-a",
                        "android.intent.action.MAIN",
                        "-c",
                        "android.intent.category.LAUNCHER",
                    ),
                ): (
                    "packageName=com.example.notes\n"
                    "packageName=com.example.mail\n"
                ),
            }
        )
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append(command)
            if command[:4] == ["shell", "pm", "list", "packages"]:
                raise AutomationError("adb discovery failed")
            return ""

        with patch("builtins.print"):
            stochastic.run_stochastic_actions(
                "192.168.10.21:5555",
                rng=FirstRng(),
                run_adb_command=fake_run_adb,
                driver_factory=lambda serial, server_url: driver,
                sleep=lambda seconds: None,
            )

        self.assertTrue(driver.quit_called)
        self.assertIn(
            [
                "shell",
                "monkey",
                "-p",
                "com.example.notes",
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
            commands,
        )

    def test_run_stochastic_actions_survives_appium_session_failure_when_adb_works(self):
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append(command)
            if command[:4] == ["shell", "pm", "list", "packages"]:
                return "package:com.example.notes\n"
            if command[:3] == ["shell", "cmd", "package"]:
                return "packageName=com.example.notes\n"
            return ""

        with patch("builtins.print"):
            stochastic.run_stochastic_actions(
                "192.168.10.21:5555",
                rng=FirstRng(),
                run_adb_command=fake_run_adb,
                driver_factory=MockDriverFactoryError(),
                sleep=lambda seconds: None,
            )

        self.assertIn(
            [
                "shell",
                "monkey",
                "-p",
                "com.example.notes",
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
            commands,
        )

    def test_run_stochastic_actions_succeeds_when_no_safe_apps_are_found(self):
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append(command)
            if command[:4] == ["shell", "pm", "list", "packages"]:
                return "package:com.whatsapp\n"
            if command[:3] == ["shell", "cmd", "package"]:
                return "packageName=com.whatsapp\n"
            return ""

        with patch("builtins.print") as print_mock:
            stochastic.run_stochastic_actions(
                "192.168.10.21:5555",
                rng=FirstRng(),
                run_adb_command=fake_run_adb,
                driver_factory=MockDriverFactoryError(),
                sleep=lambda seconds: None,
            )

        self.assertFalse(any(command[:2] == ["shell", "monkey"] for command in commands))
        self.assertTrue(
            any(
                "No safe launchable apps" in str(call.args[0])
                for call in print_mock.call_args_list
            )
        )
        self.assertIn(
            ["shell", "input", "keyevent", "KEYCODE_WAKEUP"],
            commands,
        )

    def test_run_stochastic_actions_succeeds_when_appium_and_adb_discovery_fail(self):
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append(command)
            if command[:4] == ["shell", "pm", "list", "packages"]:
                raise AutomationError("adb discovery failed")
            return ""

        with patch("builtins.print") as print_mock:
            stochastic.run_stochastic_actions(
                "192.168.10.21:5555",
                rng=FirstRng(),
                run_adb_command=fake_run_adb,
                driver_factory=MockDriverFactoryError(),
                sleep=lambda seconds: None,
            )

        self.assertFalse(any(command[:2] == ["shell", "monkey"] for command in commands))
        self.assertTrue(
            any(
                "Appium unavailable" in str(call.args[0])
                for call in print_mock.call_args_list
            )
        )
        self.assertIn(
            ["shell", "input", "keyevent", "KEYCODE_WAKEUP"],
            commands,
        )


if __name__ == "__main__":
    unittest.main()
