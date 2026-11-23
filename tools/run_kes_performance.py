"""Bounded, reproducible KES performance and short-duration stress checks.

Run from the repository root with ASYNCKB_KES_PASSWORD configured.
This deliberately stays separate from the functional case manifest.
"""

import argparse
from array import array
import asyncio
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import gc
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asynckb
from tests.kes.support.config import KESConfig


def summarize(latencies, elapsed):
    ordered = sorted(latencies)

    def percentile(fraction):
        if not ordered:
            return None
        index = max(0, math.ceil(len(ordered) * fraction) - 1)
        return round(ordered[index] * 1000, 4)

    return {
        "completed": len(ordered),
        "elapsed_seconds": round(elapsed, 4),
        "operations_per_second": round(len(ordered) / elapsed, 2),
        "latency_ms": {
            "p50": percentile(0.5), "p95": percentile(0.95),
            "p99": percentile(0.99), "max": percentile(1),
        },
    }


def resources():
    status = Path("/proc/self/status").read_text()
    rss_kib = int(next(line.split()[1] for line in status.splitlines()
                       if line.startswith("VmRSS:")))
    return {
        "rss_mib": round(rss_kib / 1024, 3),
        "file_descriptors": len(list(Path("/proc/self/fd").iterdir())),
        "asyncio_tasks": len(asyncio.all_tasks()),
    }


async def run_load(operation, *, workers, duration):
    latencies = array("d")
    errors = Counter()
    first_error = None
    stop = asyncio.Event()
    start = time.perf_counter()
    cpu_start = time.process_time()
    deadline = start + duration
    samples = []

    async def worker(number):
        nonlocal first_error
        sequence = 0
        while time.perf_counter() < deadline and not stop.is_set():
            before = time.perf_counter()
            try:
                await operation(number, sequence)
            except Exception as exc:
                errors[type(exc).__name__] += 1
                first_error = first_error or (
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                )
                stop.set()
                break
            latencies.append(time.perf_counter() - before)
            sequence += 1

    async def monitor():
        while not stop.is_set():
            sample = resources()
            sample["seconds"] = round(time.perf_counter() - start, 3)
            sample["completed"] = len(latencies)
            samples.append(sample)
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

    monitor_task = asyncio.create_task(monitor())
    try:
        await asyncio.gather(*(worker(number) for number in range(workers)))
    finally:
        stop.set()
        await monitor_task
    elapsed = time.perf_counter() - start
    cpu_seconds = time.process_time() - cpu_start
    result = summarize(latencies, elapsed)
    result.update({
        "workers": workers,
        "requested_seconds": duration,
        "errors": sum(errors.values()),
        "error_types": dict(errors),
        "first_error": first_error,
        "client_cpu_seconds": round(cpu_seconds, 4),
        "resource_samples": samples,
    })
    return result


async def close_pool(pool):
    try:
        await asyncio.wait_for(pool.close(), timeout=15)
    except BaseException:
        pool.terminate()
        raise


async def benchmark_mode(mode, options, application):
    config = KESConfig.from_env(mode)
    kwargs = config.connection_kwargs(
        command_timeout=10,
        server_settings={"application_name": application},
    )
    record = {"mode": mode, "phases": [], "checks": {}}
    query = "SELECT CAST($1 AS INTEGER)" + (
        " FROM dual" if mode == "oracle" else ""
    )
    observer = await asynckb.connect(**kwargs)
    table = "kb_perf_" + uuid.uuid4().hex[:12]
    created = False
    try:
        record["database_version"] = await observer.fetchval(
            "SELECT version()"
        )
        record["resources_before"] = resources()
        for cache in (0, 100):
            con = await asynckb.connect(
                **dict(kwargs, statement_cache_size=cache)
            )
            try:
                async def single(worker, sequence):
                    value = await con.fetchval(query, sequence)
                    if value != sequence:
                        raise AssertionError(
                            f"incorrect scalar result: {value!r}"
                        )

                for index in range(100):
                    await single(0, index)
                name = f"single_cache_{cache}"
                print(f"{mode}: starting {name}", flush=True)
                result = await run_load(
                    single, workers=1, duration=options.seconds
                )
                result["name"] = name
                result["unit"] = "queries/second"
                record["phases"].append(result)
            finally:
                await con.close()

        pool = await asynckb.create_pool(
            **kwargs, min_size=8, max_size=8, max_queries=100000000,
        )
        try:
            async def pooled(worker, sequence):
                async with pool.acquire(timeout=5) as con:
                    value = await con.fetchval(query, sequence)
                    if value != sequence:
                        raise AssertionError(
                            f"incorrect pooled result: {value!r}"
                        )

            for index in range(100):
                await pooled(0, index)
            for workers, seconds, name in (
                (1, options.seconds, "pool_workers_1"),
                (8, options.seconds, "pool_workers_8"),
                (32, options.seconds, "pool_workers_32"),
                (32, options.stress_seconds, "sustained_workers_32"),
            ):
                print(f"{mode}: starting {name} ({seconds}s)", flush=True)
                result = await run_load(
                    pooled, workers=workers, duration=seconds
                )
                result.update(name=name, unit="queries/second", pool_size=8)
                record["phases"].append(result)
                if result["errors"]:
                    raise RuntimeError(f"{name}: {result['first_error']}")

            held = []
            try:
                for _ in range(8):
                    held.append(await pool.acquire(timeout=5))
                try:
                    async with pool.acquire(timeout=0.05):
                        raise AssertionError(
                            "exhausted pool unexpectedly granted a connection"
                        )
                except asyncio.TimeoutError:
                    record["checks"]["pool_queue_timeout"] = True
            finally:
                for con in held:
                    await pool.release(con)
            await pooled(0, 42)
            record["checks"]["recovered_after_acquire_timeout"] = True

            await observer.execute(
                f"CREATE TABLE {table} (id INT PRIMARY KEY, "
                "label VARCHAR(256), amount DECIMAL(12,2))"
            )
            created = True
            expected_commits = 0
            payload = "x" * 256

            async def transaction(worker, sequence):
                nonlocal expected_commits
                key = sequence * 32 + worker
                async with pool.acquire(timeout=5) as con:
                    tx = con.transaction()
                    await tx.start()
                    try:
                        await con.execute(
                            f"INSERT INTO {table} (id, label, amount) "
                            "VALUES ($1, $2, $3)",
                            key, payload, Decimal("123.45"),
                        )
                        row = await con.fetchrow(
                            f"SELECT id, label, amount FROM {table} "
                            "WHERE id = $1", key,
                        )
                        if tuple(row) != (key, payload, Decimal("123.45")):
                            raise AssertionError(
                                f"incorrect transaction row: {row!r}"
                            )
                    except BaseException:
                        await tx.rollback()
                        raise
                    if sequence % 2:
                        await tx.rollback()
                    else:
                        await tx.commit()
                        expected_commits += 1

            print(
                f"{mode}: starting transaction_mix ({options.seconds}s)",
                flush=True,
            )
            result = await run_load(
                transaction, workers=32, duration=options.seconds
            )
            result.update(
                name="transaction_mix", unit="transactions/second", pool_size=8
            )
            record["phases"].append(result)
            actual_rows = await observer.fetchval(
                f"SELECT COUNT(*) FROM {table}"
            )
            record["checks"]["committed_rows"] = actual_rows
            record["checks"]["expected_committed_rows"] = expected_commits
            if actual_rows != expected_commits:
                raise AssertionError(
                    f"row count mismatch: {actual_rows} != {expected_commits}"
                )
            if pool.get_idle_size() != 8:
                raise AssertionError(
                    "pool did not recover all idle connections"
                )
            record["checks"]["all_pool_connections_returned"] = True
        finally:
            await close_pool(pool)

        remaining = await observer.fetchval(
            "SELECT COUNT(*) FROM pg_catalog.pg_stat_activity "
            "WHERE application_name = $1",
            application,
        )
        record["checks"][
            "sessions_after_pool_close_including_observer"
        ] = remaining
        if remaining != 1:
            raise AssertionError(
                f"unexpected remaining benchmark sessions: {remaining}"
            )
    finally:
        try:
            if created:
                await observer.execute(f"DROP TABLE {table}")
                record["checks"]["test_table_removed"] = True
        finally:
            await observer.close()
    gc.collect()
    await asyncio.sleep(0.1)
    record["resources_after"] = resources()
    record["passed"] = (
        all(phase["errors"] == 0 and phase["completed"] > 0
            for phase in record["phases"])
        and record["checks"].get("test_table_removed", False)
    )
    return record


async def main(options):
    application = "asynckb_perf_" + uuid.uuid4().hex[:12]
    output = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "driver_version": asynckb.__version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "application_name": application,
        "configuration": {
            "phase_seconds": options.seconds,
            "stress_seconds": options.stress_seconds,
            "pool_size": 8, "max_workers": 32, "ssl": False,
            "latency_includes_pool_acquire_and_release": True,
            "warmup_operations_per_query_path": 100,
            "percentile_method": "nearest-rank over all successful operations",
            "notes": ("Short closed-loop local test, not a 24-hour soak "
                      "or certified capacity benchmark."),
        },
        "modes": [],
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    for mode in ("mysql", "oracle", "sqlserver"):
        record = await benchmark_mode(mode, options, application)
        output["modes"].append(record)
        options.output.write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"{mode}: finished; passed={record['passed']}", flush=True)
    output["finished_utc"] = datetime.now(timezone.utc).isoformat()
    options.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(options.output, flush=True)
    return 0 if all(record["passed"] for record in output["modes"]) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--stress-seconds", type=float, default=120)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not (0 < args.seconds <= 60 and 0 < args.stress_seconds <= 600):
        parser.error(
            "phase duration must be in (0, 60], stress duration in (0, 600]"
        )
    raise SystemExit(asyncio.run(main(args)))
