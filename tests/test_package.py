import importlib

import finqa

SUBPACKAGES = ["ingestion", "tools", "generators", "verifiers", "eval", "rq2"]


def test_package_imports() -> None:
    assert finqa.__version__


def test_subpackages_import() -> None:
    for name in SUBPACKAGES:
        importlib.import_module(f"finqa.{name}")
