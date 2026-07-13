"""Tests for sw_type_info method flagging helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_import_handles_missing_pywin32(monkeypatch) -> None:
    """Import should handle missing win32com gracefully."""
    # Load the module under an alias while forcing win32com to fail.
    import builtins

    original_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name.startswith("win32com"):
            raise ImportError("blocked")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    module_path = (
        Path(__file__).parents[3]
        / "src"
        / "solidworks_mcp"
        / "adapters"
        / "sw_type_info.py"
    )
    spec = importlib.util.spec_from_file_location(
        "sw_type_info_no_pywin32", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.PYWIN32_AVAILABLE is False


def test_interface_method_names_empty_when_unloaded(monkeypatch) -> None:
    """interface_method_names should return empty set when wrapper missing."""
    # Force the module to behave as if pywin32 is unavailable.
    from solidworks_mcp.adapters import sw_type_info

    monkeypatch.setattr(sw_type_info, "PYWIN32_AVAILABLE", False)
    sw_type_info._wrapper_module = None
    sw_type_info._interface_methods.clear()

    result = sw_type_info.interface_method_names("ISldWorks")
    assert result == frozenset()


def test_flag_methods_returns_zero_when_no_methods(monkeypatch) -> None:
    """flag_methods should no-op when no interface methods are loaded."""
    # Ensure we return zero when nothing is loaded to flag.
    from solidworks_mcp.adapters import sw_type_info

    monkeypatch.setattr(sw_type_info, "_interface_methods", {})
    assert sw_type_info.flag_methods(object(), "ISldWorks") == 0


def test_flagged_passes_through_none() -> None:
    """flagged should return None when obj is None."""
    # Validate the None short-circuit in flagged().
    from solidworks_mcp.adapters import sw_type_info

    assert sw_type_info.flagged(None, "ISldWorks") is None


def test_flag_method_names_flags_only_requested_names_and_caches() -> None:
    """Selective flagging avoids replaying names on the same dispatch."""
    from solidworks_mcp.adapters import sw_type_info

    obj = _Flaggable()
    assert sw_type_info.flag_method_names(obj, "GetNextView", "GetOutline") == 2
    assert sw_type_info.flag_method_names(obj, "GetNextView") == 0
    assert obj.flagged == ["GetNextView", "GetOutline"]


class _Flaggable:
    """Weakref-able stand-in for a CDispatch recording _FlagAsMethod calls."""

    def __init__(self) -> None:
        self.flagged: list[str] = []

    def _FlagAsMethod(self, name: str) -> None:  # noqa: N802 — COM casing
        self.flagged.append(name)


def test_invalidate_flag_cache_clears_and_pops() -> None:
    """invalidate_flag_cache should clear or remove entries."""
    # Validate both the full clear and per-object pop behavior.
    import weakref

    from solidworks_mcp.adapters import sw_type_info

    obj = _Flaggable()
    sw_type_info._flag_cache[id(obj)] = (weakref.ref(obj), {"ISldWorks"})
    sw_type_info.invalidate_flag_cache(obj)
    assert id(obj) not in sw_type_info._flag_cache

    sw_type_info._flag_cache[id(obj)] = (weakref.ref(obj), {"ISldWorks"})
    sw_type_info.invalidate_flag_cache()
    assert sw_type_info._flag_cache == {}


def test_flag_cache_hit_requires_identity(monkeypatch) -> None:
    """A new object at a recycled id must be flagged, not cache-skipped.

    Regression: the cache was keyed by bare ``id(obj)``, so a fresh dispatch
    allocated at a garbage-collected object's address inherited its
    "already flagged" record and was silently left unflagged (live symptom:
    ``GetActiveSketch2`` degraded to a property read mid-session and
    ``create_sketch`` returned synthetic ``Sketch_N`` names).
    """
    from solidworks_mcp.adapters import sw_type_info

    monkeypatch.setattr(
        sw_type_info, "_interface_methods", {"IModelDoc2": frozenset({"GetTitle"})}
    )
    monkeypatch.setattr(sw_type_info, "_wrapper_module", object())

    first = _Flaggable()
    assert sw_type_info.flag_methods(first, "IModelDoc2") == 1
    assert sw_type_info.flag_methods(first, "IModelDoc2") == 0  # same obj: no-op

    # Simulate id reuse: poison the cache at the new object's id with an
    # entry whose weakref points at a *different* (still-alive) object.
    second = _Flaggable()
    import weakref

    sw_type_info._flag_cache[id(second)] = (weakref.ref(first), {"IModelDoc2"})
    assert sw_type_info.flag_methods(second, "IModelDoc2") == 1
    assert second.flagged == ["GetTitle"]


def test_flag_cache_entry_evicted_on_gc(monkeypatch) -> None:
    """Cache entries disappear when their object is garbage collected."""
    import gc

    from solidworks_mcp.adapters import sw_type_info

    monkeypatch.setattr(
        sw_type_info, "_interface_methods", {"IModelDoc2": frozenset({"GetTitle"})}
    )
    monkeypatch.setattr(sw_type_info, "_wrapper_module", object())

    obj = _Flaggable()
    sw_type_info.flag_methods(obj, "IModelDoc2")
    obj_id = id(obj)
    assert obj_id in sw_type_info._flag_cache
    del obj
    gc.collect()
    assert obj_id not in sw_type_info._flag_cache


def test_load_wrapper_warns_when_genpy_missing(monkeypatch) -> None:
    """_load_wrapper should warn when neither the checked-in wrapper nor gen_py loads."""
    # Simulate BOTH the checked-in ``_generated.sldworks_2026`` import and
    # gencache failing to load or generate a wrapper module.
    import sys
    import types

    from solidworks_mcp.adapters import sw_type_info

    warnings: list[str] = []

    # Block the checked-in wrapper import: a PEP 562 module ``__getattr__`` that
    # raises makes ``from ._generated import sldworks_2026`` fail like a missing
    # artifact would, so the gencache fallback path is exercised.
    broken_generated = types.ModuleType("solidworks_mcp.adapters._generated")

    def _raise_missing(_name: str):
        raise ImportError("checked-in wrapper unavailable")

    broken_generated.__getattr__ = _raise_missing  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules, "solidworks_mcp.adapters._generated", broken_generated
    )
    monkeypatch.setitem(
        sys.modules, "solidworks_mcp.adapters._generated.sldworks_2026", None
    )

    class _FakeCache:
        @staticmethod
        def GetModuleForTypelib(*_a, **_kw):
            return None

        @staticmethod
        def EnsureModule(*_a, **_kw):
            raise RuntimeError("no gen_py")

    monkeypatch.setattr(sw_type_info, "PYWIN32_AVAILABLE", True)
    monkeypatch.setattr(sw_type_info, "gencache", _FakeCache, raising=False)
    monkeypatch.setattr(
        sw_type_info,
        "logger",
        SimpleNamespace(warning=lambda msg: warnings.append(msg)),
    )
    sw_type_info._wrapper_module = None
    sw_type_info._interface_methods.clear()

    sw_type_info._load_wrapper()

    assert sw_type_info._wrapper_module is None
    assert any("generated wrapper not available" in msg for msg in warnings)


def test_early_bound_passes_through_none(monkeypatch) -> None:
    """early_bound returns None unchanged (no wrapper lookup attempted)."""
    from solidworks_mcp.adapters import sw_type_info

    monkeypatch.setattr(sw_type_info, "_ensure_loaded", lambda: None)
    assert sw_type_info.early_bound(None, "IModelDocExtension") is None


def test_early_bound_passes_through_when_wrapper_unloaded(monkeypatch) -> None:
    """With no gen_py wrapper module, the object is returned unchanged."""
    from solidworks_mcp.adapters import sw_type_info

    monkeypatch.setattr(sw_type_info, "_ensure_loaded", lambda: None)
    monkeypatch.setattr(sw_type_info, "_wrapper_module", None)
    obj = object()
    assert sw_type_info.early_bound(obj, "IModelDocExtension") is obj


def test_early_bound_raises_when_interface_absent(monkeypatch) -> None:
    """A loaded wrapper missing the requested interface fails loud, not silently.

    Silently returning the unwrapped dispatch defers the failure to a confusing
    downstream error (a base-interface method missing, a property read as a
    method); raising here names the bad interface at the point it is requested.
    """
    from solidworks_mcp.adapters import sw_type_info

    monkeypatch.setattr(sw_type_info, "_ensure_loaded", lambda: None)
    monkeypatch.setattr(sw_type_info, "_wrapper_module", SimpleNamespace())
    obj = SimpleNamespace(_oleobj_=object())
    with pytest.raises(ValueError, match="IModelDocExtension"):
        sw_type_info.early_bound(obj, "IModelDocExtension")


def test_early_bound_passes_through_when_no_oleobj(monkeypatch) -> None:
    """A dispatch without _oleobj_ cannot be re-wrapped, so it is returned as-is."""
    from solidworks_mcp.adapters import sw_type_info

    class _IModelDocExtension:
        def __init__(self, oleobj):
            self.__dict__["_oleobj_"] = oleobj

    monkeypatch.setattr(sw_type_info, "_ensure_loaded", lambda: None)
    monkeypatch.setattr(
        sw_type_info,
        "_wrapper_module",
        SimpleNamespace(IModelDocExtension=_IModelDocExtension),
    )
    obj = object()  # no _oleobj_
    assert sw_type_info.early_bound(obj, "IModelDocExtension") is obj


def test_early_bound_wraps_via_dispid(monkeypatch) -> None:
    """The raw _oleobj_ is wrapped by the interface class (dispid invocation).

    ``early_bound`` wraps through a :func:`_fallback_subclass` of the makepy
    class, so the returned object is an instance of that class holding the raw
    ``_oleobj_`` — not the original late-bound dispatch.
    """
    from solidworks_mcp.adapters import sw_type_info

    raw = object()

    class _IModelDocExtension:
        def __init__(self, oleobj):
            self.__dict__["_oleobj_"] = oleobj

    monkeypatch.setattr(sw_type_info, "_ensure_loaded", lambda: None)
    monkeypatch.setattr(
        sw_type_info,
        "_wrapper_module",
        SimpleNamespace(IModelDocExtension=_IModelDocExtension),
    )
    result = sw_type_info.early_bound(
        SimpleNamespace(_oleobj_=raw), "IModelDocExtension"
    )
    assert isinstance(result, _IModelDocExtension)
    assert result._oleobj_ is raw


def test_early_bound_keeps_already_typed_wrapper(monkeypatch) -> None:
    """Repeated casts of an early-bound wrapper are a no-op."""
    from solidworks_mcp.adapters import sw_type_info

    class _Typed:
        pass

    typed = _Typed()
    typed._oleobj_ = object()
    monkeypatch.setattr(sw_type_info, "_ensure_loaded", lambda: None)
    monkeypatch.setattr(
        sw_type_info, "_wrapper_module", SimpleNamespace(IView=_Typed)
    )
    assert sw_type_info.early_bound(typed, "IView") is typed
    assert sw_type_info.is_early_bound(typed, "IView") is True
    assert sw_type_info.is_early_bound(object(), "IView") is False
    assert sw_type_info.early_bound_or_flag(typed, "IView", "GetNextView") is typed


def test_early_bound_or_flag_selectively_flags_when_wrapper_is_unavailable(
    monkeypatch,
) -> None:
    """The compatibility fallback flags exact names, never the whole interface."""
    from solidworks_mcp.adapters import sw_type_info

    obj = _Flaggable()
    monkeypatch.setattr(sw_type_info, "_wrapper_module", None)
    monkeypatch.setattr(sw_type_info, "PYWIN32_AVAILABLE", False)
    result = sw_type_info.early_bound_or_flag(
        obj, "IView", "GetNextView", "GetOutline"
    )
    assert result is obj
    assert obj.flagged == ["GetNextView", "GetOutline"]


def test_early_bound_swallows_wrapper_construction_failure(monkeypatch) -> None:
    """If the wrapper class raises, the original object is returned unchanged."""
    from solidworks_mcp.adapters import sw_type_info

    class _Boom:
        def __init__(self, _oleobj):
            raise RuntimeError("bad dispatch")

    monkeypatch.setattr(sw_type_info, "_ensure_loaded", lambda: None)
    monkeypatch.setattr(
        sw_type_info, "_wrapper_module", SimpleNamespace(IModelDocExtension=_Boom)
    )
    obj = SimpleNamespace(_oleobj_=object())
    assert sw_type_info.early_bound(obj, "IModelDocExtension") is obj


def test_early_bound_fallback_forwards_off_interface_members(monkeypatch) -> None:
    """A member absent from the makepy interface class degrades to late binding.

    Real SW dispatches are polymorphic (IFace2's Select2 lives on IEntity;
    a part model's GetBodies2 lives on IPartDoc), so the early-bound wrapper
    must forward undeclared members to a late-bound dispatch on the same
    object instead of raising AttributeError.
    """
    from solidworks_mcp.adapters import sw_type_info

    class _FakeLate:
        """Stands in for ``dynamic.Dispatch(oleobj)`` — carries the members
        the interface class does not declare."""

        def OffMethod(self, x):
            return ("off", x)

    late = _FakeLate()

    class _FakeBase:
        """Mimics the makepy ``DispatchBaseClass`` contract: a real declared
        method, a declared property via ``_prop_map_get_``, AttributeError for
        everything else, and ``_oleobj_`` set through ``__dict__``."""

        _prop_map_get_ = {"DeclaredProp": ()}

        def __init__(self, oleobj):
            self.__dict__["_oleobj_"] = oleobj

        def DeclaredMethod(self):
            return "declared-method"

        def __getattr__(self, attr):
            if attr in self._prop_map_get_:
                return "declared-prop"
            raise AttributeError(attr)

        def __setattr__(self, attr, value):
            if attr in self.__dict__:
                self.__dict__[attr] = value
                return
            raise AttributeError(attr)

    monkeypatch.setattr(
        "win32com.client.dynamic.Dispatch", lambda _oleobj: late, raising=False
    )

    wrapped = sw_type_info._fallback_subclass(_FakeBase)(object())

    # Declared method: found by normal lookup, never touches the fallback.
    assert wrapped.DeclaredMethod() == "declared-method"
    # Declared property: resolved by the makepy base __getattr__.
    assert wrapped.DeclaredProp == "declared-prop"
    # Undeclared member: forwarded to the late-bound dispatch.
    assert wrapped.OffMethod(5) == ("off", 5)
    # The fallback dispatch is built once and reused.
    assert wrapped.__dict__["_late_bound_dispatch"] is late
    # Undeclared attribute set also forwards to the late-bound dispatch.
    wrapped.OffAttr = 7
    assert late.OffAttr == 7


def test_early_bound_fallback_reuses_subclass_per_base() -> None:
    """The same makepy base yields one cached fallback subclass."""
    from solidworks_mcp.adapters import sw_type_info

    class _Base:
        def __init__(self, oleobj):
            self.__dict__["_oleobj_"] = oleobj

    first = sw_type_info._fallback_subclass(_Base)
    second = sw_type_info._fallback_subclass(_Base)
    assert first is second
    assert issubclass(first, _Base)
