"""Offline checks: routing, settings persistence, and environment separation."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unz"))
import api_config
import check_fdh
import get_token
import history
import import_fdh
import send_gui


class APIConfigTest(unittest.TestCase):
    def test_default_uat_and_production_routing(self):
        self.assertEqual(api_config.load({}).environment, "UAT")
        for environment, host in (("UAT", api_config.UAT_URL), ("PRODUCTION", api_config.PRODUCTION_URL)):
            config = api_config.APIConfig(environment=environment)
            response = MagicMock()
            response.status = 200
            response.read.return_value = b'{"message":"success"}'
            response.__enter__.return_value = response
            with patch.object(import_fdh.urllib.request, "urlopen", return_value=response) as request:
                self.assertEqual(import_fdh.send({}, "TEST-TOKEN", config=config)[0], 200)
                self.assertEqual(request.call_args.args[0].full_url,
                                 host + "/fdh_api/v1/dataset/import")
            with patch.object(check_fdh, "post", return_value=(200, "[]")) as post:
                self.assertEqual(check_fdh.sent_seqs("TEST-TOKEN", config=config), set())
                self.assertEqual(post.call_args.args[0], host + "/fdh_api/v1/dataset/get_data")

    def test_token_url_matches_config_snapshot(self):
        config = api_config.APIConfig(token_url="https://token.example.test/token?Action=test")
        with patch.object(get_token, "get_token", return_value={"access_token": "TEST"}) as token:
            import_fdh.get_access_token(env={"FDH_PASSWORD_HASH": "TEST"}, config=config)
            self.assertEqual(token.call_args.kwargs["token_url"], config.token_url)
        response = MagicMock()
        response.read.return_value = b'TEST-TOKEN'
        response.__enter__.return_value = response
        with patch.object(get_token.urllib.request, "urlopen", return_value=response) as request:
            get_token.get_token({"FDH_USER": "TEST", "FDH_HOSPITAL_CODE": "TEST"},
                                "TEST", token_url=config.token_url)
            self.assertEqual(request.call_args.args[0].full_url, config.token_url)

    def test_custom_dataset_base_path(self):
        config = api_config.APIConfig(environment="PRODUCTION",
                                      production_url="https://api.example.test/api/v3/dataset/")
        self.assertEqual(config.dataset_url("import"), "https://api.example.test/api/v3/dataset/import")

    def test_save_preserves_credentials_and_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('# keep comment\nFDH_PASSWORD="TEST-ONLY"\nHOSXP_HOST=test\nFDH_ENV=UAT\n', encoding="utf-8")
            config = api_config.APIConfig(environment="PRODUCTION")
            api_config.save(config, path)
            self.assertIn('FDH_PASSWORD="TEST-ONLY"', path.read_text(encoding="utf-8"))
            self.assertIn("# keep comment", path.read_text(encoding="utf-8"))
            self.assertEqual(api_config.load(get_token.load_env(str(path))), config)
            api_config.save(config, path)
            self.assertEqual(path.read_text(encoding="utf-8").count("FDH_ENV="), 1)

    def test_invalid_settings_are_rejected(self):
        for url in ("http://host.test", "https://user:password@host.test", "https://host.test\nFDH_ENV=PRODUCTION"):
            with self.assertRaises(ValueError):
                api_config.APIConfig(uat_url=url)
        with self.assertRaises(ValueError):
            api_config.APIConfig(environment="WRONG")

    def test_history_separates_environments_and_legacy_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            entries = [dict(vn="OLD", status="submitted"),
                       dict(vn="UAT", status="submitted", environment="UAT"),
                       dict(vn="PROD", status="submitted", environment="PRODUCTION")]
            path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
            with patch.object(history, "LOG", str(path)):
                self.assertEqual(history.sent_vns("UAT"), {"OLD", "UAT"})
                self.assertEqual(history.sent_vns("PRODUCTION"), {"PROD"})


class APISettingsUITest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        with patch.object(api_config, "load", return_value=api_config.APIConfig()):
            self.app = send_gui.App(self.root)

    def tearDown(self):
        self.root.destroy()

    def test_save_updates_badge_and_uses_selected_history(self):
        self.app.rowstatus = {0: ("✓ ส่งแล้ว", "ok")}
        values = [tk.StringVar(master=self.root, value=value) for value in
                  ("PRODUCTION", api_config.UAT_URL, api_config.PRODUCTION_URL, get_token.TOKEN_URL)]
        window = tk.Toplevel(self.root)
        with patch.object(api_config, "save") as save, \
             patch.object(history, "sent_vns", return_value=set()) as sent:
            self.app._save_api_settings(window, *values)
            self.assertEqual(save.call_args.args[0].environment, "PRODUCTION")
            sent.assert_called_once_with("PRODUCTION")
            self.assertEqual(self.app.api_config.environment, "PRODUCTION")
            self.assertIn("PRODUCTION", self.app.lbl_environment.cget("text"))
            self.assertEqual(self.app.rowstatus, {})

    def test_busy_work_prevents_environment_switch(self):
        self.app.sending = True
        values = [tk.StringVar(master=self.root, value=value) for value in
                  ("PRODUCTION", api_config.UAT_URL, api_config.PRODUCTION_URL, get_token.TOKEN_URL)]
        window = tk.Toplevel(self.root)
        with patch.object(api_config, "save") as save, patch.object(send_gui.messagebox, "showinfo"):
            self.app._save_api_settings(window, *values)
            save.assert_not_called()
            self.assertEqual(self.app.api_config.environment, "UAT")


if __name__ == "__main__":
    unittest.main()
