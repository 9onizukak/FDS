"""Offline checks for responsive search, duplicate protection, and recovery."""
import sys
from pathlib import Path
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unz"))
import send_gui


class SearchUITest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = send_gui.App(self.root)
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()
        self.root.destroy()

    def pump_until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(condition(), "UI did not complete within timeout")

    def delayed(self, result):
        def query(*args, **kwargs):
            if not self.release.wait(2):
                raise RuntimeError("Test timed out")
            return result
        return query

    def test_opd_responsive_and_duplicate_protected(self):
        row = dict(vn="TEST", hn="TEST", an=None, pname="", fname="ทดสอบ",
                   lname="ระบบ", tot=100, vstdate="2026-10-06", vsttime="09:00")
        with patch.object(send_gui.send_menu, "list_visits", side_effect=self.delayed([row])) as query, \
             patch.object(send_gui.history, "sent_vns", return_value=set()):
            self.app.search()
            self.assertTrue(self.app.searching)
            self.assertIn("กำลังค้นหา", self.app.lbl_count.cget("text"))
            self.assertEqual(str(self.app.btn_search.cget("state")), "disabled")
            self.assertEqual(str(self.app.btn_send.cget("state")), "disabled")
            tick = []
            self.root.after(10, lambda: tick.append(True))
            self.pump_until(lambda: bool(tick))
            self.assertTrue(self.app.searching)
            self.assertGreater(float(self.app.opd_search_progress.cget("value")), 0)
            self.app.search()
            self.app.ipd_search()
            self.release.set()
            self.pump_until(lambda: not self.app.searching)
            self.assertEqual(query.call_count, 1)
            self.assertEqual(len(self.app.tree.get_children()), 1)
            self.assertEqual(str(self.app.btn_search.cget("state")), "normal")
            self.assertFalse(self.app.opd_search_progress.winfo_manager())

    def test_error_preserves_results_and_allows_retry(self):
        self.app.rows = [{"vn": "EXISTING"}]
        with patch.object(send_gui.send_menu, "list_visits", side_effect=RuntimeError("Offline test")), \
             patch.object(send_gui.messagebox, "showerror") as error:
            self.app.search()
            self.pump_until(lambda: not self.app.searching)
            error.assert_called_once()
            self.assertEqual(self.app.rows, [{"vn": "EXISTING"}])
            self.assertEqual(str(self.app.btn_search.cget("state")), "normal")
        with patch.object(send_gui.send_menu, "list_visits", return_value=[]), \
             patch.object(send_gui.history, "sent_vns", return_value=set()):
            self.app.search()
            self.pump_until(lambda: not self.app.searching)
            self.assertIn("พบ 0", self.app.lbl_count.cget("text"))

    def test_ipd_loading_and_completion(self):
        with patch.object(send_gui.send_menu, "list_discharged", side_effect=self.delayed([])):
            self.app.ipd_search()
            self.assertIn("กำลังค้นหา", self.app.ipd_count.cget("text"))
            self.assertEqual(str(self.app.btn_ipd_search.cget("state")), "disabled")
            self.release.set()
            self.pump_until(lambda: not self.app.searching)
            self.assertIn("จำหน่าย 0", self.app.ipd_count.cget("text"))
            self.assertFalse(self.app.ipd_search_progress.winfo_manager())

    def test_ipd_error_restores_button(self):
        with patch.object(send_gui.send_menu, "list_discharged", side_effect=RuntimeError("Offline test")), \
             patch.object(send_gui.messagebox, "showerror") as error:
            self.app.ipd_search()
            self.pump_until(lambda: not self.app.searching)
            error.assert_called_once()
            self.assertEqual(str(self.app.btn_ipd_search.cget("state")), "normal")


if __name__ == "__main__":
    unittest.main()
