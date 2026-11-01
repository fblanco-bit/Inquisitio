"""Run the complete test suite when the development-only pytest wheel is unavailable."""
from __future__ import annotations

import contextlib
import importlib
import inspect
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _Raises(contextlib.AbstractContextManager):
    def __init__(self, exception: type[BaseException], match: str | None = None):
        self.exception = exception
        self.match = match

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None or not issubclass(exc_type, self.exception):
            return False
        if self.match and not re.search(self.match, str(exc)):
            raise AssertionError(f"{exc!r} did not match {self.match!r}")
        return True


def _parametrize(names: str, values: list):
    fields = [name.strip() for name in names.split(",")]

    def decorate(function):
        cases = []
        for value in values:
            row = value if isinstance(value, tuple) else (value,)
            cases.append(dict(zip(fields, row)))
        function.__offline_parameter_cases__ = cases
        return function
    return decorate


pytest = types.ModuleType("pytest")
pytest.mark = types.SimpleNamespace(parametrize=_parametrize)
pytest.raises = lambda exception, match=None: _Raises(exception, match)
pytest.skip = lambda message="": (_ for _ in ()).throw(unittest.SkipTest(message))
sys.modules.setdefault("pytest", pytest)


def run_function_tests(module_name: str) -> unittest.TestSuite:
    module = importlib.import_module(module_name)
    suite = unittest.TestSuite()
    for name, function in inspect.getmembers(module, inspect.isfunction):
        if not name.startswith("test_"):
            continue
        cases = getattr(function, "__offline_parameter_cases__", [{}])
        for index, parameters in enumerate(cases, start=1):
            def execute(fn=function, supplied=parameters):
                arguments = dict(supplied)
                with tempfile.TemporaryDirectory() as directory:
                    if "tmp_path" in inspect.signature(fn).parameters:
                        arguments["tmp_path"] = Path(directory)
                    fn(**arguments)
            label = f"{module_name}.{name}" + (f"[{index}]" if len(cases) > 1 else "")
            suite.addTest(unittest.FunctionTestCase(execute, description=label))
    return suite


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for module_name in (
        "tests.test_binding", "tests.test_engine", "tests.test_evidence", "tests.test_exporter",
        "tests.test_forms", "tests.test_server", "tests.test_storage",
    ):
        suite.addTests(loader.loadTestsFromName(module_name))
    suite.addTests(run_function_tests("tests.test_extraction_pipeline"))
    suite.addTests(run_function_tests("tests.test_launcher"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
