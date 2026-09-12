"""Reproducible local overhead probe; owns and cleans all temporary resources."""
import json
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_pow


def main():
    with tempfile.TemporaryDirectory(prefix="aipow-bench-") as tmp:
        root = Path(tmp)
        ai_pow.git(root, "init", "-q")
        for i in range(1000):
            (root / f"file{i}.txt").write_bytes(b"x" * 1024)
        rec = ai_pow.Recorder(root)
        rec.init()
        start = time.perf_counter()
        sample = rec.sample()
        scan_ms = (time.perf_counter() - start) * 1000
        tracemalloc.start()
        latencies = []
        for i in range(1000):
            start = time.perf_counter()
            rec.record("tool.call", {"name": "shell", "call_id": str(i)})
            latencies.append((time.perf_counter() - start) * 1000)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(json.dumps({"events": 1000, "files": 1000, "sample_ms": round(scan_ms, 2),
                          "unchanged_sample_bytes_read": sample["bytes_read"],
                          "record_p50_ms": round(statistics.median(latencies), 2),
                          "record_p95_ms": round(sorted(latencies)[949], 2),
                          "python_current_kib": round(current / 1024, 2),
                          "python_peak_kib": round(peak / 1024, 2),
                          "database_bytes": rec.database.stat().st_size,
                          "threads_after": threading.active_count()}, indent=2))


if __name__ == "__main__":
    main()
