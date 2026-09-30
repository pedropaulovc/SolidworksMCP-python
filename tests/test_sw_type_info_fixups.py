"""Offline contract for the SolidWorks typelib mistyping fixups.

``sw_type_info._apply_typelib_fixups`` corrects the two ``SetEntitiesToMate``
indexed properties the 2026 typelib mistypes as bare ``VT_DISPATCH`` (cam
follower + rack-pinion mate data) to the ``VT_VARIANT`` calling convention the
semantically identical ``IHingeMateFeatureData`` member declares.  These tests
pin the patched call shape at the ``InvokeTypes`` boundary through fake makepy
classes — no SolidWorks, no pywin32 required (VARIANT-specific assertions are
skipped where pywin32 is absent).
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from solidworks_mcp.adapters import sw_type_info

try:
    import pythoncom
    from win32com.client import VARIANT

    PYWIN32 = True
except Exception:  # pragma: no cover - Linux CI
    PYWIN32 = False


class _RecordingOle:
    """Stands in for a makepy ``_oleobj_``; records ``InvokeTypes`` calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def InvokeTypes(self, *args: Any) -> str:
        self.calls.append(args)
        return "invoked"


def _broken_class(name: str) -> type:
    """Mimic the generated wrapper's mistyped cam/rack-pinion class."""

    class Broken:
        def __init__(self) -> None:
            self._oleobj_ = _RecordingOle()
            self.applied: list[tuple[Any, ...]] = []

        # The generated (broken) signatures: value slot typed (9, 1).
        def EntitiesToMate(self, EntityType: Any) -> Any:
            return self._oleobj_.InvokeTypes(1, 0, 2, (9, 0), ((3, 1),), EntityType)

        def SetEntitiesToMate(self, EntityType: Any, arg1: Any) -> Any:
            return self._oleobj_.InvokeTypes(
                1, 0, 4, (24, 0), ((3, 1), (9, 1)), EntityType, arg1
            )

        def _ApplyTypes_(self, *args: Any) -> str:
            self.applied.append(args)
            return "applied"

    Broken.__name__ = name
    Broken.__qualname__ = name
    return Broken


def _fake_module() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        ICamFollowerMateFeatureData=_broken_class("ICamFollowerMateFeatureData"),
        IRackPinionMateFeatureData=_broken_class("IRackPinionMateFeatureData"),
        IHingeMateFeatureData=_broken_class("IHingeMateFeatureData"),
    )


class _Entity:
    """Fake makepy-wrapped entity carrying an ``_oleobj_``."""

    def __init__(self, tag: str) -> None:
        self._oleobj_ = f"raw-{tag}"


@pytest.mark.parametrize(
    "class_name", ["ICamFollowerMateFeatureData", "IRackPinionMateFeatureData"]
)
def test_setter_retypes_value_slot_to_variant(class_name: str) -> None:
    module = _fake_module()
    sw_type_info._apply_typelib_fixups(module)
    data = getattr(module, class_name)()

    entities = [_Entity("cam"), _Entity("follower")]
    result = data.SetEntitiesToMate(9, entities)

    assert result == "invoked"
    (call,) = data._oleobj_.calls
    dispid, lcid, invkind, ret_type, arg_types, entity_type, value = call
    assert (dispid, lcid, invkind) == (1, 0, 4)
    assert ret_type == (24, 0)
    assert arg_types == ((3, 1), (12, 1)), (
        "value slot must be retyped VT_VARIANT (the IHingeMateFeatureData "
        "calling convention), not the typelib's bare VT_DISPATCH"
    )
    assert entity_type == 9
    if PYWIN32:
        assert isinstance(value, VARIANT)
        assert value.varianttype == pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH
        assert value.value == ["raw-cam", "raw-follower"]
    else:
        assert value == ["raw-cam", "raw-follower"]


def test_setter_passes_non_sequence_value_through() -> None:
    module = _fake_module()
    sw_type_info._apply_typelib_fixups(module)
    data = module.ICamFollowerMateFeatureData()

    sentinel = object()
    data.SetEntitiesToMate(4, sentinel)

    (call,) = data._oleobj_.calls
    assert call[-1] is sentinel


def test_getter_reads_variant_array() -> None:
    module = _fake_module()
    sw_type_info._apply_typelib_fixups(module)
    data = module.ICamFollowerMateFeatureData()

    result = data.EntitiesToMate(9)

    assert result == "applied"
    assert data._oleobj_.calls == []
    (applied,) = data.applied
    assert applied == (1, 2, (12, 0), ((3, 1),), "EntitiesToMate", None, 9)


def test_fixup_is_idempotent() -> None:
    module = _fake_module()
    sw_type_info._apply_typelib_fixups(module)
    first_setter = module.ICamFollowerMateFeatureData.SetEntitiesToMate
    sw_type_info._apply_typelib_fixups(module)
    assert module.ICamFollowerMateFeatureData.SetEntitiesToMate is first_setter


def test_correctly_typed_classes_untouched() -> None:
    module = _fake_module()
    original = module.IHingeMateFeatureData.SetEntitiesToMate
    sw_type_info._apply_typelib_fixups(module)
    assert module.IHingeMateFeatureData.SetEntitiesToMate is original
    assert not hasattr(module.IHingeMateFeatureData, "_sw_entity_array_fixup")


def test_missing_class_is_skipped() -> None:
    module = types.SimpleNamespace(ICamFollowerMateFeatureData=None)
    sw_type_info._apply_typelib_fixups(module)  # must not raise


def test_entity_array_variant_unwraps_oleobj() -> None:
    raw = object()
    wrapped = _Entity("x")
    value = sw_type_info._entity_array_variant([wrapped, raw])
    items = value.value if PYWIN32 else value
    assert list(items) == ["raw-x", raw]


@pytest.mark.skipif(
    not sw_type_info.PYWIN32_AVAILABLE, reason="checked-in wrapper needs pywin32"
)
def test_checked_in_wrapper_gets_fixups() -> None:
    """The real vendored wrapper's classes carry the fixup after loading."""
    sw_type_info._ensure_loaded()
    module = sw_type_info._wrapper_module
    if module is None:
        pytest.skip("wrapper module unavailable on this machine")
    for class_name in sw_type_info._ENTITY_ARRAY_FIXUPS:
        cls = getattr(module, class_name)
        assert cls.__dict__.get("_sw_entity_array_fixup") is True
