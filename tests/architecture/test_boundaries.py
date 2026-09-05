"""验证门禁确实拒绝公开/私有头、实现及反向扩展依赖。"""
import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[2] / "tools" / "check_boundaries.py"
SPEC = importlib.util.spec_from_file_location("boundaries", MODULE)
boundaries = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boundaries)


class BoundaryTests(unittest.TestCase):
    def probe(self, path, text, expected):
        with tempfile.TemporaryDirectory(prefix="portable-boundary-") as folder:
            root = Path(folder)
            file = root / path
            file.parent.mkdir(parents=True)
            file.write_text(text, encoding="utf-8")
            count, errors = boundaries.scan(root)
            self.assertEqual(count, 1)
            self.assertEqual(bool(errors), expected, errors)

    def test_valid_core(self):
        self.probe("include/portable/core/host.hpp", "#include <portable/contracts/module.hpp>\n", False)

    def test_adapter_private_type_allowed(self):
        self.probe("src/adapters/sqlite/private.hpp", "sqlite3* connection;", False)

    def test_dependency_negative_matrix(self):
        cases = [
            ("include/portable/core/host.hpp", "DocumentId target;"),
            ("src/core/private.hpp", "#include <portable/workspace/document.hpp>"),
            ("src/core/private.h", "RevisionSet revision;"),
            ("src/core/private.ipp", "sqlite3* database;"),
            ("src/core/runtime.cpp", "#include <QString>"),
            ("src/core/runtime.cxx", "#include <TopoDS_Shape.hxx>"),
            ("src/foundation/private.hpp", "#include <portable/core/host.hpp>"),
            ("src/contracts/private.hpp", "#include <portable/core/host.hpp>"),
            ("src/automation/plan.hpp", "#include <portable/workflow/runtime.hpp>"),
            ("src/core/private.hpp", '# include "../workspace/state.hpp"'),
            ("include/portable/core/api.hpp", '#include "../../../src/core/private.hpp"'),
            ("include/portable/adapters/db.hpp", "sqlite3* database;"),
            ("src/core/old.hpp", "#include <lasercnc/kernel/app_kernel.hpp>"),
            ("src/core/unknown.hpp", "#include <portable/unknown/service.hpp>"),
            ("src/misc/escape.hpp", "struct Unknown {};"),
        ]
        for path, content in cases:
            with self.subTest(path=path, content=content):
                self.probe(path, content, True)

    def test_empty_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(boundaries.scan(Path(folder))[1])
            self.assertFalse(boundaries.scan(Path(folder), allow_empty=True)[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
