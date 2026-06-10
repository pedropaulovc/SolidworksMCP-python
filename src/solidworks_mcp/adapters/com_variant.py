"""COM VARIANT marshalling helpers for pywin32 late binding.

Late-bound SolidWorks calls take their arguments as VARIANTs. A few argument
types do not round-trip from plain Python values and need an explicit VARIANT
wrapper, or the call fails at the COM boundary. This module centralises those
conversions so every call site marshals them the same way.

All helpers import ``pywin32`` lazily and degrade to a benign value when it is
unavailable (e.g. Linux CI running the mock suite), so importing this module is
safe on every platform.
"""

from __future__ import annotations

from typing import Any


def null_dispatch() -> Any:
    """Return a typed-null object pointer for optional ``IDispatch`` params.

    Under pywin32 late binding a bare Python ``None`` marshals as ``VT_NULL``,
    which SolidWorks rejects with ``com_error (-2147352571, 'Type mismatch')``.
    A ``VT_DISPATCH`` null VARIANT supplies the null-object-pointer type the
    API expects. Used for ``SelectByID2``'s ``Callout`` (see
    :func:`null_callout`) and ``IModelDocExtension::SaveAs2``'s ``ExportData``.

    Returns:
        Any: ``VARIANT(VT_DISPATCH, None)`` on Windows with pywin32 available;
        plain ``None`` as a fallback otherwise (mock adapters and CI never
        reach a real COM boundary, so the value is inert there).
    """
    try:
        import pythoncom
        from win32com.client import VARIANT

        return VARIANT(pythoncom.VT_DISPATCH, None)
    except Exception:
        return None


def null_callout() -> Any:
    """Return a typed-null ``Callout`` argument for ``SelectByID2``.

    ``IModelDocExtension::SelectByID2`` (and the ``IModelDoc2`` variant) take an
    optional ``Callout`` parameter typed as an ``ICallout`` object pointer.
    The failure mode of passing a bare ``None`` was long misattributed to
    "``SelectByID2`` is broken on this build" — see :func:`null_dispatch`.

    Returns:
        Any: See :func:`null_dispatch`.
    """
    return null_dispatch()


def byref_long() -> Any:
    """Return an in/out ``long`` VARIANT for required by-reference params.

    SolidWorks methods such as ``IModelDocExtension::SaveAs2``/``SaveAs3``
    take required ``VT_BYREF | VT_I4`` ``Errors``/``Warnings`` parameters.
    Under late binding these cannot be omitted (``DISP_E_BADPARAMCOUNT``) nor
    passed as bare ``None`` (``VT_NULL`` type mismatch). After the call the
    out-value is readable via ``.value``.

    Returns:
        Any: ``VARIANT(VT_BYREF | VT_I4, 0)`` on Windows with pywin32
        available; plain ``None`` as a fallback otherwise (CI never reaches a
        real COM boundary).
    """
    try:
        import pythoncom
        from win32com.client import VARIANT

        return VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    except Exception:
        return None


def bstr_array(values: list[str]) -> Any:
    """Return an array-of-strings VARIANT for ``string[]`` SAFEARRAY params.

    SolidWorks methods such as ``IEquationMgr::Add3`` take configuration-name
    lists typed as ``System.object`` holding a string array. Under late
    binding a bare Python list unpacks into N positional VARIANTs
    (``DISP_E_BADPARAMCOUNT``), so the list must be wrapped in a
    ``VT_ARRAY | VT_BSTR`` VARIANT.

    Args:
        values: The strings to marshal.

    Returns:
        Any: ``VARIANT(VT_ARRAY | VT_BSTR, values)`` on Windows with pywin32
        available; the plain list as a fallback otherwise (CI never reaches a
        real COM boundary).
    """
    try:
        import pythoncom
        from win32com.client import VARIANT

        return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, values)
    except Exception:
        return values


def empty_double_array() -> Any:
    """Return an empty array-of-doubles VARIANT for unused SAFEARRAY params.

    Some SolidWorks methods take an optional ``double[]`` (e.g. the ``Radii``
    argument of ``IModelDoc2::FeatureFillet3``, unused when the radius count is
    zero). Under late binding the correct typed-absent value is an empty
    ``VT_ARRAY | VT_R8`` VARIANT, not a bare ``None`` (which would marshal as
    ``VT_NULL`` — the same class of failure as :func:`null_callout`).

    Returns:
        Any: ``VARIANT(VT_ARRAY | VT_R8, [])`` on Windows with pywin32
        available; plain ``None`` as a fallback otherwise (CI never reaches a
        real COM boundary).
    """
    try:
        import pythoncom
        from win32com.client import VARIANT

        return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [])
    except Exception:
        return None
