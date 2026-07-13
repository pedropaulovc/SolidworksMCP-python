"""
SolidWorks early-bound COM interface resolution (with a flagging fallback).

Primary path — **early binding**: ``early_bound(obj, "IFace2")`` wraps a
pywin32 dispatch in the makepy interface class from a *checked-in* wrapper for
``sldworks.tlb`` (``._generated.sldworks_2026``), so members invoke by DISPID
via ``InvokeTypes`` — no per-name ``GetIDsOfNames`` round-trip. The wrapper is
vendored (not built in each user's ``gen_py`` cache), so startup never depends
on a writable temp dir or typelib discovery through a ROT proxy. Call sites use
``early_bound_or_flag(obj, iface, *fallback_names)`` and **reassign** the result
(``x = early_bound_or_flag(x, ...)``) — the wrapper is a new object.

Off-interface members stay safe: SW dispatches are polymorphic (a face is an
``IFace2`` and an ``IEntity``; a part model answers ``IModelDoc2`` and
``IPartDoc``), so ``early_bound`` returns a ``_fallback_subclass`` that forwards
any member the named interface class does not declare to a lazily-built
late-bound dispatch on the same object. No per-call-site interface-completeness
proof is needed.

Fallback path — **method flagging**: for interfaces absent from ``sldworks.tlb``
(the undocumented motion methods) or when the wrapper can't load, pywin32's
late-binding sometimes resolves SW zero-argument methods (``GetTitle``,
``GetPathName`` …) as *properties*, so calling them raises ``TypeError:
'str' object is not callable``. ``flag_methods(obj, *interfaces)`` /
``flag_method_names(obj, *names)`` call ``CDispatch._FlagAsMethod(name)`` to
force method (``Invoke``) resolution for names that belong to the object's real
interface. Per-interface (not flag-everything) because each unknown name is a
~5 ms ``GetIDsOfNames`` round-trip and the full TLB has ~6 000 names across 482
interfaces; per-interface flagging is ~1-3 s, whole-object early binding is ~0.

This module:

1. Loads the checked-in makepy wrapper for ``sldworks.tlb`` (``gen_py`` and
   lazy generation remain only as compatibility fallbacks).
2. Builds per-interface sets of method names for the flagging fallback.
3. Exposes ``early_bound`` / ``early_bound_or_flag`` (primary) and
   ``flag_methods`` / ``flag_method_names`` / ``flag_doc`` (fallback).
"""

from __future__ import annotations

import inspect
import weakref
from typing import Any

from loguru import logger

try:
    import win32com.client  # noqa: F401 — optional Windows dep
    from win32com.client import DispatchBaseClass, gencache

    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False


# SolidWorks type library IID (stable across SW versions).
SW_TLB_IID = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"

# Module state: populated by _load_wrapper() the first time it's needed.
_wrapper_module: Any | None = None
_interface_methods: dict[str, frozenset[str]] = {}
# Per-object record of which interfaces have already been flagged. Keyed by
# id(obj) so ``flag_methods(doc, 'IModelDoc2')`` followed by
# ``flag_methods(doc, 'IAssemblyDoc')`` does incremental work, not a no-op.
# The value carries a weakref to the object so a *new* dispatch landing at a
# recycled address is never mistaken for an already-flagged one — that
# collision left ``GetActiveSketch2`` (etc.) unflagged on fresh documents in
# long sessions, silently degrading them to property reads. Dead entries are
# evicted by the weakref callback.
_flag_cache: dict[int, tuple[weakref.ref[Any], set[str]]] = {}


def _cache_entry_for(obj: Any) -> set[str]:
    """Return the flagged-interface set for ``obj``, verifying identity.

    A hit requires the stored weakref to resolve to ``obj`` itself; a stale
    entry from a garbage-collected object at the same address is replaced.
    Objects that cannot be weak-referenced get a fresh (uncached) set each
    call — correct, just without the no-op shortcut.
    """
    obj_id = id(obj)
    entry = _flag_cache.get(obj_id)
    if entry is not None and entry[0]() is obj:
        return entry[1]

    already: set[str] = set()

    def _evict(ref: weakref.ref[Any], obj_id: int = obj_id) -> None:
        current = _flag_cache.get(obj_id)
        if current is not None and current[0] is ref:
            del _flag_cache[obj_id]

    try:
        _flag_cache[obj_id] = (weakref.ref(obj, _evict), already)
    except TypeError:
        pass
    return already


def _load_wrapper() -> None:
    """Load the generated wrapper and extract per-interface method names.

    The checked-in SOLIDWORKS 2026 wrapper is the normal path.  SOLIDWORKS keeps
    existing automation interface IIDs and DISPIDs binary compatible between
    releases, so it can bind those interfaces on older supported seats as well.
    ``gencache`` remains only as a compatibility fallback for an installation
    where the vendored artifact cannot be imported.
    """
    global _wrapper_module, _interface_methods

    if not PYWIN32_AVAILABLE:
        return

    try:
        from ._generated import sldworks_2026

        _wrapper_module = sldworks_2026
    except Exception as exc:
        logger.warning(
            "Checked-in SolidWorks wrapper could not be imported; "
            f"falling back to pywin32 gen_py: {exc}"
        )

    # Compatibility only: reuse an existing per-user wrapper.  Probe common
    # versions because the type-library major changes with each SW release.
    for major in (35, 34, 33, 32, 31, 30) if _wrapper_module is None else ():
        try:
            mod = gencache.GetModuleForTypelib(SW_TLB_IID, 0, major, 0)
        except Exception:
            mod = None
        if mod is not None:
            _wrapper_module = mod
            break

    if _wrapper_module is None:
        # Last resort for unusual installations or damaged package artifacts.
        for major in (35, 34, 33, 32, 31, 30):
            try:
                gencache.EnsureModule(SW_TLB_IID, 0, major, 0)
                _wrapper_module = gencache.GetModuleForTypelib(SW_TLB_IID, 0, major, 0)
                if _wrapper_module is not None:
                    break
            except Exception:
                continue

    if _wrapper_module is None:
        logger.warning(
            "SolidWorks generated wrapper not available; method flagging "
            "disabled. Zero-arg SW methods may raise TypeError. To fix, "
            "run: python -m win32com.client.makepy "
            '"C:\\Program Files\\SOLIDWORKS Corp\\SOLIDWORKS\\sldworks.tlb"'
        )
        return

    # Build per-interface method sets by inspecting each DispatchBaseClass
    # subclass in the wrapper module.
    for name in dir(_wrapper_module):
        cls = getattr(_wrapper_module, name, None)
        if not (inspect.isclass(cls) and issubclass(cls, DispatchBaseClass)):
            continue
        method_names: set[str] = set()
        for attr_name, attr in vars(cls).items():
            if attr_name.startswith("_"):
                continue
            if callable(attr):
                method_names.add(attr_name)
        if method_names:
            _interface_methods[name] = frozenset(method_names)

    logger.info(
        f"SolidWorks type info loaded: {len(_interface_methods)} interfaces, "
        f"wrapper={_wrapper_module.__name__}"
    )


def _ensure_loaded() -> None:
    """Lazy-load the wrapper on first use."""
    if _wrapper_module is None and PYWIN32_AVAILABLE:
        _load_wrapper()


def interface_method_names(interface: str) -> frozenset[str]:
    """Return the set of method names declared by the given SW interface.

    Args:
        interface: Interface name as it appears in the type library
            (e.g. ``"ISldWorks"``, ``"IModelDoc2"``).

    Returns:
        Immutable set of method names, or an empty set if the interface is
        unknown or the wrapper isn't loaded.
    """
    _ensure_loaded()
    return _interface_methods.get(interface, frozenset())


# Interface sets most tool operations need to flag. When acquiring a doc
# dispatch, always flag IModelDoc2 (base) plus the subclass that matches the
# doc type. For the app root, flag ISldWorks.
DOC_TYPE_TO_INTERFACES: dict[int, tuple[str, ...]] = {
    # Values match swDocumentTypes_e: 1=Part, 2=Assembly, 3=Drawing
    1: ("IModelDoc2", "IPartDoc"),
    2: ("IModelDoc2", "IAssemblyDoc"),
    3: ("IModelDoc2", "IDrawingDoc"),
}


def flag_methods(obj: Any, *interfaces: str) -> int:
    """Flag SW methods on ``obj`` so pywin32 dispatches them as methods,
    not properties.

    Safe to call repeatedly on the same object — results are cached by
    ``id(obj)``. Unknown method names are silently skipped (those are
    the ones that don't belong to the object's real interface).

    Args:
        obj: A pywin32 ``CDispatch`` wrapping a SolidWorks COM object.
        *interfaces: One or more interface names whose methods to flag.
            Common values: ``"ISldWorks"``, ``"IModelDoc2"``,
            ``"IAssemblyDoc"``, ``"IPartDoc"``, ``"IDrawingDoc"``.

    Returns:
        Number of methods successfully flagged.
    """
    _ensure_loaded()

    if not _interface_methods or obj is None:
        return 0

    already = _cache_entry_for(obj)

    # Only flag methods from interfaces we haven't already processed for
    # this object. Repeats are a no-op; novel interfaces add incrementally.
    new_interfaces = [i for i in interfaces if i not in already]
    if not new_interfaces:
        return 0

    names: set[str] = set()
    for iface in new_interfaces:
        names.update(_interface_methods.get(iface, ()))

    flagged = 0
    for name in names:
        try:
            obj._FlagAsMethod(name)
            flagged += 1
        except Exception:
            # Name not on this dispatch's real interface — skip silently.
            pass

    already.update(new_interfaces)
    return flagged


def flag_method_names(obj: Any, *names: str) -> int:
    """Flag only the named ambiguous zero-argument methods on ``obj``.

    Whole-interface flagging is appropriate for long-lived root objects, but
    prohibitively expensive for transient wrappers returned by drawing and
    feature-tree walks.  This helper performs one ``GetIDsOfNames`` round trip
    per requested name and caches successful or failed attempts per object.

    Args:
        obj: A pywin32 ``CDispatch`` wrapping a SolidWorks COM object.
        *names: Exact method names to pass to ``_FlagAsMethod``.

    Returns:
        Number of names successfully flagged.
    """
    if obj is None:
        return 0
    flag = getattr(obj, "_FlagAsMethod", None)
    if not callable(flag):
        return 0

    already = _cache_entry_for(obj)
    flagged_count = 0
    for name in names:
        cache_key = f"@method:{name}"
        if cache_key in already:
            continue
        try:
            flag(name)
            flagged_count += 1
        except Exception:
            pass
        already.add(cache_key)
    return flagged_count


def flagged(obj: Any, *interfaces: str) -> Any:
    """Flag ``obj``'s methods then return ``obj`` — call-chain friendly.

    Useful for inline flagging of short-lived dispatches::

        config = sw_type_info.flagged(
            model.GetActiveConfiguration(), "IConfiguration"
        )
        name = config.GetName()

    If ``obj`` is ``None`` (e.g. SW returned Nothing), passes through
    unchanged.
    """
    if obj is not None:
        flag_methods(obj, *interfaces)
    return obj


# Cache of fallback subclasses keyed by their makepy base class, so every
# ``early_bound(obj, "IFace2")`` reuses one generated subclass rather than
# minting a new type per call.
_fallback_classes: dict[type, type] = {}


def _fallback_subclass(base: type) -> type:
    """Return a subclass of the makepy interface ``base`` that degrades to
    late binding for any member ``base`` does not declare.

    Why this exists: a makepy interface class exposes ONLY the members the
    type library lists for that one interface, and its ``__getattr__`` /
    ``__setattr__`` raise ``AttributeError`` for anything else. Real SW
    dispatches are polymorphic — a face is an ``IFace2`` AND an ``IEntity``
    (``Select2`` lives on the latter); a part model answers both ``IModelDoc2``
    and ``IPartDoc`` (``GetBodies2`` lives on the latter). Late binding never
    cared (it resolves by name against the live object), so call sites freely
    mix interfaces on one dispatch. A bare makepy wrapper would break those
    off-interface calls.

    The subclass keeps DISPID-fast ``InvokeTypes`` for every DECLARED member
    (normal attribute lookup finds real methods; declared properties go through
    the base ``__getattr__``), and only for an UNDECLARED member does it build
    one lazy ``dynamic.Dispatch`` over the same ``_oleobj_`` and forward. So the
    fast path stays fast and the wrapper is safe to apply to any dispatch,
    regardless of which interfaces a call site later exercises on it.
    """
    cached = _fallback_classes.get(base)
    if cached is not None:
        return cached

    class _EarlyBoundWithFallback(base):  # type: ignore[valid-type, misc]
        def _late_bound(self) -> Any:
            dyn = self.__dict__.get("_late_bound_dispatch")
            if dyn is None:
                from win32com.client import dynamic

                dyn = dynamic.Dispatch(self._oleobj_)
                self.__dict__["_late_bound_dispatch"] = dyn
            return dyn

        def __getattr__(self, attr: str) -> Any:
            # Called only when normal lookup misses (declared methods never
            # reach here). Let the makepy base resolve declared properties;
            # forward the rest to a late-bound dispatch on the same object.
            try:
                return base.__getattr__(self, attr)
            except AttributeError:
                if attr.startswith("__") and attr.endswith("__"):
                    raise
                return getattr(self._late_bound(), attr)

        def __setattr__(self, attr: str, value: Any) -> None:
            try:
                base.__setattr__(self, attr, value)
            except AttributeError:
                setattr(self._late_bound(), attr, value)

    _EarlyBoundWithFallback.__name__ = f"{base.__name__}_EarlyBound"
    _EarlyBoundWithFallback.__qualname__ = _EarlyBoundWithFallback.__name__
    _fallback_classes[base] = _EarlyBoundWithFallback
    return _EarlyBoundWithFallback


def early_bound(obj: Any, interface: str) -> Any:
    """Wrap a late-bound dispatch in its early-bound interface class.

    pywin32 late binding resolves members through SolidWorks's
    ``IDispatch::GetIDsOfNames``. A handful of methods are present in the
    type library (and the vtable) but **absent from that name table**, so a
    by-name call raises ``com_error -2147352573 ('Member not found')`` even
    though the method exists — ``IModelDocExtension::GetMotionStudyManager``
    is the known case. The early-bound wrapper class generated by makepy
    invokes by **dispid** (``InvokeTypes``), which bypasses the name lookup
    and works. It also drops the per-name ``GetIDsOfNames``/``_FlagAsMethod``
    round-trips that ``flag_methods`` needs (~155 ms/object) — the whole
    point of the migration.

    This reuses the already-loaded gen_py wrapper module, so the dispid comes
    from the type library for the connected SW version — nothing is
    hard-coded. The wrapper is constructed from the raw ``_oleobj_`` (passing
    the ``CDispatch`` itself drops the underlying IDispatch and breaks
    ``InvokeTypes``).

    The returned wrapper is a :func:`_fallback_subclass` of the makepy class,
    so a member from a DIFFERENT interface on the same dispatch (``IFace2``'s
    ``Select2`` from ``IEntity``; a part model's ``GetBodies2`` from
    ``IPartDoc``) still resolves — via a lazily-built late-bound dispatch —
    instead of raising ``AttributeError``. That makes early binding safe to
    apply without proving each call site touches only one interface.

    Args:
        obj: A pywin32 ``CDispatch`` wrapping a SolidWorks COM object.
        interface: Interface name as it appears in the type library
            (e.g. ``"IModelDocExtension"``).

    Returns:
        The early-bound wrapper exposing dispid-fast declared members (and
        late-bound off-interface members), or ``obj`` unchanged when the
        wrapper module or interface class is unavailable.
    """
    _ensure_loaded()
    if obj is None or _wrapper_module is None:
        return obj
    cls = getattr(_wrapper_module, interface, None)
    if cls is None or not inspect.isclass(cls):
        # The wrapper IS loaded but the requested interface is absent — a wrong
        # name or an incomplete wrapper. Fail loud rather than silently return an
        # unwrapped dispatch that breaks with a confusing error much later.
        raise ValueError(
            f"early_bound: interface {interface!r} is not defined in the loaded "
            f"SolidWorks wrapper ({getattr(_wrapper_module, '__name__', '?')}). "
            "Check the interface name against the type library, or regenerate the "
            "checked-in wrapper after a SolidWorks version upgrade."
        )
    oleobj = getattr(obj, "_oleobj_", None)
    if oleobj is None:
        # Not a real COM dispatch (a mock/test double) — nothing to wrap.
        return obj
    if isinstance(obj, cls):
        return obj
    try:
        return _fallback_subclass(cls)(oleobj)
    except Exception:
        return obj


def is_early_bound(obj: Any, interface: str) -> bool:
    """Return whether ``obj`` already uses the generated interface wrapper."""
    _ensure_loaded()
    if obj is None or _wrapper_module is None:
        return False
    cls = getattr(_wrapper_module, interface, None)
    return bool(inspect.isclass(cls) and isinstance(obj, cls))


# swSketchSegments_e value -> the derived ``ISketch*`` interface that DECLARES
# the segment's point accessors (``GetStartPoint2``/``GetEndPoint2``/
# ``GetCenterPoint2``/``GetStartPoint``/``GetEndPoint`` …). swSketchTEXT (4) and
# swSketchPARABOLA (5) carry no such accessors and are left as ISketchSegment.
_SKETCH_SEGMENT_INTERFACE: dict[int, str] = {
    0: "ISketchLine",  # swSketchLINE
    1: "ISketchArc",  # swSketchARC (also full circles)
    2: "ISketchEllipse",  # swSketchELLIPSE
    3: "ISketchSpline",  # swSketchSPLINE
}


def concrete_sketch_segment(obj: Any) -> Any:
    """Re-bind a sketch segment from base ``ISketchSegment`` to its derived class.

    makepy wraps ``CreateLine``/``CreateArc``/… results as the *base*
    ``ISketchSegment``, whose generated class does NOT expose the derived point
    accessors (``GetStartPoint2``, ``GetCenterPoint2``, …) — those live on
    ``ISketchLine`` / ``ISketchArc`` / …. ``ISketchSegment.GetType()`` names the
    concrete type (``swSketchSegments_e``), so this re-binds ``obj`` to the
    matching generated interface, where the accessors are declared DISPID
    methods — the pattern the ``swSketchSegments_e`` Remarks prescribe ("obtain
    the appropriate derived class … and call the appropriate derived class
    functions"). Non-segment dispatches (or a session without the wrapper) pass
    through unchanged.

    Args:
        obj: A pywin32 dispatch for a sketch segment (line/arc/circle/spline/
            ellipse), typically the base ``ISketchSegment`` makepy wrapper.

    Returns:
        The segment re-bound to its derived interface, or the base
        ``ISketchSegment`` for the point-less types (``swSketchTEXT`` /
        ``swSketchPARABOLA``). Raises rather than silently returning an
        unusable base wrapper when the segment type cannot be read.
    """
    segment = early_bound(obj, "ISketchSegment")
    if not is_early_bound(segment, "ISketchSegment"):
        return obj  # wrapper module not loaded (mock/degraded) — leave untouched
    seg_type = int(segment.GetType())
    interface = _SKETCH_SEGMENT_INTERFACE.get(seg_type)
    return early_bound(obj, interface) if interface else segment


def early_bound_or_flag(obj: Any, interface: str, *method_names: str) -> Any:
    """Use the generated interface, or selectively flag exact fallback methods."""
    typed = early_bound(obj, interface)
    if typed is obj and not is_early_bound(obj, interface):
        flag_method_names(obj, *method_names)
    return typed


def flag_doc(obj: Any, doc_type: int) -> int:
    """Flag methods for a SolidWorks document dispatch given its type.

    Convenience wrapper around ``flag_methods`` that looks up the correct
    interface list for the document type.

    Args:
        obj: ``CDispatch`` wrapping the document.
        doc_type: Value returned by ``swDoc.GetType()`` — 1=Part, 2=Assembly,
            3=Drawing.

    Returns:
        Number of methods flagged.
    """
    interfaces = DOC_TYPE_TO_INTERFACES.get(doc_type, ("IModelDoc2",))
    return flag_methods(obj, *interfaces)


def invalidate_flag_cache(obj: Any | None = None) -> None:
    """Forget that ``obj`` has been flagged, or clear the cache entirely.

    Address reuse by a *different* object is detected automatically (the
    cache stores a weakref and verifies identity), so this is only needed
    when the same live dispatch must be re-flagged — e.g. after its gen_py
    wrapper state was rebuilt.
    """
    if obj is None:
        _flag_cache.clear()
    else:
        _flag_cache.pop(id(obj), None)
