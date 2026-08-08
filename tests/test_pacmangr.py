import importlib.machinery
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "pacmangr"
LOADER = importlib.machinery.SourceFileLoader("pacmangr_module", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = MODULE
LOADER.exec_module(MODULE)


class SearchKeyTests(unittest.TestCase):
    def make_ui(self, mode="search"):
        ui = MODULE.PkgUI.__new__(MODULE.PkgUI)
        ui.version_shelf_open = False
        ui.running = True
        ui.mode = mode
        ui.selected = 4
        ui.scroll = 2
        ui.search = Mock()
        ui.filter_installed = Mock()
        return ui

    def test_s_opens_search_prompt_immediately(self):
        ui = self.make_ui(mode="installed")

        ui.handle_key(ord("s"))

        self.assertEqual(ui.mode, "search")
        self.assertEqual(ui.selected, 0)
        self.assertEqual(ui.scroll, 0)
        ui.search.assert_called_once_with()

    def test_slash_searches_in_search_view(self):
        ui = self.make_ui()

        ui.handle_key(ord("/"))

        ui.search.assert_called_once_with()
        ui.filter_installed.assert_not_called()

    def test_slash_filters_in_installed_view(self):
        ui = self.make_ui(mode="installed")

        ui.handle_key(ord("/"))

        ui.filter_installed.assert_called_once_with()
        ui.search.assert_not_called()


class NixBackendTests(unittest.TestCase):
    def tools(self, managers):
        return MODULE.Tools(
            pacman=None,
            yay=None,
            paru=None,
            flatpak=None,
            pacseek=None,
            downgrade=None,
            apt=None,
            apt_cache=None,
            dpkg_query=None,
            snap=None,
            sudo=None,
            doas=None,
            extra_managers=managers,
        )

    def test_detection_prefers_modern_nix_over_incompatible_nix_env(self):
        def which(command):
            if command in {"nix", "nix-env"}:
                return f"/usr/bin/{command}"
            return None

        with patch.object(MODULE.shutil, "which", side_effect=which):
            managers = MODULE.detect_extra_managers()

        self.assertEqual(managers, {"nix": "/usr/bin/nix"})

    def test_detection_falls_back_to_legacy_nix_env(self):
        def which(command):
            return "/usr/bin/nix-env" if command == "nix-env" else None

        with patch.object(MODULE.shutil, "which", side_effect=which):
            managers = MODULE.detect_extra_managers()

        self.assertEqual(managers, {"nix-env": "/usr/bin/nix-env"})

    def test_modern_commands_use_profile_and_flake_interfaces(self):
        tools = self.tools({"nix": "/usr/bin/nix"})
        search_item = MODULE.PackageItem(
            "nix", "nix", "hello", "hello", origin="nixpkgs#hello"
        )
        installed_item = MODULE.PackageItem(
            "nix",
            "nix",
            "hello",
            "hello",
            installed=True,
            origin="flake:nixpkgs#legacyPackages.x86_64-linux.hello",
        )
        with patch.object(MODULE.shutil, "which", return_value="/usr/bin/nix"):
            search = MODULE.manager_spec_command(
                "nix", "search", tools, query="c++"
            )
            install = search_item.install_command(tools)
            reinstall = installed_item.install_command(tools)
            remove = installed_item.remove_command(tools)
            update = MODULE.manager_spec_command("nix", "update", tools)

        self.assertEqual(search[-2:], [r"c\+\+", "--json"])
        self.assertEqual(install[-3:], ["profile", "install", "nixpkgs#hello"])
        self.assertEqual(
            reinstall[-1],
            "flake:nixpkgs#legacyPackages.x86_64-linux.hello",
        )
        self.assertEqual(remove[-3:], ["profile", "remove", "hello"])
        self.assertEqual(update[-3:], ["profile", "upgrade", ".*"])

    def test_nix_search_json_keeps_installable_attribute(self):
        output = """warning: using experimental feature\n{
          "legacyPackages.x86_64-linux.hello": {
            "description": "A friendly greeting program",
            "pname": "hello",
            "version": "2.12.2"
          },
          "packages.x86_64-linux.ripgrep": {
            "description": "Fast recursive search",
            "pname": "ripgrep",
            "version": "14.1.1"
          }
        }"""

        items = MODULE.parse_nix_search(output, {"hello"})

        self.assertEqual([item.package_id for item in items], ["hello", "ripgrep"])
        self.assertEqual(items[0].origin, "nixpkgs#hello")
        self.assertEqual(items[0].version, "2.12.2")
        self.assertTrue(items[0].installed)

    def test_current_nix_profile_json_uses_element_name_for_remove(self):
        output = """{
          "version": 3,
          "elements": {
            "hello": {
              "active": true,
              "attrPath": "legacyPackages.x86_64-linux.hello",
              "originalUrl": "flake:nixpkgs",
              "storePaths": [
                "/nix/store/0123456789abcdfghijklmnpqrsvwxyz-hello-2.12.2"
              ]
            }
          }
        }"""

        items = MODULE.parse_nix_profile_installed(output)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "hello")
        self.assertEqual(items[0].package_id, "hello")
        self.assertEqual(items[0].version, "2.12.2")
        self.assertEqual(
            items[0].origin,
            "flake:nixpkgs#legacyPackages.x86_64-linux.hello",
        )

    def test_old_nix_profile_json_uses_numeric_remove_selector(self):
        output = """{
          "version": 2,
          "elements": [{
            "active": true,
            "attrPath": "legacyPackages.x86_64-linux.ripgrep",
            "originalUrl": "flake:nixpkgs",
            "storePaths": [
              "/nix/store/0123456789abcdfghijklmnpqrsvwxyz-ripgrep-14.1.1"
            ]
          }]
        }"""

        items = MODULE.parse_nix_profile_installed(output)

        self.assertEqual(items[0].name, "ripgrep")
        self.assertEqual(items[0].package_id, "0")
        self.assertEqual(items[0].version, "14.1.1")

    def test_legacy_nix_env_parsers_preserve_attribute_and_version(self):
        searched = MODULE.parse_nix_env_search(
            "nixpkgs.hello hello-2.12.2 A friendly greeting program\n",
            {"hello"},
        )
        installed = MODULE.parse_nix_env_installed("hello-2.12.2\n")

        self.assertEqual(searched[0].package_id, "nixpkgs.hello")
        self.assertEqual(searched[0].version, "2.12.2")
        self.assertTrue(searched[0].installed)
        self.assertEqual(installed[0].package_id, "hello")
        self.assertEqual(installed[0].version, "2.12.2")


class OutputTests(unittest.TestCase):
    def test_usage_lists_headless_commands(self):
        help_text = MODULE.usage()

        self.assertIn("find <query>", help_text)
        self.assertIn("installed [filter]", help_text)
        self.assertIn("cache status|clear", help_text)


if __name__ == "__main__":
    unittest.main()
