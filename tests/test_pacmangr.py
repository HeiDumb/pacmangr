import importlib.machinery
import importlib.util
import queue
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


class SearchStateTests(unittest.TestCase):
    def make_ui(self):
        ui = MODULE.PkgUI.__new__(MODULE.PkgUI)
        ui.query = ""
        ui.mode = "search"
        ui.selected = 0
        ui.scroll = 0
        ui.search_results = []
        ui.pending_search_query = None
        ui.active_search_query = ""
        ui.busy = False
        ui.busy_label = ""
        ui.status = ""
        ui.log_lines = []
        ui.marked = {}
        ui.events = queue.Queue()
        ui.cache = Mock()
        ui.cache.load_search.return_value = []
        ui.enabled_search_managers = Mock(return_value={"pacman"})
        ui.refresh_marked_metadata = Mock()
        ui.spawn_job = Mock()
        return ui

    def test_search_queues_latest_query_while_another_job_is_busy(self):
        ui = self.make_ui()
        ui.busy = True
        ui.busy_label = "searching"
        ui.active_search_query = "old-query"
        ui.search_results = [Mock()]

        ui.start_search("new-query")

        self.assertEqual(ui.query, "new-query")
        self.assertEqual(ui.pending_search_query, "new-query")
        self.assertEqual(ui.search_results, [])
        ui.spawn_job.assert_not_called()
        self.assertIn("Queued search", ui.status)

    def test_stale_search_completion_starts_queued_search(self):
        ui = self.make_ui()
        stale_item = Mock()
        ui.busy = True
        ui.busy_label = "searching"
        ui.active_search_query = "old-query"
        ui.query = "new-query"
        ui.pending_search_query = "new-query"
        ui.events.put(("done", ("searching", [stale_item], None)))

        ui.poll_events()

        self.assertEqual(ui.search_results, [])
        self.assertIsNone(ui.pending_search_query)
        ui.spawn_job.assert_called_once()
        self.assertEqual(ui.active_search_query, "new-query")

    def test_current_search_completion_populates_results(self):
        ui = self.make_ui()
        item = Mock()
        ui.busy = True
        ui.busy_label = "searching"
        ui.active_search_query = "hyprland"
        ui.query = "hyprland"
        ui.events.put(("done", ("searching", [item], None)))

        ui.poll_events()

        self.assertEqual(ui.search_results, [item])
        ui.refresh_marked_metadata.assert_called_once_with([item])
        self.assertIn("Found 1 packages", ui.status)


class OutputTests(unittest.TestCase):
    def test_usage_lists_headless_commands(self):
        help_text = MODULE.usage()

        self.assertIn("find <query>", help_text)
        self.assertIn("installed [filter]", help_text)
        self.assertIn("cache status|clear", help_text)


if __name__ == "__main__":
    unittest.main()
