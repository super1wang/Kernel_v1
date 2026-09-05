"""扫描生产代码的分层依赖，包括公开头、私有头及内联实现。"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

EXTENSIONS = {".h", ".hh", ".hpp", ".hxx", ".ipp", ".inl", ".tpp", ".c", ".cc", ".cpp", ".cxx"}
LAYERS = {"foundation", "contracts", "core", "automation", "durable", "workflow", "workspace", "control", "adapters"}
ALLOWED = {
    "foundation": {"foundation"},
    "contracts": {"foundation", "contracts"},
    "core": {"foundation", "contracts", "core"},
    "automation": {"foundation", "contracts", "core", "automation"},
    "durable": {"foundation", "contracts", "core", "durable"},
    "workflow": {"foundation", "contracts", "core", "automation", "durable", "workflow"},
    "workspace": {"foundation", "contracts", "core", "workspace"},
    "control": {"foundation", "contracts", "core", "control"},
    "adapters": LAYERS,
}
THIRD_PARTY = re.compile(
    r"\b(?:spdlog|jsoncons|toml|BS|tf|opentelemetry)::|\bsqlite3\w*\b|"
    r"\b(?:QWidget|QObject|QString|QVariant|QCoreApplication|TopoDS_\w*|TDF_\w*|TDocStd_\w*)\b|"
    r"#\s*include\s*[<\"](?:Qt\w*/|Q[A-Z]\w*|spdlog/|jsoncons/|toml(?:\.hpp|11/)|BS_thread_pool\.hpp|sqlite3\.h|TopoDS|TDF_|TDocStd_)"
)
STATE_TYPES = re.compile(r"\b(?:ProjectId|DocumentId|ProjectRuntime|DocumentRuntime|DocumentStore|RevisionSet|TransactionCommit|ApplicationTransaction|EditSession)\b")
INCLUDE = re.compile(r'#\s*include\s*[<"]([^>"\n]+)[>"]')


def scan(root: Path, allow_empty: bool = False) -> tuple[int, list[str]]:
    root = root.resolve()
    files = sorted(p for base in (root / "include", root / "src") if base.exists()
                   for p in base.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS)
    errors: list[str] = []
    if not files and not allow_empty:
        errors.append("未发现生产源码，不能报告边界验证通过")
    for path in files:
        relative = path.relative_to(root)
        parts = relative.parts
        public = parts[0] == "include"
        layer = parts[2] if public and len(parts) > 3 and parts[1] == "portable" else (parts[1] if not public and len(parts) > 2 else "")
        if layer not in LAYERS:
            errors.append(f"{relative}: 未声明的生产组件目录")
            continue
        content = path.read_text(encoding="utf-8-sig")
        for number, line in enumerate(content.splitlines(), 1):
            if (public or layer != "adapters") and THIRD_PARTY.search(line):
                errors.append(f"{relative}:{number}: 第三方类型或头文件泄漏")
            if layer in {"foundation", "contracts", "core"} and STATE_TYPES.search(line):
                errors.append(f"{relative}:{number}: 必选核心包含状态扩展类型")
        for match in INCLUDE.finditer(content):
            include = match.group(1).replace("\\", "/")
            target_layer = None
            if include.startswith("portable/"):
                target_layer = include.split("/")[1]
            elif include.startswith("lasercnc/"):
                errors.append(f"{relative}: 不允许回接原内核头 {include}")
            elif ":" in include or include.startswith("/"):
                errors.append(f"{relative}: 不允许绝对包含路径 {include}")
            else:
                resolved = (path.parent / include).resolve()
                if resolved.is_relative_to(root / "src"):
                    target_layer = resolved.relative_to(root / "src").parts[0]
                    if public:
                        errors.append(f"{relative}: 公开头包含私有实现 {include}")
                elif ".." in include.split("/"):
                    errors.append(f"{relative}: 未受治理的相对包含路径 {include}")
            if target_layer is not None and target_layer not in ALLOWED[layer]:
                errors.append(f"{relative}: {layer} 不得依赖 {target_layer}: {include}")
    return len(files), errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--allow-empty", action="store_true", help="仅限无生产代码的 M0 门禁引导")
    args = parser.parse_args()
    count, errors = scan(args.root, args.allow_empty)
    for error in errors:
        print(error)
    if errors:
        return 1
    print(f"boundary-verified: {count} 个生产文件" + ("；M0 尚无生产代码" if count == 0 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
