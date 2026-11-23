"""Regression checks for plan-to-code traceability (no database needed)."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
HELPERS = Path(__file__).with_name("trace_helpers")


def run_pytest(*args, fault=None):
    env = dict(os.environ, PYTHONPATH=str(HELPERS) + os.pathsep + str(ROOT))
    if fault:
        env["TRACE_FAULT"] = fault
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args], cwd=ROOT,
        env=env, capture_output=True, text=True,
    )


class TraceabilityChecks(unittest.TestCase):
    def test_every_collected_case_has_one_id_and_report_properties(self):
        result = run_pytest(
            "tests/kes", "--collect-only", "-q", "-p", "trace_probe",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = json.loads(next(
            line.split("=", 1)[1] for line in result.stdout.splitlines()
            if line.startswith("TRACE_RECORDS=")
        ))
        manifest_path = ROOT / "tests/kes/case_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            {r["case_id"][0] for r in records if len(r["case_id"]) == 1},
            {case["id"] for case in manifest},
        )
        for record in records:
            self.assertEqual(len(record["case_id"]), 1, record["nodeid"])
            self.assertEqual(
                record["properties"]["case_id"], record["case_id"][0],
            )

    def test_plan_id_selects_its_parameterized_cases(self):
        result = run_pytest(
            "tests/kes", "--collect-only", "-q", "-k", "KB-EXEC-049",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        nodes = [line for line in result.stdout.splitlines()
                 if line.startswith("tests/kes/")]
        self.assertEqual(len(nodes), 6)
        self.assertTrue(all("::test_zip_original_two_select_forms[" in node
                            for node in nodes))

    def test_junit_retains_ids_on_executed_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "identity.xml"
            result = run_pytest(
                "tests/kes/test_package_identity.py", "-q",
                "--junitxml=" + str(report),
            )
            self.assertEqual(
                result.returncode, 0, result.stdout + result.stderr,
            )
            cases = list(ET.parse(report).getroot().iter("testcase"))
        self.assertEqual(len(cases), 3)
        ids = set()
        for case in cases:
            props = {p.attrib["name"]: p.attrib["value"]
                     for p in case.findall("./properties/property")}
            self.assertIn("case_id", props)
            self.assertIn("case_source", props)
            ids.add(props["case_id"])
        self.assertEqual(len(ids), 3)

    def test_bad_markers_stop_collection(self):
        for fault in ("missing", "duplicate", "wrong"):
            with self.subTest(fault=fault):
                result = run_pytest(
                    "tests/kes/test_package_identity.py",
                    "--collect-only", "-q",
                    "-p", "fault_probe", fault=fault,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("case_id", result.stdout + result.stderr)

    def test_static_checker_accepts_current_mapping(self):
        result = subprocess.run(
            [sys.executable, "tools/check_test_traceability.py"], cwd=ROOT,
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
