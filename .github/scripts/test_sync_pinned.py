import copy
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import sync_pinned


class SyncPinnedTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "README.md"
        self.prefix = "# 资料\n\n保留前文。\n\n## 精选项目\n"
        self.suffix = "## 连接\n\n保留后文。\n"
        self.path.write_text(
            self.prefix + sync_pinned.render_section(["owner/old"]) + self.suffix,
            encoding="utf-8", newline="\n",
        )

    def payload(self, names=()):
        return {"data": {"user": {"pinnedItems": {
            "nodes": [{"nameWithOwner": name, "isPrivate": False} for name in names],
            "totalCount": len(names),
            "pageInfo": {"hasNextPage": False},
        }}}}

    def fetch(self, payload):
        with patch.object(sync_pinned, "urlopen", return_value=BytesIO(json.dumps(payload).encode())):
            return sync_pinned.fetch_pinned("owner", "test-token")

    def test_unchanged_does_not_write(self):
        with patch.object(Path, "write_bytes") as write:
            self.assertFalse(sync_pinned.sync_readme(self.path, ["owner/old"]))
            write.assert_not_called()

    def test_add_remove_reorder_preserves_other_sections(self):
        repositories = ["another-owner/new", "owner/second"]
        self.assertTrue(sync_pinned.sync_readme(self.path, repositories))
        result = self.path.read_text(encoding="utf-8")
        self.assertEqual(result, self.prefix + sync_pinned.render_section(repositories) + self.suffix)
        self.assertNotIn("owner/old", result)
        self.assertIn("username=another-owner&repo=new&theme=tokyonight", result)
        self.assertTrue(sync_pinned.sync_readme(self.path, list(reversed(repositories))))
        self.assertFalse(sync_pinned.sync_readme(self.path, list(reversed(repositories))))

    def test_empty_pins_clear_only_cards(self):
        self.assertEqual(self.fetch(self.payload()), [])
        self.assertTrue(sync_pinned.sync_readme(self.path, []))
        result = self.path.read_text(encoding="utf-8")
        self.assertEqual(result, self.prefix + sync_pinned.render_section([]) + self.suffix)
        self.assertNotIn("<a href=", result)
        self.assertFalse(sync_pinned.sync_readme(self.path, []))

    def test_missing_or_duplicate_heading_rejected_without_writing(self):
        for text in ["# 没有精选项目\n", self.prefix + "\n" + self.prefix]:
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8", newline="\n")
                before = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    sync_pinned.sync_readme(self.path, [])
                self.assertEqual(self.path.read_bytes(), before)

    def test_last_section_supported(self):
        self.path.write_text(self.prefix + "旧卡片\n", encoding="utf-8", newline="\n")
        self.assertTrue(sync_pinned.sync_readme(self.path, ["owner/new"]))
        self.assertEqual(
            self.path.read_text(encoding="utf-8"),
            self.prefix + sync_pinned.render_section(["owner/new"]),
        )

    def test_api_order_and_private_filter(self):
        payload = self.payload(["owner/z", "owner/private", "other/a"])
        payload["data"]["user"]["pinnedItems"]["nodes"][1]["isPrivate"] = True
        self.assertEqual(self.fetch(payload), ["owner/z", "other/a"])

    def test_request_uses_variables_and_timeout(self):
        with patch.object(sync_pinned, "urlopen", return_value=BytesIO(json.dumps(self.payload()).encode())) as request:
            sync_pinned.fetch_pinned("owner", "test-token")
        args, kwargs = request.call_args
        self.assertEqual(json.loads(args[0].data)["variables"], {"login": "owner"})
        self.assertEqual(args[0].get_method(), "POST")
        self.assertEqual(kwargs["timeout"], 30)

    def test_invalid_or_partial_api_response_rejected(self):
        valid = self.payload(["owner/repo"])
        responses = [None, {}, {"data": {"user": None}}, {**valid, "errors": [{"message": "denied"}]}]
        for key, value in [
            ("nodes", [None]),
            ("nodes", [{"nameWithOwner": 'owner/bad"name', "isPrivate": False}]),
            ("nodes", [{"nameWithOwner": "owner/repo", "isPrivate": None}]),
            ("nodes", None),
            ("totalCount", 2),
            ("pageInfo", {"hasNextPage": True}),
        ]:
            payload = copy.deepcopy(valid)
            payload["data"]["user"]["pinnedItems"][key] = value
            responses.append(payload)
        responses.append(self.payload(["owner/repo", "OWNER/REPO"]))
        for payload in responses:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.fetch(payload)

    def test_http_network_timeout_and_invalid_json_errors(self):
        for error in [HTTPError("https://api.github.com/graphql", 403, "denied", {}, None), URLError("offline"), TimeoutError()]:
            with self.subTest(error=error), patch.object(sync_pinned, "urlopen", side_effect=error):
                with self.assertRaises(ValueError):
                    sync_pinned.fetch_pinned("owner", "test-token")
        with patch.object(sync_pinned, "urlopen", return_value=BytesIO(b"not json")):
            with self.assertRaises(ValueError):
                sync_pinned.fetch_pinned("owner", "test-token")

    def test_main_api_failure_never_reaches_write(self):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY_OWNER": "owner", "GITHUB_TOKEN": "test-token"}), \
                patch.object(sync_pinned, "fetch_pinned", side_effect=ValueError("API failed")), \
                patch.object(sync_pinned, "sync_readme") as sync, patch("sys.stderr", new_callable=StringIO):
            self.assertEqual(sync_pinned.main(), 1)
            sync.assert_not_called()

    def test_missing_credentials_fail(self):
        with patch.dict(os.environ, {}, clear=True), patch("sys.stderr", new_callable=StringIO):
            self.assertEqual(sync_pinned.main(), 1)


if __name__ == "__main__":
    unittest.main()
