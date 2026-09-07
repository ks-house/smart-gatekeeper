import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
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
