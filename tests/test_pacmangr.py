import importlib.machinery
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock


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


class OutputTests(unittest.TestCase):
    def test_usage_lists_headless_commands(self):
        help_text = MODULE.usage()

        self.assertIn("find <query>", help_text)
        self.assertIn("installed [filter]", help_text)
        self.assertIn("cache status|clear", help_text)


if __name__ == "__main__":
    unittest.main()
