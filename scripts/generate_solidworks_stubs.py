"""Generate a small, stable typing facade from a pywin32 makepy module.

The generated makepy module is executable dispatch code, not a type stub: its
methods and properties are unannotated and its filename contains typelib
identity/version details.  This script extracts the useful static shape into a
normal package module that can be checked in and imported under ``TYPE_CHECKING``.

It deliberately uses ``Any`` for COM values.  The SolidWorks typelib describes
VARIANT and IDispatch values accurately enough for invocation, but not accurately
enough to infer Python-level return tuples (especially methods with ``[out]``
parameters).  Member names and call signatures still provide useful completion
and catch misspellings, missing arguments, and extra arguments.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Iterable


DEFAULT_INTERFACES = (
    "IAnnotation",
    "IBeltChainFeatureData",
    "IBody2",
    "IDimension",
    "IDisplayDimension",
    "IFace2",
    "IFeature",
    "IModelDoc2",
    "IModelDocExtension",
    "INote",
    "ISelectionMgr",
    "ISketch",
    "ISketchManager",
    "ISldWorks",
    "ISurface",
    "IView",
)


def _parameters(node: ast.FunctionDef) -> str:
    """Render a makepy method's Python call shape without sentinel defaults."""
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    defaults_at = len(positional) - len(args.defaults)
    rendered: list[str] = []
    for index, arg in enumerate(positional):
        item = arg.arg if arg.arg == "self" else f"{arg.arg}: Any"
        if index >= defaults_at:
            item += " = ..."
        rendered.append(item)
    if args.vararg:
        rendered.append(f"*{args.vararg.arg}: Any")
    elif args.kwonlyargs:
        rendered.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        item = f"{arg.arg}: Any"
        if default is not None:
            item += " = ..."
        rendered.append(item)
    if args.kwarg:
        rendered.append(f"**{args.kwarg.arg}: Any")
    return ", ".join(rendered)


def _property_names(node: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for statement in node.body:
        if not isinstance(statement, ast.Assign):
            continue
        targets = [target.id for target in statement.targets if isinstance(target, ast.Name)]
        if not ({"_prop_map_get_", "_prop_map_put_"} & set(targets)):
            continue
        if isinstance(statement.value, ast.Dict):
            for key in statement.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    names.add(key.value)
    return names


def generate_stub(source: str, interfaces: Iterable[str]) -> str:
    """Return a deterministic ``.pyi`` facade for selected makepy interfaces."""
    wanted = set(interfaces)
    tree = ast.parse(source)
    classes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in wanted
    }
    missing = wanted - classes.keys()
    if missing:
        raise ValueError(f"interfaces absent from makepy module: {', '.join(sorted(missing))}")

    lines = [
        '"""Generated SolidWorks COM interface shapes; do not edit by hand."""',
        "",
        "from typing import Any, Protocol",
        "",
    ]
    for name in sorted(classes):
        node = classes[name]
        methods = [item for item in node.body if isinstance(item, ast.FunctionDef)]
        method_names = {item.name for item in methods}
        properties = sorted(_property_names(node) - method_names)
        lines.append(f"class {name}(Protocol):")
        for prop in properties:
            lines.append(f"    {prop}: Any")
        for method in methods:
            lines.append(f"    def {method.name}({_parameters(method)}) -> Any: ...")
        if not properties and not methods:
            lines.append("    ...")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="makepy-generated sldworks module")
    parser.add_argument("output", type=Path, help="destination .pyi file")
    parser.add_argument(
        "--interface",
        action="append",
        dest="interfaces",
        help="interface to include (repeatable; defaults to adapter core set)",
    )
    args = parser.parse_args()
    result = generate_stub(
        args.input.read_text(encoding="utf-8"),
        args.interfaces or DEFAULT_INTERFACES,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
