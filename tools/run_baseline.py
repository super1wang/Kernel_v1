"""运行固定 donor 的 Release 初始测量，保留真实输出、退出码与原始样本。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def validate_report(data: dict, family: str, storage: str, samples: int) -> None:
    metadata = data["metadata"]
    expected = {"family": family, "storage": storage, "object_count": 1000,
                "build_config": "Release", "samples": samples, "warmup": 3, "cycles": 10}
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise RuntimeError("基准报告与实际请求/配置不符")
    if family == "lifecycle":
        if len(data["lifecycle"]) != 10:
            raise RuntimeError("生命周期报告缺少完整周期")
    elif not data["operations"] or any(len(row["raw_samples"]) != samples for row in data["operations"]):
        raise RuntimeError("基准报告缺少原始样本")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build/donor-release")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--evidence-dir", type=Path,
                        default=ROOT / "docs/evidence/m0" / datetime.now(timezone.utc).strftime("baseline-%Y%m%dT%H%M%S"))
    args = parser.parse_args()
    if not 2 <= args.samples <= 64 or not 1 <= args.runs <= 10:
        parser.error("samples 必须为 2..64，runs 必须为 1..10")
    executable = args.build.resolve() / "tests/Release/lasercnc_kernel_benchmark.exe"
    evidence = args.evidence_dir.resolve()
    raw_root = ROOT / "out/donor-baseline"
    evidence.mkdir(parents=True, exist_ok=False)
    summary = {
        "schema": 1,
        "source_commit": "432434f9c43d3f83c124ac1cf23fec39018f394f",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "logical_processors": os.cpu_count(),
        "configuration": "Release",
        "binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "cmake_cache_sha256": hashlib.sha256((args.build / "CMakeCache.txt").read_bytes()).hexdigest(),
        "limitations": ["初始串行基线，无新内核 A/B", "每进程至多 64 次，不报告 P99",
                        "仅 1k 对象；并发、参数规模、任务尾延迟及完整容量矩阵未运行"],
        "runs": [],
    }
    manifest = ROOT / "docs/evidence/m0/source-manifest.json"
    summary["source_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    summary["configure_command"] = json.loads((ROOT / "build/donor-configure.json").read_text(encoding="utf-8"))
    (evidence / "baseline-index.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cases = [("gateway", "memory"), ("gateway", "sqlite"), ("component", "memory"),
             ("component", "sqlite"), ("journal", "sqlite"), ("lifecycle", "memory"), ("lifecycle", "sqlite")]
    for run in range(args.runs):
        for family, storage in (cases if run % 2 == 0 else list(reversed(cases))):
            command = [str(executable), "--objects", "1000", "--samples", str(args.samples),
                       "--warmup", "3", "--cycles", "10", "--family", family, "--storage", storage,
                       "--output-root", str(raw_root)]
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
            label = f"{family}-{storage}-run{run + 1}"
            (evidence / (label + ".log")).write_text(completed.stdout + completed.stderr, encoding="utf-8")
            marker = "benchmark-verified: "
            paths = [line.removeprefix(marker).strip() for line in completed.stdout.splitlines() if line.startswith(marker)]
            record = {"name": label, "command": command, "exit_code": completed.returncode, "completed_marker": len(paths) == 1}
            summary["runs"].append(record)
            (evidence / "baseline-index.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if completed.returncode != 0 or len(paths) != 1:
                raise RuntimeError(f"基线失败，保留原始输出：{label}")
            report = Path(paths[0]).resolve()
            if not report.is_relative_to(raw_root.resolve()):
                raise RuntimeError("基准返回了隔离目录之外的报告")
            data = json.loads(report.read_text(encoding="utf-8"))
            validate_report(data, family, storage, args.samples)
            shutil.copyfile(report, evidence / (label + ".json"))
            print(f"baseline-verified: {label}", flush=True)
    print(f"baseline-matrix-verified: {evidence}；初始七场景、多进程轮次完成；缺口见索引")


if __name__ == "__main__":
    main()
