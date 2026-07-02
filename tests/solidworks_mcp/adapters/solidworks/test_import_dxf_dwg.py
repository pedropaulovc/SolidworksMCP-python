"""Coverage for DXF/DWG import: mock adapter + the live io closure via fakes."""

from __future__ import annotations

import pytest

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    ImportDxfDwgParameters,
)
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.adapters.solidworks import io as io_mod
from solidworks_mcp.adapters.solidworks.io import SolidWorksIOMixin


@pytest.fixture(autouse=True)
def _dispatch_propertyput(monkeypatch):
    """Off-Windows ``pythoncom`` is a stub; give it the one constant the
    indexed-property put needs so the closure runs the real put path."""
    if not hasattr(io_mod.pythoncom, "DISPATCH_PROPERTYPUT"):
        monkeypatch.setattr(
            io_mod.pythoncom, "DISPATCH_PROPERTYPUT", 4, raising=False
        )


@pytest.fixture
def dxf_file(tmp_path):
    """A trivial on-disk file to satisfy the existence precondition."""
    p = tmp_path / "engraving.dxf"
    p.write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n")
    return str(p)


# --- Mock adapter -----------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_import_requires_existing_file():
    adapter = MockSolidWorksAdapter()
    await adapter.connect()
    await adapter.create_part()
    res = await adapter.import_dxf_dwg(
        ImportDxfDwgParameters(file_path="/no/such/file.dxf")
    )
    assert res.status is AdapterResultStatus.ERROR
    assert "not found" in (res.error or "")


@pytest.mark.asyncio
async def test_mock_import_records_feature(dxf_file):
    adapter = MockSolidWorksAdapter()
    await adapter.connect()
    await adapter.create_part()
    res = await adapter.import_dxf_dwg(
        ImportDxfDwgParameters(file_path=dxf_file, plane="Front", scale=0.3)
    )
    assert res.status is AdapterResultStatus.SUCCESS
    assert res.data.type == "ImportedDxfDwg"
    assert res.data.parameters["file_path"] == dxf_file
    assert res.data.parameters["scale"] == 0.3


# --- Live io.py closure, exercised through fakes (no SolidWorks) -------------

class _FakePlane:
    def __init__(self):
        self.selected = False

    def Select2(self, _append, _mark):
        self.selected = True
        return True


class _FakeOleObj:
    """Records DISPATCH_PROPERTYPUT Invoke calls the way pywin32 would route them."""

    def __init__(self, sink):
        self._sink = sink

    def GetIDsOfNames(self, _lcid, name):
        return {"ImportMethod": 1, "LengthUnit": 2, "ImportHatch": 3,
                "ImportDimensions": 4, "AddSketchConstraints": 5}[name]

    def Invoke(self, dispid, _lcid, _flags, _want, sheet, value):
        self._sink[dispid] = (sheet, value)


class _FakeImportData:
    def __init__(self):
        self.puts: dict = {}
        self.methods: list = []
        self._oleobj_ = _FakeOleObj(self.puts)

    def SetPosition(self, sheet, positioning, x, y):
        self.methods.append(("SetPosition", sheet, positioning, x, y))
        return True

    def SetSheetScale(self, sheet, num, den):
        self.methods.append(("SetSheetScale", sheet, num, den))
        return True

    def SetMergePoints(self, sheet, merge, dist):
        self.methods.append(("SetMergePoints", sheet, merge, dist))
        return True


class _FakeFeature:
    Name = "DXF1"

    def GetSpecificFeature2(self):
        return object()


class _FakeFeatureManager:
    def __init__(self, sink):
        self._sink = sink

    def InsertDwgOrDxfFile2(self, filename, import_data):
        self._sink.append((filename, import_data))
        return _FakeFeature()


class _FakeExtension:
    def SelectByID2(self, *_a):
        return False


class _FakeModel:
    def __init__(self, sink):
        self._plane = _FakePlane()
        self.FeatureManager = _FakeFeatureManager(sink)
        self.Extension = _FakeExtension()
        self.cleared = False

    def FeatureByName(self, _name):
        return self._plane

    def ClearSelection2(self, _flag):
        self.cleared = True


class _FakeApp:
    def __init__(self, import_data):
        self._import_data = import_data

    def GetImportFileData(self, _path):
        return self._import_data


class _FakeAdapter(SolidWorksIOMixin):
    """Drives the real io.import_dxf_dwg closure with fakes for the COM objects."""

    def __init__(self, dxf_file):
        self.inserted: list = []
        self.import_data = _FakeImportData()
        self.currentModel = _FakeModel(self.inserted)
        self.swApp = _FakeApp(self.import_data)

    def _handle_com_operation(self, _name, callback):
        try:
            return AdapterResult(status=AdapterResultStatus.SUCCESS, data=callback())
        except Exception as exc:  # pragma: no cover
            return AdapterResult(status=AdapterResultStatus.ERROR, error=str(exc))

    def _attempt(self, callback, default=None):
        try:
            return callback()
        except Exception:
            return default


@pytest.mark.asyncio
async def test_live_closure_configures_and_inserts(dxf_file):
    adapter = _FakeAdapter(dxf_file)
    res = await adapter.import_dxf_dwg(
        ImportDxfDwgParameters(
            file_path=dxf_file, plane="Front", scale=0.3, position=[50.0, 27.5]
        )
    )
    assert res.status is AdapterResultStatus.SUCCESS
    assert res.data.type == "ImportedDxfDwg"
    # The plane was selected and the file inserted through the FeatureManager.
    assert adapter.inserted and adapter.inserted[0][0] == dxf_file
    assert adapter.currentModel.cleared is True
    # ImportMethod=4 (existing part) and LengthUnit=0 (mm) put on the import data.
    data = adapter.import_data
    assert data.puts[1] == ("", 4)  # ImportMethod
    assert data.puts[2] == ("", 0)  # LengthUnit
    # Position (metres) + scale set through the method calls.
    assert ("SetPosition", "", 2, 0.05, 0.0275) in data.methods
    assert ("SetSheetScale", "", 0.3, 1.0) in data.methods


@pytest.mark.asyncio
async def test_live_closure_missing_file_errors(tmp_path):
    adapter = _FakeAdapter(str(tmp_path / "x.dxf"))
    res = await adapter.import_dxf_dwg(
        ImportDxfDwgParameters(file_path=str(tmp_path / "missing.dxf"))
    )
    assert res.status is AdapterResultStatus.ERROR
    assert "not found" in (res.error or "")
