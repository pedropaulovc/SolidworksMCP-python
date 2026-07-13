"""Dispatch-cost contracts for project-agnostic drawing helpers."""

from __future__ import annotations

from types import SimpleNamespace

from solidworks_mcp.adapters.solidworks import drawing


class _Adapter:
    def __init__(self, model):
        self.currentModel = model

    @staticmethod
    def _attempt(callback, default=None):
        try:
            return callback()
        except Exception:
            return default

    @staticmethod
    def _get_attr_or_call(obj, name):
        member = getattr(obj, name, None)
        return member() if callable(member) else member


def test_iter_views_handles_property_and_method_dispatch_without_flagging(monkeypatch):
    """Fresh IView wrappers use selective rather than whole-interface flagging."""

    def _unexpected_flag(*_args, **_kwargs):
        raise AssertionError("iter_views must not flag transient view dispatches")

    monkeypatch.setattr(drawing._sw_type_info, "flagged", _unexpected_flag)

    second = SimpleNamespace(GetNextView=None)
    first = SimpleNamespace(GetNextView=lambda: second)
    sheet = SimpleNamespace(GetNextView=first)
    model = SimpleNamespace(GetFirstView=lambda: sheet)

    assert list(drawing.iter_views(_Adapter(model))) == [first, second]
