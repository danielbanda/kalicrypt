import os
import tempfile
import unittest
from unittest import mock

import provision.cli as cli


class PassphrasePathTests(unittest.TestCase):
    def test_normalize_passphrase_expands_home(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/admin"}):
            path = cli._normalize_passphrase_path("~/secret.txt")
        self.assertEqual(path, os.path.abspath("/home/admin/secret.txt"))

    def test_require_passphrase_accepts_tilde(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            secret = os.path.join(tmpdir, "secret.txt")
            with open(secret, "w", encoding="utf-8") as handle:
                handle.write("key")
            with mock.patch.dict(os.environ, {"HOME": tmpdir}):
                resolved = cli._require_passphrase("~/secret.txt")
        self.assertEqual(resolved, os.path.abspath(secret))

    def test_plan_uses_normalized_passphrase(self):
        captured = {}

        def fake_plan_payload(plan, flags, root_src):
            captured["plan"] = plan
            return {"plan": "ok"}

        def fake_emit_result(*args, **kwargs):
            raise RuntimeError("emit")

        with mock.patch.dict(os.environ, {"HOME": "/home/admin"}), \
                mock.patch("provision.cli._plan_payload", side_effect=fake_plan_payload), \
                mock.patch("provision.cli._write_json_artifact", return_value="/tmp/plan.json"), \
                mock.patch("provision.cli._emit_result", side_effect=fake_emit_result), \
                mock.patch("provision.cli.safety.guard_not_live_disk", return_value=(True, "")), \
                mock.patch("provision.cli._same_underlying_disk", return_value=False), \
                mock.patch("provision.cli.os.path.exists", return_value=True), \
                mock.patch("provision.cli.os.popen") as popen_mock:
            popen_mock.return_value.read.return_value = "/dev/sda2"
            with self.assertRaisesRegex(RuntimeError, "emit"):
                cli.main([
                    "/dev/nvme0n1",
                    "--plan",
                    "--passphrase-file",
                    "~/secret.txt",
                ])

        self.assertIn("plan", captured)
        expected = os.path.abspath("/home/admin/secret.txt")
        self.assertEqual(captured["plan"].passphrase_file, expected)


if __name__ == "__main__":
    unittest.main()
