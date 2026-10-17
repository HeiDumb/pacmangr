#!/usr/bin/env python3

import importlib.machinery
import importlib.util
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "pacmangr-gui"
LOADER = importlib.machinery.SourceFileLoader("pacmangr_gui_test", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
GUI = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = GUI
LOADER.exec_module(GUI)


class GuiOperationCommandTests(unittest.TestCase):
    def setUp(self):
        self.tools = SimpleNamespace(sudo="/usr/bin/sudo", doas=None)

    def test_pacman_uses_pkexec_without_prompts(self):
        command = ["/usr/bin/sudo", "/usr/bin/pacman", "-S", "demo"]
        result = GUI.prepare_gui_operation(
            command, self.tools, "install", "/usr/bin/pkexec"
        )
        self.assertEqual(
            result,
            [
                "/usr/bin/pkexec",
                "/usr/bin/pacman",
                "-S",
                "--noconfirm",
                "--needed",
                "demo",
            ],
        )

    def test_aur_helper_delegates_privilege_to_pkexec(self):
        command = ["/usr/bin/yay", "-S", "demo-git"]
        result = GUI.prepare_gui_operation(
            command, self.tools, "install", "/usr/bin/pkexec"
        )
        self.assertEqual(
            result,
            [
                "/usr/bin/yay",
                "--sudo",
                "/usr/bin/pkexec",
                "-S",
                "--noconfirm",
                "--needed",
                "demo-git",
            ],
        )

    def test_flatpak_is_noninteractive_without_privilege(self):
        command = ["/usr/bin/flatpak", "install", "flathub", "org.demo.App"]
        result = GUI.prepare_gui_operation(command, self.tools, "install", None)
        self.assertEqual(
            result,
            [
                "/usr/bin/flatpak",
                "install",
                "--noninteractive",
                "-y",
                "flathub",
                "org.demo.App",
            ],
        )

    def test_privileged_command_requires_pkexec(self):
        with self.assertRaisesRegex(RuntimeError, "polkit"):
            GUI.prepare_gui_operation(
                ["/usr/bin/sudo", "/usr/bin/pacman", "-S", "demo"],
                self.tools,
                "install",
                None,
            )

    def test_source_choices_include_detected_extra_managers(self):
        tools = SimpleNamespace(
            pacman="/usr/bin/pacman",
            yay=None,
            paru=None,
            flatpak="/usr/bin/flatpak",
            apt_cache=None,
            snap=None,
            git="/usr/bin/git",
            extra_managers={"nix": "/nix/bin/nix-env"},
        )
        choices = GUI.source_choices(tools)
        self.assertIn(("All sources", "all"), choices)
        self.assertIn(("System packages", "pacman"), choices)
        self.assertIn(("Nix", "nix"), choices)
        self.assertIn(("Git repository", "git"), choices)

    def test_cli_operation_parser_supports_source_yes_and_dry_run(self):
        self.assertEqual(
            GUI.CORE.parse_cli_operation(["demo", "--source", "flatpak", "-y", "--dry-run"]),
            ("demo", "flatpak", "user", True, True),
        )

    def test_update_commands_keep_package_sources_separate(self):
        tools = SimpleNamespace(
            aur_helper=None,
            pacman="/usr/bin/pacman",
            privilege="/usr/bin/sudo",
            flatpak="/usr/bin/flatpak",
            apt=None,
            snap=None,
            git=None,
            extra_managers={},
        )
        commands = GUI.CORE.system_update_commands(tools)
        self.assertEqual(commands[0], ("pacman", ["/usr/bin/sudo", "/usr/bin/pacman", "-Syu"]))
        self.assertEqual(commands[1], ("flatpak", ["/usr/bin/flatpak", "update"]))

    def test_escape_closes_the_gui_window(self):
        app = GUI.PacmangrGUI()
        app.window = Mock()
        self.assertTrue(app.on_key_pressed(None, GUI.Gdk.KEY_Escape, 0, 0))
        app.window.close.assert_called_once_with()

    def test_git_url_becomes_managed_checkout(self):
        item = GUI.CORE.git_package("https://github.com/example/demo.git")
        self.assertIsNotNone(item)
        self.assertEqual(item.source, "git")
        self.assertTrue(item.package_id.endswith("/.local/src/pacmangr/example--demo"))

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_git_fetch_clones_into_managed_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "example.git"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            original = GUI.CORE.GIT_SOURCE_ROOT
            try:
                GUI.CORE.GIT_SOURCE_ROOT = root / "managed"
                item = GUI.CORE.git_package(remote.as_uri())
                self.assertEqual(GUI.CORE.run_git_fetch(item.origin, item.package_id), 0)
                self.assertTrue((Path(item.package_id) / ".git").is_dir())
            finally:
                GUI.CORE.GIT_SOURCE_ROOT = original

    def test_pip_install_supports_venv_user_and_system_scopes(self):
        item = GUI.CORE.PackageItem("pip", "pip", "demo", "demo")
        tools = SimpleNamespace(privilege="/usr/bin/sudo")
        venv = item.install_command(tools, install_scope="venv")
        user = item.install_command(tools, install_scope="user")
        system = item.install_command(tools, install_scope="system")
        self.assertIn("_pip-install", venv)
        self.assertIn("venv", venv)
        self.assertIn("user", user)
        self.assertEqual(system[0], "/usr/bin/sudo")
        self.assertIn("system", system)


class PacmanAnimationTests(unittest.TestCase):
    def test_hex_rgb_accepts_long_and_short_colours(self):
        self.assertEqual(GUI.hex_rgb("#ff8000"), (1.0, 128 / 255, 0.0))
        self.assertEqual(GUI.hex_rgb("abc"), (170 / 255, 187 / 255, 204 / 255))

    def test_hex_rgb_falls_back_for_invalid_colours(self):
        self.assertEqual(GUI.hex_rgb("not-a-colour", "123456"), (18 / 255, 52 / 255, 86 / 255))

    def test_pacman_frame_moves_pellets_and_animates_mouth(self):
        mouth_a, pellets_a = GUI.pacman_frame(0, 148)
        mouth_b, pellets_b = GUI.pacman_frame(4, 148)
        self.assertGreaterEqual(mouth_a, math.radians(8))
        self.assertLessEqual(mouth_a, math.radians(30))
        self.assertGreaterEqual(mouth_b, math.radians(8))
        self.assertLessEqual(mouth_b, math.radians(30))
        self.assertNotEqual(mouth_a, mouth_b)
        self.assertNotEqual(pellets_a, pellets_b)
        self.assertTrue(all(31 < position < 144 for position in pellets_a))

    def test_progress_parser_reads_percent_speed_and_eta(self):
        line, percent, speed, eta = GUI.parse_operation_progress(
            "\x1b[32mdemo 42% 1.5 MiB/s eta 0:00:10\x1b[0m"
        )
        self.assertIn("demo", line)
        self.assertEqual(percent, 42)
        self.assertEqual(speed, "1.5 MiB/s")
        self.assertEqual(eta, "0:00:10")

    def test_eta_formatter_handles_minutes_and_hours(self):
        self.assertEqual(GUI.format_eta(65), "1:05")
        self.assertEqual(GUI.format_eta(3661), "1:01:01")

    def test_streamed_runner_preserves_terminal_progress_lines(self):
        lines = []
        code, output = GUI.run_streamed_operation(
            [
                sys.executable,
                "-c",
                "print('download 67% 2.0 MiB/s eta 0:00:03')",
            ],
            os.environ.copy(),
            lines.append,
            timeout=5,
        )
        self.assertEqual(code, 0)
        self.assertTrue(any("67%" in line for line in lines))
        self.assertIn("2.0 MiB/s", output)


if __name__ == "__main__":
    unittest.main()
