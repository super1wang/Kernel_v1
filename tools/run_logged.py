"""执行一个命令，将 stdout/stderr、实际退出码、耗时及完整参数写入证据。"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        parser.error("缺少命令")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    record = {"command": command, "cwd": str(Path.cwd()), "started_utc": datetime.now(timezone.utc).isoformat()}
    with args.output.with_suffix(".log").open("xb") as log:
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    record.update(exit_code=completed.returncode, elapsed_seconds=time.monotonic() - start)
    args.output.with_suffix(".json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"command-finished: exit={completed.returncode}; evidence={args.output}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
