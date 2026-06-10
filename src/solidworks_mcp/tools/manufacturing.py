"""Manufacturing-prep tools for SolidWorks MCP Server (Phase 5).

Provides tools for material assignment, cosmetic threads and BOM tables
(including CSV export) — the manufacturing metadata layer applied after
geometry is modeled.
"""

from typing import Any

from fastmcp import FastMCP
from loguru import logger
from pydantic import BaseModel, Field

from ..adapters.base import (
    AddThreadParameters,
    ApplyMaterialParameters,
    CreateBomParameters,
    SolidWorksAdapter,
)
from .modeling import _normalize_input

_THREAD_STANDARDS = {
    "none",
    "ansi_inch",
    "ansi_metric",
    "bsi",
    "din",
    "helicoil_inch",
    "helicoil_metric",
    "iso",
    "jis",
}
_THREAD_END_TYPES = {"blind", "blind_upto_next", "through", "blind_2dia"}
_BOM_TYPES = {"parts_only", "top_level", "indented", "flattened"}


class ApplyMaterialInput(BaseModel):
    """Input schema for assigning a material to the active part.

    Attributes:
        material (str): Material name as it appears in the database.
        database (str): Material database; empty for the default.
        configuration (str): Configuration scope; empty for active.
    """

    material: str = Field(
        description=(
            "Material name exactly as it appears in the materials database, "
            "e.g. 'Plain Carbon Steel', 'Brass', 'Gray Cast Iron'"
        )
    )
    database: str = Field(
        default="",
        description=(
            "Materials database; empty for the default SolidWorks materials "
            "database, otherwise a .sldmat file name or path"
        ),
    )
    configuration: str = Field(
        default="",
        description=(
            "Configuration to assign the material in; empty for the active "
            "configuration"
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate the material name.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the material name is empty.
        """
        if not self.material.strip():
            raise ValueError("material is required")


class AddThreadInput(BaseModel):
    """Input schema for adding a cosmetic thread to a circular edge.

    Attributes:
        edge_point (list[float]): Point on the circular edge in mm.
        standard (str): Thread standard key.
        standard_type (str): Thread type within the standard.
        size (str): Thread size designation.
        diameter (float): Thread diameter in millimetres.
        end_type (str): Thread end condition key.
        depth (float): Thread depth in millimetres (blind types).
        note (str): Drawing callout text.
    """

    edge_point: list[float] = Field(
        description=(
            "[x, y, z] in millimetres on the circular edge of the "
            "cylindrical face to thread (point-based selection is "
            "view-dependent — prefer an unoccluded edge)"
        )
    )
    standard: str = Field(
        default="ansi_inch",
        description=(
            "Thread standard: one of "
            "'none', 'ansi_inch', 'ansi_metric', 'iso', 'din', 'jis', "
            "'bsi', 'helicoil_inch', 'helicoil_metric'"
        ),
    )
    standard_type: str = Field(
        default="",
        description="Thread type within the standard, e.g. 'Machine Threads'",
    )
    size: str = Field(
        default="",
        description="Thread size designation, e.g. '1/4-20' or 'M6x1.0'",
    )
    diameter: float = Field(
        default=0.0, description="Thread (minor/drill) diameter in millimetres"
    )
    end_type: str = Field(
        default="blind",
        description=(
            "Thread end condition: 'blind', 'blind_upto_next', 'through' or "
            "'blind_2dia'"
        ),
    )
    depth: float = Field(
        default=0.0,
        description="Thread depth in millimetres (blind end types only)",
    )
    note: str = Field(default="", description="Callout text shown in drawings")

    def model_post_init(self, __context: Any) -> None:
        """Validate the edge point and enum keys.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the point or enum keys are invalid.
        """
        if len(self.edge_point) != 3:
            raise ValueError("edge_point must be [x, y, z] in millimetres")
        if self.standard not in _THREAD_STANDARDS:
            raise ValueError(f"standard must be one of {sorted(_THREAD_STANDARDS)}")
        if self.end_type not in _THREAD_END_TYPES:
            raise ValueError(f"end_type must be one of {sorted(_THREAD_END_TYPES)}")


class CreateBomInput(BaseModel):
    """Input schema for inserting a BOM table.

    Attributes:
        bom_type (str): BOM table type key.
        configuration (str): Configuration the BOM reflects.
        template (str): BOM template path; empty for the installed default.
    """

    bom_type: str = Field(
        default="parts_only",
        description=("BOM type: 'parts_only', 'top_level', 'indented' or 'flattened'"),
    )
    configuration: str = Field(
        default="",
        description=(
            "Configuration the BOM reflects; empty for the active configuration"
        ),
    )
    template: str = Field(
        default="",
        description=(
            "Path to a .sldbomtbt BOM template; empty to use the installed "
            "bom-standard template"
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate the BOM type.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When bom_type is unknown.
        """
        if self.bom_type not in _BOM_TYPES:
            raise ValueError(f"bom_type must be one of {sorted(_BOM_TYPES)}")


class ExportBomCsvInput(CreateBomInput):
    """Input schema for exporting a BOM table to CSV.

    Attributes:
        file_path (str): Destination CSV path.
    """

    file_path: str = Field(description="Destination .csv file path")

    def model_post_init(self, __context: Any) -> None:
        """Validate the BOM type and file path.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When bom_type is unknown or file_path empty.
        """
        super().model_post_init(__context)
        if not self.file_path.strip():
            raise ValueError("file_path is required")


async def register_manufacturing_tools(
    mcp: FastMCP, adapter: SolidWorksAdapter, config: Any
) -> int:
    """Register manufacturing-prep tools with the MCP server.

    Args:
        mcp (FastMCP): The mcp value.
        adapter (SolidWorksAdapter): Adapter instance used for the operation.
        config (Any): Configuration values for the operation.

    Returns:
        int: The number of tools registered.
    """

    @mcp.tool()
    async def apply_material(input_data: ApplyMaterialInput) -> dict[str, Any]:
        """Assign a material to the active part.

        Looks the material up in the SolidWorks materials database (or a
        custom .sldmat database), assigns it to the requested configuration
        and rebuilds so mass properties reflect the new density. The
        assignment is verified by reading the material back.

        Args:
            input_data (ApplyMaterialInput): Material, database, scope.

        Returns:
            dict[str, Any]: Status and applied material details.

        Example:
            ```python
            result = await apply_material({"material": "Plain Carbon Steel"})
            ```
        """
        try:
            input_data = _normalize_input(input_data, ApplyMaterialInput)
            result = await adapter.apply_material(
                ApplyMaterialParameters(
                    material=input_data.material,
                    database=input_data.database,
                    configuration=input_data.configuration,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Applied material: {payload.get('material')}",
                    "material": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to apply material: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in apply_material tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def add_thread(input_data: AddThreadInput) -> dict[str, Any]:
        """Add a cosmetic thread to a circular edge.

        Selects the circular edge at the given point and inserts a cosmetic
        thread (annotation-level thread, the standard practice for
        manufacturing callouts). Blind end types take a depth; sizes follow
        the chosen standard's designations.

        Args:
            input_data (AddThreadInput): Edge location and thread spec.

        Returns:
            dict[str, Any]: Status and thread feature details.

        Example:
            ```python
            result = await add_thread({
                "edge_point": [0, 0, 0],
                "standard": "ansi_inch",
                "size": "1/4-20",
                "end_type": "blind",
                "depth": 12.0,
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, AddThreadInput)
            result = await adapter.add_thread(
                AddThreadParameters(
                    edge_point=input_data.edge_point,
                    standard=input_data.standard,
                    standard_type=input_data.standard_type,
                    size=input_data.size,
                    diameter=input_data.diameter,
                    end_type=input_data.end_type,
                    depth=input_data.depth,
                    note=input_data.note,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Added cosmetic thread: {payload.get('name')}",
                    "thread": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to add thread: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in add_thread tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def create_bom(input_data: CreateBomInput) -> dict[str, Any]:
        """Insert a BOM table into the active document and return its contents.

        Works on assemblies (and parts, for cut lists) — the table is
        inserted visibly and its rows are read back as displayed text, so
        the response contains the full bill of materials.

        Args:
            input_data (CreateBomInput): BOM type, configuration, template.

        Returns:
            dict[str, Any]: Status, table header and data rows.

        Example:
            ```python
            result = await create_bom({"bom_type": "parts_only"})
            ```
        """
        try:
            input_data = _normalize_input(input_data, CreateBomInput)
            result = await adapter.create_bom(
                CreateBomParameters(
                    bom_type=input_data.bom_type,
                    configuration=input_data.configuration,
                    template=input_data.template,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": (f"Created BOM table with {payload.get('rows')} rows"),
                    "bom": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create BOM: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in create_bom tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def export_bom_csv(input_data: ExportBomCsvInput) -> dict[str, Any]:
        """Insert a BOM table and write its contents to a CSV file.

        Same insertion as create_bom, then writes the header and data rows
        to the given .csv path (parent directories are created).

        Args:
            input_data (ExportBomCsvInput): BOM options plus file_path.

        Returns:
            dict[str, Any]: Status and export summary.

        Example:
            ```python
            result = await export_bom_csv({
                "bom_type": "parts_only",
                "file_path": "C:/exports/analyzer-bom.csv",
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, ExportBomCsvInput)
            result = await adapter.export_bom_csv(
                CreateBomParameters(
                    bom_type=input_data.bom_type,
                    configuration=input_data.configuration,
                    template=input_data.template,
                    file_path=input_data.file_path,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Exported BOM to {payload.get('file_path')}",
                    "export": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to export BOM: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in export_bom_csv tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    tool_count = 4  # Number of tools registered
    return tool_count
