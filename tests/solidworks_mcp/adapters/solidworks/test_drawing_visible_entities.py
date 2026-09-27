"""Visible-entity fetches must not wrap elements the caller never uses."""

from types import SimpleNamespace

import pytest

from solidworks_mcp.adapters import sw_type_info
from solidworks_mcp.adapters.solidworks import drawing

pythoncom = pytest.importorskip("pythoncom")


class _RawElement:
    """A bare PyIDispatch stand-in: answers InvokeTypes, has no ``_oleobj_``."""

    def __init__(self, tag):
        self.tag = tag

    def InvokeTypes(self, *args):  # noqa: N802 - COM spelling
        raise AssertionError("elements are only bound, never invoked, here")


class _ViewOleobj:
    def __init__(self, elements):
        self.elements = elements
        self.calls = []

    def GetIDsOfNames(self, name):  # noqa: N802 - COM spelling
        self.calls.append(("ids", name))
        return 427

    def InvokeTypes(self, dispid, lcid, flags, result_type, arg_types, *args):  # noqa: N802
        self.calls.append(("invoke", dispid, flags, result_type, arg_types, args))
        return self.elements


def _view(elements):
    return SimpleNamespace(_oleobj_=_ViewOleobj(elements))


@pytest.fixture
def bindable(monkeypatch):
    """Treat the fake view as already-bound; bind entities to a recording class."""
    bound = []

    def early_bound(obj, interface):
        if interface == "IView":
            return obj
        bound.append((interface, obj._oleobj_))
        return SimpleNamespace(interface=interface, _oleobj_=obj._oleobj_)

    monkeypatch.setattr(sw_type_info, "early_bound", early_bound)
    return bound


def test_raw_fetch_invokes_by_live_dispid_and_binds_nothing(bindable):
    elements = (_RawElement("a"), _RawElement("b"))
    view = _view(elements)
    component = SimpleNamespace(_oleobj_="component-dispatch")

    fetched = drawing.raw_visible_entities(view, component, 1)

    assert fetched == elements
    assert bindable == []
    (ids, invoke) = view._oleobj_.calls
    assert ids == ("ids", "GetVisibleEntities2")
    _tag, dispid, flags, result_type, arg_types, args = invoke
    assert dispid == 427
    assert flags == pythoncom.DISPATCH_METHOD
    assert result_type == (pythoncom.VT_VARIANT, 0)
    assert arg_types == ((pythoncom.VT_DISPATCH, 1), (pythoncom.VT_I4, 1))
    assert args == ("component-dispatch", 1)


def test_empty_result_is_an_empty_tuple(bindable):
    assert drawing.raw_visible_entities(_view(None), SimpleNamespace(), 1) == ()


@pytest.mark.parametrize(
    ("kind", "interface"),
    [(1, "IEdge"), (2, "IVertex"), (3, "IFace2"), (4, "ISilhouetteEdge")],
)
def test_each_kind_binds_to_its_declaring_interface(bindable, kind, interface):
    raw = _RawElement("x")

    entity = drawing.bind_view_entity(raw, kind)

    assert entity.interface == interface
    assert entity._oleobj_ is raw


def test_wrapped_objects_and_doubles_pass_through(bindable):
    wrapped = SimpleNamespace(_oleobj_=object())
    double = object()

    assert drawing.bind_view_entity(wrapped, 1) is wrapped
    assert drawing.bind_view_entity(double, 1) is double
    assert bindable == []


def test_component_entities_binds_every_element_in_order(bindable):
    elements = (_RawElement("a"), _RawElement("b"), _RawElement("c"))

    entities = drawing.visible_component_entities(_view(elements), SimpleNamespace(), 3)

    assert [e._oleobj_ for e in entities] == list(elements)
    assert {e.interface for e in entities} == {"IFace2"}


def test_view_double_without_oleobj_is_called_directly(bindable):
    edges = ["e1", "e2"]
    view = SimpleNamespace(GetVisibleEntities2=lambda component, kind: edges)

    assert drawing.visible_component_entities(view, "c", 1) == edges
