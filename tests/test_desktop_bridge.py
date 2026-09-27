from __future__ import annotations

import json
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import webview.util

from backend.api import API
from backend.desktop_bridge import DesktopBridge


class DesktopBridgeTests(unittest.TestCase):
    def test_pywebview_only_registers_whitelisted_rpc_entrypoint(self):
        with tempfile.TemporaryDirectory() as directory:
            api = API(directory)
            self.addCleanup(api.close)
            bridge = DesktopBridge(api)
            scripts = []
            window = SimpleNamespace(
                uid="audit", _js_api=bridge, _functions={}, _expose_lock=threading.Lock(),
                events=SimpleNamespace(before_load=Mock(), _pywebviewready=Mock(), loaded=Mock()),
                run_js=scripts.append,
            )

            class InlineThread:
                def __init__(self, target):
                    self.target = target

                def start(self):
                    self.target()

            with patch.object(webview.util, "load_js_files", return_value=("", "%(functions)s")), \
                    patch.object(webview.util, "Thread", InlineThread):
                webview.util.inject_pywebview("edgechromium", window)
            self.assertEqual([item["func"] for item in json.loads(scripts[-1])], ["call"])
            self.assertEqual(bridge.call("settings_service.get")["error"]["code"], "METHOD_NOT_ALLOWED")
            self.assertTrue(bridge.call("get_bootstrap")["ok"])
