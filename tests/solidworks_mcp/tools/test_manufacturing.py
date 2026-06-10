"""Tests for SolidWorks manufacturing tools."""

from unittest.mock import AsyncMock, Mock

import pytest

from solidworks_mcp.tools.manufacturing import (
    AddThreadInput,
    ApplyMaterialInput,
    CreateBomInput,
    ExportBomCsvInput,
    register_manufacturing_tools,
)


async def _tool(mcp_server, name):
    for tool in await mcp_server.list_tools():
        if tool.name == name:
            return tool.fn
    return None


class TestManufacturingTools:
    """Test suite for manufacturing tools."""

    @pytest.mark.asyncio
    async def test_register_manufacturing_tools(
        self, mcp_server, mock_adapter, mock_config
    ):
        """Test that manufacturing tools register correctly."""
        tool_count = await register_manufacturing_tools(
            mcp_server, mock_adapter, mock_config
        )
        assert tool_count == 4

    @pytest.mark.asyncio
    async def test_apply_material_success(self, mcp_server, mock_adapter, mock_config):
        """Test successful material assignment via the adapter."""
        await register_manufacturing_tools(mcp_server, mock_adapter, mock_config)

        mock_adapter.apply_material = AsyncMock(
            return_value=Mock(
                is_success=True,
                data={"material": "Plain Carbon Steel", "configuration": "Default"},
                execution_time=0.1,
            )
        )

        tool_func = await _tool(mcp_server, "apply_material")
        assert tool_func is not None
        result = await tool_func(
            input_data=ApplyMaterialInput(material="Plain Carbon Steel")
        )

        assert result["status"] == "success"
        assert result["material"]["material"] == "Plain Carbon Steel"
        params = mock_adapter.apply_material.call_args.args[0]
        assert params.material == "Plain Carbon Steel"
        assert params.database == ""
        assert params.configuration == ""

    @pytest.mark.asyncio
    async def test_apply_material_adapter_error(
        self, mcp_server, mock_adapter, mock_config
    ):
        """Test handling of adapter errors in apply_material."""
        await register_manufacturing_tools(mcp_server, mock_adapter, mock_config)

        mock_adapter.apply_material = AsyncMock(
            return_value=Mock(
                is_success=False,
                error="Material 'Unobtainium' was not applied",
                execution_time=0.1,
            )
        )

        tool_func = await _tool(mcp_server, "apply_material")
        result = await tool_func(input_data=ApplyMaterialInput(material="Unobtainium"))
        assert result["status"] == "error"
        assert "Unobtainium" in result["message"]

    @pytest.mark.asyncio
    async def test_add_thread_success(self, mcp_server, mock_adapter, mock_config):
        """Test successful cosmetic thread creation via the adapter."""
        await register_manufacturing_tools(mcp_server, mock_adapter, mock_config)

        mock_adapter.add_thread = AsyncMock(
            return_value=Mock(
                is_success=True,
                data={
                    "name": "Cosmetic Thread1",
                    "standard": "ansi_inch",
                    "size": "1/4-20",
                },
                execution_time=0.1,
            )
        )

        tool_func = await _tool(mcp_server, "add_thread")
        assert tool_func is not None
        result = await tool_func(
            input_data=AddThreadInput(
                edge_point=[25.0, 0.0, 100.0],
                standard="ansi_inch",
                size="1/4-20",
                end_type="blind",
                depth=12.0,
            )
        )

        assert result["status"] == "success"
        assert result["thread"]["name"] == "Cosmetic Thread1"
        params = mock_adapter.add_thread.call_args.args[0]
        assert params.edge_point == [25.0, 0.0, 100.0]
        assert params.depth == 12.0

    @pytest.mark.asyncio
    async def test_create_bom_success(self, mcp_server, mock_adapter, mock_config):
        """Test successful BOM creation via the adapter."""
        await register_manufacturing_tools(mcp_server, mock_adapter, mock_config)

        mock_adapter.create_bom = AsyncMock(
            return_value=Mock(
                is_success=True,
                data={
                    "rows": 3,
                    "columns": 3,
                    "header": ["ITEM NO.", "PART NUMBER", "QTY."],
                    "data": [["1", "part-a", "2"], ["2", "part-b", "1"]],
                    "configuration": "Default",
                    "bom_type": "parts_only",
                },
                execution_time=0.2,
            )
        )

        tool_func = await _tool(mcp_server, "create_bom")
        assert tool_func is not None
        result = await tool_func(input_data=CreateBomInput())

        assert result["status"] == "success"
        assert result["bom"]["rows"] == 3
        params = mock_adapter.create_bom.call_args.args[0]
        assert params.bom_type == "parts_only"

    @pytest.mark.asyncio
    async def test_export_bom_csv_success(self, mcp_server, mock_adapter, mock_config):
        """Test successful BOM CSV export via the adapter."""
        await register_manufacturing_tools(mcp_server, mock_adapter, mock_config)

        mock_adapter.export_bom_csv = AsyncMock(
            return_value=Mock(
                is_success=True,
                data={
                    "file_path": "C:/exports/bom.csv",
                    "rows": 3,
                    "columns": 3,
                    "configuration": "Default",
                },
                execution_time=0.2,
            )
        )

        tool_func = await _tool(mcp_server, "export_bom_csv")
        assert tool_func is not None
        result = await tool_func(
            input_data=ExportBomCsvInput(file_path="C:/exports/bom.csv")
        )

        assert result["status"] == "success"
        assert result["export"]["file_path"] == "C:/exports/bom.csv"
        params = mock_adapter.export_bom_csv.call_args.args[0]
        assert params.file_path == "C:/exports/bom.csv"

    @pytest.mark.asyncio
    async def test_export_bom_csv_adapter_error(
        self, mcp_server, mock_adapter, mock_config
    ):
        """Test handling of adapter errors in export_bom_csv."""
        await register_manufacturing_tools(mcp_server, mock_adapter, mock_config)

        mock_adapter.export_bom_csv = AsyncMock(
            return_value=Mock(
                is_success=False,
                error="Failed to insert BOM table",
                execution_time=0.1,
            )
        )

        tool_func = await _tool(mcp_server, "export_bom_csv")
        result = await tool_func(
            input_data=ExportBomCsvInput(file_path="C:/exports/bom.csv")
        )
        assert result["status"] == "error"
        assert "Failed to insert BOM table" in result["message"]

    @pytest.mark.unit
    def test_manufacturing_input_validation(self):
        """Test input validation for the manufacturing tools."""
        assert ApplyMaterialInput(material="Brass").material == "Brass"

        with pytest.raises(ValueError):  # empty material
            ApplyMaterialInput(material="   ")

        with pytest.raises(ValueError):  # bad point
            AddThreadInput(edge_point=[1.0, 2.0])

        with pytest.raises(ValueError):  # unknown standard
            AddThreadInput(edge_point=[0, 0, 0], standard="whitworth")

        with pytest.raises(ValueError):  # unknown end type
            AddThreadInput(edge_point=[0, 0, 0], end_type="bottomless")

        with pytest.raises(ValueError):  # unknown bom type
            CreateBomInput(bom_type="exploded")

        with pytest.raises(ValueError):  # missing file path
            ExportBomCsvInput(file_path="   ")
