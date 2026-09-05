"""证据收集不能把非零退出或不完整采样认定为通过。"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("baseline", ROOT / "tools/run_baseline.py")
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


class EvidenceTests(unittest.TestCase):
    def test_nonzero_exit_with_success_text_is_failure(self):
        with tempfile.TemporaryDirectory(prefix="portable-evidence-") as folder:
            destination = Path(folder) / "probe"
            command = [sys.executable, str(ROOT / "tools/run_logged.py"), "--output", str(destination), "--",
                       sys.executable, "-c", "print('benchmark-verified: fake'); raise SystemExit(7)"]
            result = subprocess.run(command, capture_output=True)
            self.assertEqual(result.returncode, 7)
            record = json.loads(destination.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(record["exit_code"], 7)
            self.assertIn("benchmark-verified", destination.with_suffix(".log").read_text())
            # 重跑不得覆盖第一次故障证据。
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(json.loads(destination.with_suffix(".json").read_text())["exit_code"], 7)

    def test_report_config_and_sample_count(self):
        report = {"metadata": {"family": "gateway", "storage": "memory", "object_count": 1000,
                               "build_config": "Release", "samples": 64, "warmup": 3, "cycles": 10},
                  "operations": [{"raw_samples": [{}] * 64}], "lifecycle": []}
        baseline.validate_report(report, "gateway", "memory", 64)
        for key, invalid in (("family", "component"), ("storage", "sqlite"), ("object_count", 10),
                             ("build_config", "Debug"), ("samples", 5)):
            with self.subTest(key=key):
                broken = copy.deepcopy(report)
                broken["metadata"][key] = invalid
                with self.assertRaises(RuntimeError):
                    baseline.validate_report(broken, "gateway", "memory", 64)
        report["operations"][0]["raw_samples"].pop()
        with self.assertRaises(RuntimeError):
            baseline.validate_report(report, "gateway", "memory", 64)

    def test_lifecycle_requires_ten_cycles(self):
        report = {"metadata": {"family": "lifecycle", "storage": "memory", "object_count": 1000,
                               "build_config": "Release", "samples": 64, "warmup": 3, "cycles": 10},
                  "operations": [], "lifecycle": []}
        with self.assertRaises(RuntimeError):
            baseline.validate_report(report, "lifecycle", "memory", 64)
        report["lifecycle"] = [{}] * 10
        baseline.validate_report(report, "lifecycle", "memory", 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
