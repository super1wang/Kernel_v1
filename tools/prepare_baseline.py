"""从只读 Git 对象和锁定依赖归档建立隔离的 M0 参考源；不修改参考工作区。"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = {
    "structure": "52b099a9e9cabfafe5a6c2c3e95f92c2e857ed03",
    "donor": "432434f9c43d3f83c124ac1cf23fec39018f394f",
}
DEPENDENCIES = {
    "spdlog": "79524ddd08a4ec981b7fea76afd08ee05f83755d",
    "jsoncons": "bcb44594c50c495ee1e690602cdd71455942ad0e",
    "toml11": "be08ba2be2a964edcdb3d3e3ea8d100abc26f286",
    "bs_thread_pool": "bd4533f1f70c2b975cbd5769a60d8eaaea1d2233",
    "catch2": "95d8a61b089317bec800c7cc4c64064cbcb3802d",
}
SQLITE_HASH = "628a44cfe82c66aed1ccbbe85a562d2e33ebe64b3288981ed76285612227934e"


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def extract_verified(data: bytes, destination: Path, strip_prefix: bool = False) -> dict:
    manifest = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            name = entry.filename.split("/", 1)[1] if strip_prefix else entry.filename
            target = (destination / name).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise RuntimeError(f"归档越界：{name}")
            content = archive.read(entry)
            if target.exists():
                if target.read_bytes() != content:
                    raise RuntimeError(f"参考源已变化，拒绝覆盖：{target}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            manifest[name] = hashlib.sha256(content).hexdigest()
    actual = {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
    if actual != set(manifest):
        raise RuntimeError(f"参考目录含归档以外文件：{destination}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--dependency-cache", type=Path, required=True)
    args = parser.parse_args()
    records = {"schema": 1, "references": {}, "dependencies": {}}
    for role, revision in REFERENCES.items():
        data = git(args.repository, "archive", "--format=zip", revision)
        destination = ROOT / ".reference" / f"{role}-{revision[:8]}"
        files = extract_verified(data, destination)
        records["references"][role] = {
            "commit": revision,
            "tree": git(args.repository, "rev-parse", revision + "^{tree}").decode().strip(),
            "files_sha256": files,
        }
    configure = ["cmake", "-S", str(ROOT / ".reference/donor-432434f9"),
                 "-B", str(ROOT / "build/donor-release"), "-G", "Visual Studio 17 2022", "-A", "x64",
                 "-DLCNC_BUILD_TESTING=ON", "-DLCNC_WARNINGS_AS_ERRORS=ON"]
    for name, revision in DEPENDENCIES.items():
        repo = args.dependency_cache / (name + "-src")
        resolved = git(repo, "rev-parse", revision + "^{commit}").decode().strip()
        destination = ROOT / ".reference" / f"{name}-{revision[:8]}"
        files = extract_verified(git(repo, "archive", "--format=zip", revision), destination)
        records["dependencies"][name] = {"locked_object": revision, "commit": resolved,
                                           "archive_file_count": len(files),
                                           "tree": git(repo, "rev-parse", revision + "^{tree}").decode().strip()}
        configure.append(f"-DFETCHCONTENT_SOURCE_DIR_{name.upper()}={destination.as_posix()}")
    archive = args.dependency_cache / "sqlite-subbuild/sqlite-populate-prefix/src/sqlite-amalgamation-3530400.zip"
    data = archive.read_bytes()
    if hashlib.sha3_256(data).hexdigest() != SQLITE_HASH:
        raise RuntimeError("SQLite 归档与锁定 SHA3-256 不符")
    destination = ROOT / ".reference/sqlite-3530400"
    files = extract_verified(data, destination, strip_prefix=True)
    records["dependencies"]["sqlite"] = {"version": "3530400", "sha3_256": SQLITE_HASH, "files_sha256": files}
    configure.append(f"-DFETCHCONTENT_SOURCE_DIR_SQLITE={destination.as_posix()}")
    evidence = ROOT / "docs/evidence/m0"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "source-manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "build").mkdir(exist_ok=True)
    (ROOT / "build/donor-configure.json").write_text(json.dumps(configure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("reference-verified: 两个固定版本、五个 Git 依赖与 SQLite 归档；配置参数在 build/donor-configure.json")


if __name__ == "__main__":
    main()
