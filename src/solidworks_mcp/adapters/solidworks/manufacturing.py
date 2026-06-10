"""Manufacturing mixin for PyWin32 SolidWorks operations (Phase 5).

Implements material assignment (``IPartDoc::SetMaterialPropertyName2``),
cosmetic threads (``IFeatureManager::InsertCosmeticThread3``) and BOM
tables (``IModelDocExtension::InsertBomTable4`` read through
``ITableAnnotation``), including CSV export of BOM contents.
"""

from __future__ import annotations

import csv
import glob
from pathlib import Path
from typing import Any, cast

from ..base import (
    AdapterResult,
    AdapterResultStatus,
    AddThreadParameters,
    ApplyMaterialParameters,
    CreateBomParameters,
)
from .features import _flag_feature_methods, _read_member, _select_by_point
from .parametrics import _active_configuration_name

# swCosmeticStandardType_e
_THREAD_STANDARDS = {
    "none": -2,
    "ansi_inch": 0,
    "ansi_metric": 1,
    "bsi": 2,
    "din": 4,
    "helicoil_inch": 6,
    "helicoil_metric": 7,
    "iso": 8,
    "jis": 9,
}

# swCosmeticEndConditions_e
_THREAD_END_TYPES = {
    "blind": 0,
    "blind_upto_next": 1,
    "through": 2,
    "blind_2dia": 3,
}

# swBomType_e
_BOM_TYPES = {
    "parts_only": 1,
    "top_level": 2,
    "indented": 3,
    "flattened": 4,
}

# Fallback install locations of the standard BOM table template (classic
# and 3DEXPERIENCE editions). The primary lookup derives the path from the
# running instance's executable instead.
_BOM_TEMPLATE_GLOBS = [
    r"C:\Program Files\SOLIDWORKS*\SOLIDWORKS\lang\english\bom-standard.sldbomtbt",
    r"C:\Program Files\SOLIDWORKS*\lang\english\bom-standard.sldbomtbt",
    r"C:\Program Files\Dassault Systemes\SOLIDWORKS*\SOLIDWORKS\lang\english"
    r"\bom-standard.sldbomtbt",
]


class SolidWorksManufacturingMixin:
    """Expose SolidWorks manufacturing-prep methods via mixin-local helpers."""

    async def apply_material(
        self, params: ApplyMaterialParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _apply_material_impl(self, params)

    async def add_thread(
        self, params: AddThreadParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _add_thread_impl(self, params)

    async def create_bom(
        self, params: CreateBomParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _create_bom_impl(self, params)

    async def export_bom_csv(
        self, params: CreateBomParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _export_bom_csv_impl(self, params)


def _apply_material_impl(
    adapter: Any, params: ApplyMaterialParameters
) -> AdapterResult[dict[str, Any]]:
    """Assign a material via ``IPartDoc::SetMaterialPropertyName2``.

    The active part document exposes the ``IPartDoc`` interface on the same
    dispatch as ``IModelDoc2``. ``SetMaterialPropertyName2`` returns nothing,
    so the assignment is verified by reading ``MaterialIdName`` back; a
    rebuild follows so mass properties reflect the new density.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Material name, database and configuration scope.

    Returns:
        AdapterResult[dict[str, Any]]: Applied material/configuration or
        error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not params.material.strip():
        return AdapterResult(
            status=AdapterResultStatus.ERROR, error="Material name is required"
        )

    def _material_operation() -> dict[str, Any]:
        model = adapter.currentModel
        configuration = params.configuration or _active_configuration_name(adapter)
        _flag_feature_methods(model, "IPartDoc")
        model.SetMaterialPropertyName2(configuration, params.database, params.material)

        applied = str(_read_member(model, "MaterialIdName") or "")
        if params.material not in applied:
            raise Exception(
                f"Material {params.material!r} was not applied (model reports "
                f"{applied!r}) — check the material exists in the database"
            )
        adapter._attempt(lambda: model.EditRebuild3())
        return {"material": params.material, "configuration": configuration}

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("apply_material", _material_operation),
    )


def _add_thread_impl(
    adapter: Any, params: AddThreadParameters
) -> AdapterResult[dict[str, Any]]:
    """Add a cosmetic thread via ``IFeatureManager::InsertCosmeticThread3``.

    The target circular edge is selected by a point on it (subject to the
    view-dependent picking caveat on :func:`_select_by_point`). Lengths are
    converted from millimetres to metres for the API.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Edge location and thread specification.

    Returns:
        AdapterResult[dict[str, Any]]: Thread feature name/spec or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    standard = _THREAD_STANDARDS.get(params.standard)
    if standard is None:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error=f"Unknown thread standard: {params.standard!r} "
            f"(expected one of {sorted(_THREAD_STANDARDS)})",
        )
    end_type = _THREAD_END_TYPES.get(params.end_type)
    if end_type is None:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error=f"Unknown thread end_type: {params.end_type!r} "
            f"(expected one of {sorted(_THREAD_END_TYPES)})",
        )

    def _thread_operation() -> dict[str, Any]:
        adapter._attempt(lambda: adapter.currentModel.ClearSelection2(True))
        if not _select_by_point(adapter, "EDGE", params.edge_point, 0, False):
            raise Exception(f"Failed to select a circular EDGE at {params.edge_point}")

        feature_manager = adapter.currentModel.FeatureManager
        _flag_feature_methods(feature_manager, "IFeatureManager")
        feature = feature_manager.InsertCosmeticThread3(
            standard,
            params.standard_type,
            params.size,
            params.diameter / 1000.0,
            end_type,
            params.depth / 1000.0,
            params.note,
        )
        if feature is None:
            raise Exception(
                "Failed to create cosmetic thread (the selected edge must be "
                "circular and the size valid for the standard)"
            )
        name = str(_read_member(feature, "Name") or "")
        return {"name": name, "standard": params.standard, "size": params.size}

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("add_thread", _thread_operation),
    )


def _default_bom_template(adapter: Any) -> str:
    """Locate the installed ``bom-standard.sldbomtbt`` template.

    Primary lookup: ``<sldworks.exe dir>/lang/english/`` of the running
    instance (``ISldWorks::GetExecutablePath``), which is install-layout
    agnostic. Falls back to globbing the known classic / 3DEXPERIENCE
    install locations.

    Args:
        adapter: Connected adapter (for the application dispatch).

    Returns:
        str: Template path.

    Raises:
        Exception: When no installed template is found.
    """
    exe = adapter._attempt(lambda: adapter.swApp.GetExecutablePath(), default=None)
    if exe:
        candidate = (
            Path(str(exe)).parent / "lang" / "english" / "bom-standard.sldbomtbt"
        )
        if candidate.is_file():
            return str(candidate)
    for pattern in _BOM_TEMPLATE_GLOBS:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]
    raise Exception(
        "No BOM table template found under the SolidWorks install folder — "
        "pass an explicit .sldbomtbt template path"
    )


def _read_bom_table(adapter: Any, table: Any) -> dict[str, Any]:
    """Read a BOM table annotation's full contents.

    Args:
        adapter: Connected adapter (for ``_attempt``).
        table: The ``IBomTableAnnotation``/``ITableAnnotation`` dispatch.

    Returns:
        dict[str, Any]: ``rows``/``columns`` counts, ``header`` row and
        ``data`` rows (header excluded) as displayed text.
    """
    _flag_feature_methods(table, "ITableAnnotation")
    row_count = int(_read_member(table, "RowCount") or 0)
    column_count = int(_read_member(table, "ColumnCount") or 0)

    def _cell(row: int, column: int) -> str:
        value = adapter._attempt(lambda: table.DisplayedText(row, column), default=None)
        if value is None:
            value = adapter._attempt(lambda: table.Text(row, column), default="")
        return str(value or "")

    grid = [
        [_cell(row, column) for column in range(column_count)]
        for row in range(row_count)
    ]
    header = grid[0] if grid else []
    return {
        "rows": row_count,
        "columns": column_count,
        "header": header,
        "data": grid[1:],
    }


def _insert_bom(adapter: Any, params: CreateBomParameters) -> dict[str, Any]:
    """Insert a BOM table and return its contents.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        params: BOM type, configuration and template.

    Returns:
        dict[str, Any]: Table contents per :func:`_read_bom_table` plus the
        resolved ``configuration`` and ``bom_type``.

    Raises:
        Exception: When the BOM cannot be created.
    """
    bom_type = _BOM_TYPES[params.bom_type]
    template = params.template or _default_bom_template(adapter)
    # SolidWorks does NOT default to the active configuration on an empty
    # string (per the API remarks), so it is resolved explicitly.
    configuration = params.configuration or _active_configuration_name(adapter)

    extension = adapter.currentModel.Extension
    _flag_feature_methods(extension, "IModelDocExtension")
    table = extension.InsertBomTable4(
        template,
        0,  # X placement
        0,  # Y placement
        bom_type,
        configuration,
        False,  # Hidden — keep visible so the feature is inspectable
        0,  # IndentedNumberingType — only used for indented BOMs
        False,  # DetailedCutList
        False,  # DissolvePartLevelRows
    )
    if table is None:
        raise Exception(
            f"Failed to insert BOM table (type {params.bom_type!r}, "
            f"configuration {configuration!r}, template {template!r})"
        )
    contents = _read_bom_table(adapter, table)
    contents["configuration"] = configuration
    contents["bom_type"] = params.bom_type
    return contents


def _create_bom_impl(
    adapter: Any, params: CreateBomParameters
) -> AdapterResult[dict[str, Any]]:
    """Insert a BOM table via ``IModelDocExtension::InsertBomTable4``.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: BOM type, configuration and template.

    Returns:
        AdapterResult[dict[str, Any]]: Table contents or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if params.bom_type not in _BOM_TYPES:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error=f"Unknown bom_type: {params.bom_type!r} "
            f"(expected one of {sorted(_BOM_TYPES)})",
        )

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation(
            "create_bom", lambda: _insert_bom(adapter, params)
        ),
    )


def _export_bom_csv_impl(
    adapter: Any, params: CreateBomParameters
) -> AdapterResult[dict[str, Any]]:
    """Insert a BOM table and write its contents to a CSV file.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: BOM options; ``file_path`` is the CSV destination.

    Returns:
        AdapterResult[dict[str, Any]]: Export summary (path, row/column
        counts) or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if params.bom_type not in _BOM_TYPES:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error=f"Unknown bom_type: {params.bom_type!r} "
            f"(expected one of {sorted(_BOM_TYPES)})",
        )
    if not params.file_path.strip():
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="file_path is required for export_bom_csv",
        )

    def _export_operation() -> dict[str, Any]:
        contents = _insert_bom(adapter, params)
        path = Path(params.file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(contents["header"])
            writer.writerows(contents["data"])
        return {
            "file_path": str(path),
            "rows": contents["rows"],
            "columns": contents["columns"],
            "configuration": contents["configuration"],
        }

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("export_bom_csv", _export_operation),
    )
