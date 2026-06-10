"""Direct branch coverage tests for adapters.solidworks.manufacturing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    AddThreadParameters,
    ApplyMaterialParameters,
    CreateBomParameters,
)
from solidworks_mcp.adapters.solidworks import manufacturing as manufacturing_module


class _FakeAdapter:
    def __init__(self) -> None:
        self.currentModel = None

    def _handle_com_operation(self, _name, callback):
        try:
            return AdapterResult(status=AdapterResultStatus.SUCCESS, data=callback())
        except Exception as exc:
            return AdapterResult(status=AdapterResultStatus.ERROR, error=str(exc))

    def _attempt(self, callback, default=None):
        try:
            return callback()
        except Exception:
            return default


def _config_manager(active="Default"):
    return SimpleNamespace(ActiveConfiguration=SimpleNamespace(Name=active))


# ---------------------------------------------------------------------------
# apply_material
# ---------------------------------------------------------------------------


class _MaterialModel:
    def __init__(self, applied_name="Plain Carbon Steel") -> None:
        self.applied_name = applied_name
        self.set_calls: list[tuple] = []
        self.rebuilds = 0
        self.ConfigurationManager = _config_manager()

    def SetMaterialPropertyName2(self, config, database, material):  # noqa: N802
        self.set_calls.append((config, database, material))

    @property
    def MaterialIdName(self):  # noqa: N802
        return f"SOLIDWORKS Materials|{self.applied_name}"

    def EditRebuild3(self):  # noqa: N802
        self.rebuilds += 1
        return True


def test_apply_material_no_model_errors() -> None:
    adapter = _FakeAdapter()
    result = manufacturing_module._apply_material_impl(
        adapter, ApplyMaterialParameters(material="Brass")
    )
    assert result.is_error
    assert "No active model" in (result.error or "")


def test_apply_material_empty_name_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = _MaterialModel()
    result = manufacturing_module._apply_material_impl(
        adapter, ApplyMaterialParameters(material="   ")
    )
    assert result.is_error
    assert "Material name is required" in (result.error or "")


def test_apply_material_success_resolves_active_configuration() -> None:
    adapter = _FakeAdapter()
    model = _MaterialModel()
    adapter.currentModel = model

    result = manufacturing_module._apply_material_impl(
        adapter, ApplyMaterialParameters(material="Plain Carbon Steel")
    )

    assert result.is_success
    assert model.set_calls == [("Default", "", "Plain Carbon Steel")]
    assert model.rebuilds == 1
    assert result.data == {
        "material": "Plain Carbon Steel",
        "configuration": "Default",
    }


def test_apply_material_explicit_configuration_passed_through() -> None:
    adapter = _FakeAdapter()
    model = _MaterialModel()
    adapter.currentModel = model

    result = manufacturing_module._apply_material_impl(
        adapter,
        ApplyMaterialParameters(material="Plain Carbon Steel", configuration="T24"),
    )

    assert result.is_success
    assert model.set_calls[0][0] == "T24"


def test_apply_material_readback_mismatch_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = _MaterialModel(applied_name="Brass")

    result = manufacturing_module._apply_material_impl(
        adapter, ApplyMaterialParameters(material="Unobtainium")
    )

    assert result.is_error
    assert "was not applied" in (result.error or "")


# ---------------------------------------------------------------------------
# add_thread
# ---------------------------------------------------------------------------


def _thread_model(feature, select_result=True):
    selections: list[tuple] = []
    calls: list[tuple] = []

    def _select(name, entity_type, x, y, z, append, mark, callout, option):
        selections.append((name, entity_type, x, y, z))
        return select_result

    def _insert(standard, standard_type, size, diameter, end_type, depth, note):
        calls.append((standard, standard_type, size, diameter, end_type, depth, note))
        return feature

    model = SimpleNamespace(
        ClearSelection2=lambda flag: True,
        Extension=SimpleNamespace(SelectByID2=_select),
        FeatureManager=SimpleNamespace(InsertCosmeticThread3=_insert),
    )
    return model, selections, calls


def test_add_thread_no_model_errors() -> None:
    adapter = _FakeAdapter()
    result = manufacturing_module._add_thread_impl(
        adapter, AddThreadParameters(edge_point=[0, 0, 0])
    )
    assert result.is_error
    assert "No active model" in (result.error or "")


def test_add_thread_unknown_standard_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = SimpleNamespace()
    result = manufacturing_module._add_thread_impl(
        adapter, AddThreadParameters(edge_point=[0, 0, 0], standard="whitworth")
    )
    assert result.is_error
    assert "Unknown thread standard" in (result.error or "")


def test_add_thread_unknown_end_type_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = SimpleNamespace()
    result = manufacturing_module._add_thread_impl(
        adapter, AddThreadParameters(edge_point=[0, 0, 0], end_type="bottomless")
    )
    assert result.is_error
    assert "Unknown thread end_type" in (result.error or "")


def test_add_thread_success_converts_units() -> None:
    adapter = _FakeAdapter()
    feature = SimpleNamespace(Name="Cosmetic Thread1")
    adapter.currentModel, selections, calls = _thread_model(feature)

    result = manufacturing_module._add_thread_impl(
        adapter,
        AddThreadParameters(
            edge_point=[25, 0, 100],
            standard="ansi_inch",
            size="1/4-20",
            diameter=6.35,
            end_type="blind",
            depth=12.0,
        ),
    )

    assert result.is_success
    # Edge point reaches SelectByID2 in metres
    assert selections == [("", "EDGE", 0.025, 0.0, 0.1)]
    # ansi_inch=0, blind=0; diameter/depth reach the API in metres
    assert calls == [(0, "", "1/4-20", 0.00635, 0, 0.012, "")]
    assert result.data == {
        "name": "Cosmetic Thread1",
        "standard": "ansi_inch",
        "size": "1/4-20",
    }


def test_add_thread_selection_failure_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel, _, _ = _thread_model(
        SimpleNamespace(Name="x"), select_result=False
    )

    result = manufacturing_module._add_thread_impl(
        adapter, AddThreadParameters(edge_point=[99, 99, 99])
    )

    assert result.is_error
    assert "Failed to select a circular EDGE" in (result.error or "")


def test_add_thread_null_feature_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel, _, _ = _thread_model(None)

    result = manufacturing_module._add_thread_impl(
        adapter, AddThreadParameters(edge_point=[0, 0, 0])
    )

    assert result.is_error
    assert "Failed to create cosmetic thread" in (result.error or "")


# ---------------------------------------------------------------------------
# create_bom / export_bom_csv
# ---------------------------------------------------------------------------


class _FakeBomTable:
    RowCount = 3
    ColumnCount = 2

    def DisplayedText(self, row, column):  # noqa: N802
        return f"r{row}c{column}"


def _bom_model(table):
    calls: list[tuple] = []

    def _insert(template, x, y, bom_type, configuration, hidden, indent, cut, dissolve):
        calls.append((template, x, y, bom_type, configuration, hidden))
        return table

    model = SimpleNamespace(
        Extension=SimpleNamespace(InsertBomTable4=_insert),
        ConfigurationManager=_config_manager(),
    )
    return model, calls


def test_create_bom_no_model_errors() -> None:
    adapter = _FakeAdapter()
    result = manufacturing_module._create_bom_impl(adapter, CreateBomParameters())
    assert result.is_error
    assert "No active model" in (result.error or "")


def test_create_bom_unknown_type_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = SimpleNamespace()
    result = manufacturing_module._create_bom_impl(
        adapter, CreateBomParameters(bom_type="exploded")
    )
    assert result.is_error
    assert "Unknown bom_type" in (result.error or "")


def test_create_bom_success_reads_table() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel, calls = _bom_model(_FakeBomTable())

    result = manufacturing_module._create_bom_impl(
        adapter, CreateBomParameters(template="X:/custom.sldbomtbt")
    )

    assert result.is_success
    # parts_only=1, configuration resolved explicitly (no implicit default)
    assert calls == [("X:/custom.sldbomtbt", 0, 0, 1, "Default", False)]
    assert result.data["rows"] == 3
    assert result.data["columns"] == 2
    assert result.data["header"] == ["r0c0", "r0c1"]
    assert result.data["data"] == [["r1c0", "r1c1"], ["r2c0", "r2c1"]]
    assert result.data["configuration"] == "Default"
    assert result.data["bom_type"] == "parts_only"


def test_create_bom_null_table_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel, _ = _bom_model(None)

    result = manufacturing_module._create_bom_impl(
        adapter, CreateBomParameters(template="X:/custom.sldbomtbt")
    )

    assert result.is_error
    assert "Failed to insert BOM table" in (result.error or "")


def test_default_bom_template_raises_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(manufacturing_module.glob, "glob", lambda pattern: [])
    with pytest.raises(Exception, match="No BOM table template found"):
        manufacturing_module._default_bom_template(_FakeAdapter())


def test_default_bom_template_returns_last_glob_match(monkeypatch) -> None:
    monkeypatch.setattr(
        manufacturing_module.glob,
        "glob",
        lambda pattern: (
            ["a.sldbomtbt", "b.sldbomtbt"] if "SOLIDWORKS\\lang" in pattern else []
        ),
    )
    assert manufacturing_module._default_bom_template(_FakeAdapter()) == "b.sldbomtbt"


def test_default_bom_template_derives_from_executable(tmp_path) -> None:
    """The running instance's exe dir is preferred over the install globs."""
    exe = tmp_path / "SOLIDWORKS" / "sldworks.exe"
    template = tmp_path / "SOLIDWORKS" / "lang" / "english" / "bom-standard.sldbomtbt"
    template.parent.mkdir(parents=True)
    template.write_text("", encoding="utf-8")
    exe.write_text("", encoding="utf-8")

    adapter = _FakeAdapter()
    adapter.swApp = SimpleNamespace(GetExecutablePath=lambda: str(exe))

    assert manufacturing_module._default_bom_template(adapter) == str(template)


def test_export_bom_csv_requires_file_path() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = SimpleNamespace()
    result = manufacturing_module._export_bom_csv_impl(adapter, CreateBomParameters())
    assert result.is_error
    assert "file_path is required" in (result.error or "")


def test_export_bom_csv_writes_file(tmp_path) -> None:
    adapter = _FakeAdapter()
    adapter.currentModel, _ = _bom_model(_FakeBomTable())
    out = tmp_path / "nested" / "bom.csv"

    result = manufacturing_module._export_bom_csv_impl(
        adapter,
        CreateBomParameters(template="X:/custom.sldbomtbt", file_path=str(out)),
    )

    assert result.is_success
    assert result.data["rows"] == 3
    assert result.data["configuration"] == "Default"
    content = out.read_text(encoding="utf-8").strip().splitlines()
    assert content[0] == "r0c0,r0c1"
    assert content[1] == "r1c0,r1c1"
    assert content[2] == "r2c0,r2c1"
