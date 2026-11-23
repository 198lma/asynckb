"""Checks for benchmark accounting, rather than machine-specific speed."""

import asyncio
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "run_kes_performance.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("kes_performance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PerformanceAccountingTests(unittest.TestCase):
    def test_reports_percentiles_and_rate_from_completed_operations(self):
        self.assertTrue(
            SCRIPT.exists(), "benchmark tool has not been implemented"
        )
        stats = load_tool().summarize([0.001, 0.002, 0.003, 0.004], 2.0)
        self.assertEqual(stats["completed"], 4)
        self.assertEqual(stats["operations_per_second"], 2.0)
        self.assertEqual(stats["latency_ms"]["p50"], 2.0)
        self.assertEqual(stats["latency_ms"]["p95"], 4.0)
        self.assertEqual(stats["latency_ms"]["p99"], 4.0)
        self.assertEqual(stats["latency_ms"]["max"], 4.0)

    def test_failed_operation_is_not_counted_as_success(self):
        self.assertTrue(
            SCRIPT.exists(), "benchmark tool has not been implemented"
        )
        tool = load_tool()

        async def broken(worker, sequence):
            raise ValueError("intentional failure")

        result = asyncio.run(tool.run_load(broken, workers=1, duration=0.02))
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["errors"], 1)
        self.assertIn("ValueError", result["first_error"])

    def test_runs_concurrently_and_records_each_success_once(self):
        self.assertTrue(
            SCRIPT.exists(), "benchmark tool has not been implemented"
        )
        tool = load_tool()
        observed = set()

        async def operation(worker, sequence):
            await asyncio.sleep(0.001)
            self.assertNotIn((worker, sequence), observed)
            observed.add((worker, sequence))

        result = asyncio.run(
            tool.run_load(operation, workers=3, duration=0.02)
        )
        self.assertGreater(result["completed"], 3)
        self.assertEqual(result["completed"], len(observed))
        self.assertEqual(result["errors"], 0)
        self.assertEqual({worker for worker, _ in observed}, {0, 1, 2})

    def test_cli_propagates_failed_benchmark_exit_status(self):
        # Isolate the CLI boundary without running database workloads.
        probe = """
import asyncio
import runpy
import sys

def failed_benchmark(coroutine):
    coroutine.close()
    return 1

asyncio.run = failed_benchmark
script = sys.argv[1]
sys.argv = [script, '--output', 'unused.json']
runpy.run_path(script, run_name='__main__')
"""
        result = subprocess.run(
            [sys.executable, "-c", probe, str(SCRIPT)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1, result.stderr)


if __name__ == "__main__":
    unittest.main()
