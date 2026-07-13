from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[3] / "scripts" / "generate_solidworks_stubs.py"
SPEC = importlib.util.spec_from_file_location("generate_solidworks_stubs", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


MAKEPY_SAMPLE = '''
class IView(DispatchBaseClass):
    def GetNextView(self):
        return self._oleobj_.InvokeTypes(2, 0, 1, (9, 0), ())
    def ScaleDecimal(self, Value=defaultNamedNotOptArg):
        return None
    _prop_map_get_ = {"Name": (1, 2, (8, 0), ())}
    _prop_map_put_ = {"Name": ((1, 0, 4, 0), ())}
'''


def test_generate_stub_preserves_members_and_call_shape() -> None:
    result = MODULE.generate_stub(MAKEPY_SAMPLE, ["IView"])

    assert "class IView(Protocol):" in result
    assert "    Name: Any" in result
    assert "    def GetNextView(self) -> Any: ..." in result
    assert "    def ScaleDecimal(self, Value: Any = ...) -> Any: ..." in result


def test_generate_stub_fails_if_requested_interface_is_missing() -> None:
    with pytest.raises(ValueError, match="ISldWorks"):
        MODULE.generate_stub(MAKEPY_SAMPLE, ["ISldWorks"])
