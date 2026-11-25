#!/usr/bin/env python3

import importlib.machinery
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


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

    def test_source_choices_include_appimage_catalog(self):
        tools = SimpleNamespace(
            pacman=None,
            yay=None,
            paru=None,
            flatpak=None,
            apt=None,
            apt_cache=None,
            snap=None,
            git=None,
            extra_managers={},
        )
        self.assertIn(("AppImages", "appimage"), GUI.source_choices(tools))

    def test_check_updates_on_launch_defaults_on_and_persists(self):
        from pacmangr_gui.settings import SettingsManager

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings = SettingsManager(path)
            self.assertTrue(settings.get("check_updates_on_launch"))
            settings.set("check_updates_on_launch", False)
            self.assertFalse(SettingsManager(path).get("check_updates_on_launch"))

    def test_appimage_catalog_search_builds_installable_items(self):
        from pacmangr_core import backends

        feed = [
            {
                "name": "Demo Editor",
                "description": "A demo editor",
                "categories": ["Utility"],
                "links": [
                    {"type": "GitHub", "url": "demo/editor"},
                    {"type": "Download", "url": "https://github.com/demo/editor/releases"},
                ],
                "icons": ["Demo_Editor/icons/demo.png"],
            }
        ]
        with (
            patch.object(backends, "_load_appimage_feed", return_value=feed),
            patch.object(backends, "_appimage_registry", return_value={}),
        ):
            items = backends.search_appimage_catalog("demo")

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.name, "Demo Editor")
        self.assertEqual(item.origin, "https://github.com/demo/editor/releases")
        self.assertEqual(item.catalog_key, "demo-editor")
        self.assertIn("appimage.github.io/database/", item.icon_url)
        command = item.install_command(SimpleNamespace())
        self.assertEqual(
            command[-4:],
            ["_appimage-install", "demo-editor", "Demo Editor", item.origin],
        )

    def test_appimage_feed_cold_cache_fetches_catalog(self):
        from pacmangr_core import backends

        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"items": [{"name": "Demo"}]}).encode()
        with (
            patch.object(backends, "_appimage_feed_cache", (float("-inf"), [])),
            patch.object(backends.urllib.request, "urlopen", return_value=response) as fetch,
        ):
            entries = backends._load_appimage_feed()

        self.assertEqual(entries, [{"name": "Demo"}])
        fetch.assert_called_once()

    def test_official_beeper_and_curseforge_search_without_feed_fetch(self):
        from pacmangr_core import backends

        with (
            patch.object(backends, "platform") as platform,
            patch.object(backends, "_appimage_registry", return_value={}),
            patch.object(
                backends,
                "_load_appimage_feed",
                side_effect=AssertionError("popular app search should be immediate"),
            ),
        ):
            platform.machine.return_value = "x86_64"
            beeper = backends.search_appimage_catalog("Beeper")
            curseforge = backends.search_appimage_catalog("curse forge")

        self.assertEqual([item.name for item in beeper], ["Beeper"])
        self.assertEqual(
            beeper[0].origin,
            "https://api.beeper.com/desktop/download/linux/"
            "x64/stable/com.automattic.beeper.desktop",
        )
        self.assertEqual([item.name for item in curseforge], ["CurseForge"])
        self.assertTrue(curseforge[0].origin.endswith("curseforge-latest-linux.AppImage"))

    def test_beeper_download_resolver_accepts_official_release_endpoint(self):
        from pacmangr_core import cli

        source_url = (
            "https://api.beeper.com/desktop/download/linux/arm64/stable/"
            "com.automattic.beeper.desktop"
        )
        self.assertEqual(
            cli._appimage_release_asset(source_url),
            (source_url, "Beeper.AppImage"),
        )

    def test_appimage_release_resolver_prefers_native_architecture(self):
        from pacmangr_core import cli

        payload = {
            "assets": [
                {
                    "name": "Demo-aarch64.AppImage",
                    "browser_download_url": "https://example.test/arm.AppImage",
                },
                {
                    "name": "Demo-x86_64.AppImage",
                    "browser_download_url": "https://example.test/x64.AppImage",
                },
            ]
        }
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(payload).encode()
        with (
            patch.object(cli.platform, "machine", return_value="x86_64"),
            patch.object(cli.urllib.request, "urlopen", return_value=response),
        ):
            url, filename = cli._appimage_release_asset(
                "https://github.com/demo/editor/releases"
            )

        self.assertEqual(url, "https://example.test/x64.AppImage")
        self.assertEqual(filename, "Demo-x86_64.AppImage")

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


class WallpaperColourTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch

        matugen_dir = tempfile.TemporaryDirectory(prefix="pacmangr-test-matugen-")
        self.addCleanup(matugen_dir.cleanup)
        matugen_path = Path(matugen_dir.name) / "matugen.json"
        self._matugen_patch = patch.object(GUI, "MATUGEN_SCHEME_PATH", matugen_path)
        self._matugen_patch.start()
        self.addCleanup(self._matugen_patch.stop)

        def default_setting(key, default=None):
            if key == "scheme_path":
                return str(GUI.SCHEME_PATH)
            return GUI.SETTINGS.DEFAULTS.get(key, default)

        self._settings_patch = patch.object(GUI.SETTINGS, "get", side_effect=default_setting)
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)

    def test_preview_and_committed_scheme_updates(self):
        import json
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            committed = root / 'scheme.json'
            preview = root / 'preview.json'
            helios = root / 'helios.json'
            committed.write_text(json.dumps({'colours': {'primary': '111111'}}))
            with patch.object(GUI, 'SCHEME_PATH', committed), \
                 patch.object(GUI, 'PREVIEW_SCHEME_PATH', preview), \
                 patch.object(GUI, 'HEILIOS_SCHEME_PATH', helios):
                app = GUI.PacmangrGUI()
                seen = []
                app.apply_colours = lambda *, scheme_colours: seen.append(GUI.palette(scheme_colours=scheme_colours)['primary'])
                app.refresh_colours()
                preview.write_text(json.dumps({'colours': {'primary': '222222'}}))
                app.refresh_colours()
                preview.write_text('{')
                app.refresh_colours()
                preview.unlink()
                app.refresh_colours()
                self.assertEqual(seen, ['111111', '222222', '111111'])

    def test_falls_back_to_helios_scheme(self):
        import json
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helios = root / 'helios.json'
            helios.write_text(json.dumps({'colours': {'primary': '123456'}}))
            with patch.object(GUI, 'SCHEME_PATH', root / 'missing.json'), \
                 patch.object(GUI, 'HEILIOS_SCHEME_PATH', helios):
                self.assertEqual(GUI.palette()['primary'], '123456')

    def test_validated_snapshot_survives_file_truncation(self):
        import json
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            committed, preview, helios = (root / name for name in ("scheme", "preview", "helios"))
            original = json.dumps({"colours": {"primary": "123456"}})
            committed.write_text(original)
            with patch.object(GUI, "SCHEME_PATH", committed), \
                 patch.object(GUI, "PREVIEW_SCHEME_PATH", preview), \
                 patch.object(GUI, "HEILIOS_SCHEME_PATH", helios):
                app = GUI.PacmangrGUI()
                seen = []
                def apply(*, scheme_colours):
                    committed.write_text("")
                    seen.append(GUI.palette(scheme_colours=scheme_colours)["primary"])
                app.apply_colours = apply
                app.refresh_colours()
                committed.write_text(original)
                app.refresh_colours()
                self.assertEqual(seen, ["123456"])

    def test_removing_last_scheme_restores_defaults(self):
        import json
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            committed, preview, helios = (root / name for name in ("scheme", "preview", "helios"))
            with patch.object(GUI, "SCHEME_PATH", committed), \
                 patch.object(GUI, "PREVIEW_SCHEME_PATH", preview), \
                 patch.object(GUI, "HEILIOS_SCHEME_PATH", helios), \
                 patch.object(GUI.SETTINGS, "get", return_value="auto"):
                app = GUI.PacmangrGUI()
                seen = []
                app.apply_colours = lambda *, scheme_colours: seen.append(GUI.palette(scheme_colours=scheme_colours)["primary"])
                for path in (preview, committed):
                    path.write_text(json.dumps({"colours": {"primary": "123456"}}))
                    app.refresh_colours()
                    path.unlink()
                    app.refresh_colours()
                self.assertEqual(seen, ["123456", "adc9ea", "123456", "adc9ea"])

    def test_failed_application_does_not_cache_snapshot(self):
        import json
        from unittest.mock import Mock, patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            committed = root / "scheme"
            committed.write_text(json.dumps({"colours": {"primary": "123456"}}))
            with patch.object(GUI, "SCHEME_PATH", committed), \
                 patch.object(GUI, "PREVIEW_SCHEME_PATH", root / "preview"), \
                 patch.object(GUI, "HEILIOS_SCHEME_PATH", root / "helios"):
                app = GUI.PacmangrGUI()
                app.apply_colours = Mock(side_effect=[RuntimeError("failed"), None])
                with self.assertRaises(RuntimeError):
                    app.refresh_colours()
                app.refresh_colours()
                self.assertEqual(app.apply_colours.call_count, 2)


if __name__ == "__main__":
    unittest.main()
