"""Verify the pinned makepy artifact without pretending to execute native COM.

The full normalized-byte hash guards every generated interface. Independent ABI
fixtures below also expose the version, dispatch IDs, scalar types and by-ref
flags relied on by the adapter. Regeneration requires reviewing both witnesses.
Only Git's CRLF/LF checkout conversion is normalized; no syntax is discarded.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BINDING_PATH = "src/solidworks_mcp/adapters/_generated/sldworks_2026.py"
SHA256_LF = "e74de9374bae3b0b76d95f163ee65cd9c36d180f04ac02dc2652a30ba0e0d4c4"


@pytest.fixture(scope="module")
def binding():
    """Parse the real artifact, never import pywin32 or connect to SolidWorks."""
    source = (ROOT / BINDING_PATH).read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == SHA256_LF
    tree = ast.parse(source, filename=BINDING_PATH)
    compile(tree, BINDING_PATH, "exec")  # Python syntax gate; no execution.
    return tree


def test_generated_typelib_version_and_generator_are_pinned(binding):
    """A different typelib or generation tool needs an explicit artifact review."""
    assignments = {
        node.targets[0].id: node.value
        for node in binding.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    expected = {
        "makepy_version": "0.5.01",
        "python_version": 0x30E05F0,
        "MajorVersion": 34,
        "MinorVersion": 0,
        "LibraryFlags": 8,
        "LCID": 0,
    }
    assert {name: ast.literal_eval(assignments[name]) for name in expected} == expected
    assert (
        ast.unparse(assignments["CLSID"])
        == "IID('{83A33D31-27C5-11CE-BFD4-00400513BB57}')"
    )


@pytest.mark.parametrize(
    "interface,method,parameters,dispatch",
    [
        (
            "ISldWorks",
            "GetProcessID",
            [],
            "self._oleobj_.InvokeTypes(166, LCID, 1, (3, 0), ())",
        ),
        (
            "ISldWorks",
            "OpenDoc6",
            ["FileName", "Type", "Options", "Configuration", "Errors", "Warnings"],
            "self._ApplyTypes_(167, 1, (9, 0), ((8, 1), (3, 1), (3, 1), (8, 1), (16387, 3), (16387, 3)), 'OpenDoc6', '{B90793FB-EF3D-4B80-A5C4-99959CDB6CEB}', FileName, Type, Options, Configuration, Errors, Warnings)",
        ),
        (
            "IModelDoc2",
            "SaveAs3",
            ["NewName", "SaveAsVersion", "Options"],
            "self._oleobj_.InvokeTypes(66222, LCID, 1, (3, 0), ((8, 1), (3, 1), (3, 1)), NewName, SaveAsVersion, Options)",
        ),
        (
            "IDrawingDoc",
            "CreateDrawViewFromModelView3",
            ["ModelName", "ViewName", "LocX", "LocY", "LocZ"],
            "self._oleobj_.InvokeTypes(228, LCID, 1, (9, 0), ((8, 1), (8, 1), (5, 1), (5, 1), (5, 1)), ModelName, ViewName, LocX, LocY, LocZ)",
        ),
        (
            "IAnnotation",
            "GetName",
            [],
            "self._oleobj_.InvokeTypes(21, LCID, 1, (8, 0), ())",
        ),
        (
            "IAnnotation",
            "GetType",
            [],
            "self._oleobj_.InvokeTypes(5, LCID, 1, (3, 0), ())",
        ),
        (
            "IAnnotation",
            "GetPosition",
            [],
            "self._ApplyTypes_(8, 1, (12, 0), (), 'GetPosition', None)",
        ),
    ],
)
def test_generated_native_call_contract(
    binding, interface, method, parameters, dispatch
):
    """Pin critical typed arguments; this is not native execution coverage."""
    cls = next(
        node
        for node in binding.body
        if isinstance(node, ast.ClassDef) and node.name == interface
    )
    member = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == method
    )
    assert [arg.arg for arg in member.args.args] == ["self", *parameters]
    assert len(member.args.defaults) == len(parameters)
    calls = [
        ast.unparse(node) for node in ast.walk(member) if isinstance(node, ast.Call)
    ]
    assert dispatch in calls


def test_coverage_includes_every_authored_runtime_file():
    """The exception is one reviewed generated artifact, never a package glob."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    run = config["tool"]["coverage"]["run"]
    assert run["source"] == ["src/solidworks_mcp"]
    assert "--cov-fail-under=90" in config["tool"]["pytest"]["ini_options"]["addopts"]
    excluded = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src/solidworks_mcp").rglob("*.py")
        if any(
            fnmatch.fnmatchcase(path.relative_to(ROOT).as_posix(), pattern)
            for pattern in run["omit"]
        )
    }
    assert excluded == {BINDING_PATH}
    assert BINDING_PATH in run["omit"]
    assert not any("_generated/*" in pattern for pattern in run["omit"])
