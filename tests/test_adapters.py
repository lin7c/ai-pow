from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

import ai_pow as pow


class TranscriptTests(unittest.TestCase):
    def test_incremental_usage_dedup_and_historical_filter(self):
        with tempfile.TemporaryDirectory(prefix="aipow-adapter-") as tmp:
            root = Path(tmp)
            pow.git(root, "init", "-q")
            rec = pow.Recorder(root)
            rec.init()
            transcript = root / "transcript.jsonl"
            timestamp = datetime.now(timezone.utc).isoformat()
            row = {"type": "assistant", "sessionId": "s", "timestamp": timestamp,
                   "message": {"id": "msg_1", "model": "example", "content": "NEVER SAVE ME",
                               "usage": {"input_tokens": 100, "cache_read_input_tokens": 20,
                                         "cache_creation_input_tokens": 10, "output_tokens": 30}}}
            old = {**row, "timestamp": "2000-01-01T00:00:00Z"}
            transcript.write_text(json.dumps(old) + "\n" + json.dumps(row) + "\n")
            self.assertEqual(rec.import_claude_usage(transcript)["imported_calls"], 1)
            self.assertEqual(rec.import_claude_usage(transcript)["bytes_read"], 0)
            with transcript.open("a") as out:
                out.write(json.dumps(row) + "\n")
            self.assertEqual(rec.import_claude_usage(transcript)["imported_calls"], 0)
            m = rec.status()["active"]["models"]["example/provider_reported"]
            self.assertEqual(m["calls"], 1)
            self.assertEqual(m["input_tokens"], 120)
            self.assertEqual(m["cache_write_tokens"], 10)
            self.assertNotIn(b"NEVER SAVE ME", rec.database.read_bytes())

    def test_partial_line_and_start_baseline(self):
        with tempfile.TemporaryDirectory(prefix="aipow-adapter-") as tmp:
            root = Path(tmp)
            pow.git(root, "init", "-q")
            rec = pow.Recorder(root)
            rec.init()
            path = root / "trace"
            path.write_text("historic\n")
            rec.import_claude_usage(path, start_at_end=True)
            with path.open("a") as out:
                out.write('{"type":"user"')
            self.assertEqual(rec.import_claude_usage(path)["imported_calls"], 0)
            with path.open("a") as out:
                out.write('}\n')
            self.assertEqual(rec.import_claude_usage(path)["bytes_read"], 16)
