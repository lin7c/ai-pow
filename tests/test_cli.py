import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import ai_pow


class CliTests(unittest.TestCase):
    def test_standalone_and_laintas_round_trip(self):
        with tempfile.TemporaryDirectory(prefix="aipow-cli-test-") as tmp:
            root = Path(tmp)
            ai_pow.git(root, "init", "-q")
            ai_pow.git(root, "config", "user.name", "Test")
            ai_pow.git(root, "config", "user.email", "test@example.invalid")
            env = dict(os.environ, LAINTAS_HOME=str(root / "private-home"),
                       PYTHONDONTWRITEBYTECODE="1")
            independent = [sys.executable, str(Path(ai_pow.__file__).resolve())]
            def command(prefix, *args, stdin=None, code=0):
                result = subprocess.run([*prefix, "--cwd", str(root), *args],
                                        input=stdin, text=True, capture_output=True,
                                        env=env, cwd=root, timeout=30)
                self.assertEqual(result.returncode, code, result.stderr)
                return json.loads(result.stdout) if code == 0 else result
            command(independent, "init")
            command(independent, "emit", "human.message", stdin=json.dumps(ai_pow.text_meta("build feature")))
            (root / "app.py").write_text("print('hello')\n")
            command(independent, "sample")
            ai_pow.git(root, "add", "app.py")
            ai_pow.git(root, "commit", "-qm", "feature")
            proof = command(independent, "report")
            self.assertTrue(command(independent, "verify")["integrity_verified"])
            bundle = root / "bundle.jsonl"
            command(independent, "export", str(bundle))
            self.assertTrue(command(independent, "verify", "--bundle", str(bundle))["integrity_verified"])
            # A different installed frontend must read the exact same proof/store.
            laintas = Path(__file__).resolve().parents[2] / "laintas_cli"
            python = laintas / "venv/bin/python"
            if python.is_file():
                native = [str(python), str(laintas / "laintas_cli.py"), "pow"]
                result = command(native, "report")
                self.assertEqual(result["proof_hash"], proof["proof_hash"])
                self.assertTrue(command(native, "verify")["integrity_verified"])

    def test_multi_process_writers(self):
        with tempfile.TemporaryDirectory(prefix="aipow-multiprocess-") as tmp:
            root = Path(tmp)
            ai_pow.git(root, "init", "-q")
            rec = ai_pow.Recorder(root)
            rec.init()
            script = "import ai_pow,sys; r=ai_pow.Recorder(sys.argv[1]); [r.record('tool.call', {'name':'shell'}) for _ in range(10)]"
            env = dict(os.environ, PYTHONPATH=str(Path(ai_pow.__file__).parent), PYTHONDONTWRITEBYTECODE="1")
            children = []
            try:
                for _ in range(4):
                    children.append(subprocess.Popen([sys.executable, "-c", script, str(root)], env=env,
                                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                for child in children:
                    _, err = child.communicate(timeout=20)
                    self.assertEqual(child.returncode, 0, err.decode())
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.communicate()
            self.assertEqual(rec.status()["active"]["event_counts"]["tool.call"], 40)
