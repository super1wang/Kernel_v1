"""校验基线报告摘要，输出各独立进程中位数范围，不推导 P99。"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    index = json.loads((args.evidence / "baseline-index.json").read_text(encoding="utf-8"))
    if not index.get("completed") or not index["runs"]:
        raise RuntimeError("基线未完成，不生成通过摘要")
    rows = {}
    for run in index["runs"]:
        if run["exit_code"] != 0 or not run.get("report_verified"):
            raise RuntimeError("基线包含失败或未验证报告")
        report = args.evidence / run["report_file"]
        if hashlib.sha256(report.read_bytes()).hexdigest() != run["report_sha256"]:
            raise RuntimeError(f"报告摘要不匹配：{report}")
        data = json.loads(report.read_text(encoding="utf-8"))
        metadata = data["metadata"]
        for row in data["operations"]:
            key = (metadata["family"], metadata["storage"], row["operation"])
            rows.setdefault(key, []).append(row["median_ms"])
        for operation in ("startup_seed_ms", "shutdown_destroy_ms"):
            if data["lifecycle"]:
                key = (metadata["family"], metadata["storage"], operation)
                rows.setdefault(key, []).append(statistics.median(row[operation] for row in data["lifecycle"]))
    output = ["# 固定 donor 初始基线摘要", "", f"源版本：`{index['source_commit']}`。配置：Release。",
              "", "以下为各独立进程中位数的最小值/中位值/最大值，单位毫秒；不是单次调用 P99 或置信区间。",
              "", "| 场景 | 存储 | 操作 | 进程数 | 最小中位数 | 中位数的中位数 | 最大中位数 |",
              "|---|---|---|---:|---:|---:|---:|"]
    for (family, storage, operation), values in sorted(rows.items()):
        output.append(f"| {family} | {storage} | `{operation}` | {len(values)} | {min(values):.6f} | {statistics.median(values):.6f} | {max(values):.6f} |")
    output += ["", "限制：" + "；".join(index["limitations"]) + "。", ""]
    destination = args.evidence / "摘要.md"
    destination.write_text("\n".join(output), encoding="utf-8", newline="\n")
    print(f"summary-verified: {destination}")


if __name__ == "__main__":
    main()
