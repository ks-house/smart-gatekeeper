import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from scripts import read_diagnostics as client


class DiagnosticsClientTest(unittest.TestCase):
    def test_creation_is_private_never_overwrites_and_never_prints_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(0, client.main(["--init-token", "--token-file", str(path)]))
            token = path.read_text().strip()
            self.assertNotIn(token, output.getvalue())
            self.assertEqual(hashlib.sha256(token.encode()).hexdigest(),
                             json.loads(output.getvalue())["server_environment"]["DIAGNOSTICS_READ_TOKEN_SHA256"])
            if os.name != "nt":
                self.assertEqual(0o600, path.stat().st_mode & 0o777)
            with self.assertRaises(FileExistsError):
                client.initialize(path)
            self.assertEqual(token, path.read_text().strip())

    def test_environment_file_exclusivity_and_format(self):
        with patch.dict(os.environ, {client.TOKEN_ENV: "x" * 43}, clear=True):
            self.assertEqual("x" * 43, client.load_token())
        with patch.dict(os.environ, {client.TOKEN_ENV: "x" * 43,
                                    client.TOKEN_ENV + "_FILE": "ignored"}, clear=True):
            with self.assertRaises(ValueError):
                client.load_token()
        with patch.dict(os.environ, {client.TOKEN_ENV: "line\nbreak"}, clear=True):
            with self.assertRaises(ValueError):
                client.load_token()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            client.initialize(path)
            with patch.dict(os.environ, {client.TOKEN_ENV + "_FILE": str(path)}, clear=True):
                self.assertEqual(path.read_text().strip(), client.load_token())

    def test_origin_and_redirect_guard(self):
        self.assertEqual("https://example.test/api/v1/diagnostics/bundles/3",
                         client.endpoint("https://example.test/", 3, 20, None))
        for origin in ("http://example.test", "https://user:secret@example.test",
                       "https://example.test/?token=secret", "https://example.test/other"):
            with self.assertRaises(ValueError):
                client.endpoint(origin, None, 20, None)
        self.assertIsNone(client.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.test"))

    def test_check_token_does_not_fetch_or_print_credential(self):
        token = "x" * 43
        output = io.StringIO()
        with patch.dict(os.environ, {client.TOKEN_ENV: token}, clear=True), patch.object(client, "fetch") as fetch:
            with contextlib.redirect_stdout(output):
                self.assertEqual(0, client.main(["--check-token"]))
            fetch.assert_not_called()
        self.assertNotIn(token, output.getvalue())
        self.assertTrue(json.loads(output.getvalue())["token_available"])

    def test_access_events_use_same_token_and_encode_filters(self):
        token = "x" * 43
        output = io.StringIO()
        with patch.object(client, "load_token", return_value=token), \
                patch.object(client, "fetch", return_value={"events": [], "next_before_id": None}) as fetch:
            with contextlib.redirect_stdout(output):
                self.assertEqual(0, client.main([
                    "--access-events", "--since", "2026-09-07T00:00:00+09:00",
                    "--until", "2026-09-08T00:00:00+09:00", "--target-id", "gatekeeper",
                    "--session-id", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
                    "--boot-count", "768", "--event-code", "ACCESS_ARMED",
                    "--before-id", "9007199254740995", "--limit", "100",
                ]))
            url, credential = fetch.call_args.args
            self.assertEqual(token, credential)
            self.assertEqual("/api/v1/diagnostics/access-events", urlsplit(url).path)
            self.assertIn("%2B09%3A00", url)
            self.assertEqual({
                "since": ["2026-09-07T00:00:00+09:00"], "until": ["2026-09-08T00:00:00+09:00"],
                "limit": ["100"], "target_id": ["gatekeeper"], "boot_count": ["768"],
                "event_code": ["ACCESS_ARMED"], "before_id": ["9007199254740995"],
                "session_id": ["aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"],
            }, parse_qs(urlsplit(url).query))
        self.assertNotIn(token, output.getvalue())
        self.assertEqual([], json.loads(output.getvalue())["events"])

    def test_event_endpoint_keeps_origin_guard(self):
        for base in ("http://example.test", "https://user:secret@example.test", "https://example.test/path"):
            with self.assertRaises(ValueError):
                client.access_events_endpoint(base, 20, None)

    def test_incompatible_modes_fail_before_credentials_or_network(self):
        for args in (["--access-events", "--bundle-id", "1"],
                     ["--access-events", "--init-token"],
                     ["--access-events", "--check-token"],
                     ["--event-code", "ACCESS_ARMED"],
                     ["--init-token", "--since", "2026-09-07T00:00:00Z"],
                     ["--bundle-id", "1", "--before-id", "2"],
                     ["--access-events", "--boot-count", "0"]):
            with self.subTest(args=args), patch.object(client, "load_token") as load, \
                    patch.object(client, "fetch") as fetch, patch.object(client, "initialize") as init, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                client.main(args)
            self.assertEqual(2, error.exception.code)
            load.assert_not_called()
            fetch.assert_not_called()
            init.assert_not_called()

    def test_default_bundle_mode_is_unchanged(self):
        with patch.object(client, "load_token", return_value="x" * 43), \
                patch.object(client, "fetch", return_value={}) as fetch, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, client.main(["--before-id", "123"]))
        self.assertTrue(fetch.call_args.args[0].endswith("/bundles?limit=20&before_id=123"))
