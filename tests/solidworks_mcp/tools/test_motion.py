"""Tests for SolidWorks motion-study tools."""

from unittest.mock import AsyncMock, Mock

import pytest

from solidworks_mcp.tools.motion import (
    AddGravityInput,
    AddMotionDamperInput,
    AddMotionForceInput,
    AddMotionSpringInput,
    AddMotorInput,
    CreateMotionStudyInput,
    ExportMotionVideoInput,
    MotionEntityInput,
    MotionStudyRefInput,
    SetMotionTimeInput,
    register_motion_tools,
)


async def _tool(mcp_server, name):
    for tool in await mcp_server.list_tools():
        if tool.name == name:
            return tool.fn
    return None


class TestMotionTools:
    """Test suite for motion-study tools."""

    @pytest.mark.asyncio
    async def test_register_motion_tools(self, mcp_server, mock_adapter, mock_config):
        """All motion tools register under their expected names."""
        count = await register_motion_tools(mcp_server, mock_adapter, mock_config)
        assert count == 11
        names = {tool.name for tool in await mcp_server.list_tools()}
        assert {
            "create_motion_study",
            "ensure_motion_addin",
            "add_motor",
            "add_gravity",
            "calculate_motion",
            "set_motion_time",
            "export_motion_video",
            "list_motion_studies",
            "add_motion_spring",
            "add_motion_damper",
            "add_motion_force",
        } <= names

    @pytest.mark.asyncio
    async def test_create_motion_study_against_mock(
        self, mcp_server, mock_adapter, mock_config
    ):
        """create_motion_study drives the stateful mock end to end."""
        await register_motion_tools(mcp_server, mock_adapter, mock_config)
        await mock_adapter.create_assembly()
        fn = await _tool(mcp_server, "create_motion_study")
        result = await fn(
            CreateMotionStudyInput(study_type="motion_analysis", duration=4.0)
        )
        assert result["status"] == "success"
        assert result["study"]["study_type"] == "motion_analysis"

    @pytest.mark.asyncio
    async def test_add_motor_then_calculate_against_mock(
        self, mcp_server, mock_adapter, mock_config
    ):
        """A motor can be added and the study solved on the mock."""
        await register_motion_tools(mcp_server, mock_adapter, mock_config)
        await mock_adapter.create_assembly()
        await (await _tool(mcp_server, "create_motion_study"))(CreateMotionStudyInput())
        motor = await (await _tool(mcp_server, "add_motor"))(
            AddMotorInput(
                motor_type="rotary",
                entity=MotionEntityInput(entity_type="AXIS", name="Axis1@crank-1"),
                speed=30.0,
            )
        )
        assert motor["status"] == "success"
        calc = await (await _tool(mcp_server, "calculate_motion"))(
            MotionStudyRefInput()
        )
        assert calc["status"] == "success"
        assert calc["result"]["calculated"] is True

    @pytest.mark.asyncio
    async def test_add_gravity_and_time_and_avi_and_list(
        self, mcp_server, mock_adapter, mock_config
    ):
        """Gravity, scrubbing, AVI export and listing all succeed on the mock."""
        await register_motion_tools(mcp_server, mock_adapter, mock_config)
        await mock_adapter.create_assembly()
        await (await _tool(mcp_server, "create_motion_study"))(CreateMotionStudyInput())
        grav = await (await _tool(mcp_server, "add_gravity"))(AddGravityInput())
        assert grav["status"] == "success"
        t = await (await _tool(mcp_server, "set_motion_time"))(
            SetMotionTimeInput(time=1.5)
        )
        assert t["status"] == "success"
        avi = await (await _tool(mcp_server, "export_motion_video"))(
            ExportMotionVideoInput(file_path="C:/out/op.mp4")
        )
        assert avi["status"] == "success"
        listed = await (await _tool(mcp_server, "list_motion_studies"))()
        assert listed["status"] == "success"
        assert listed["count"] == 1

    @pytest.mark.asyncio
    async def test_ensure_motion_addin(self, mcp_server, mock_adapter, mock_config):
        """ensure_motion_addin reports success on the mock."""
        await register_motion_tools(mcp_server, mock_adapter, mock_config)
        fn = await _tool(mcp_server, "ensure_motion_addin")
        result = await fn()
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_add_spring_damper_force_against_mock(
        self, mcp_server, mock_adapter, mock_config
    ):
        """Spring, damper and force elements all add on the mock."""
        await register_motion_tools(mcp_server, mock_adapter, mock_config)
        await mock_adapter.create_assembly()
        await (await _tool(mcp_server, "create_motion_study"))(CreateMotionStudyInput())
        endpoints = [
            MotionEntityInput(entity_type="VERTEX", point=[0.0, 0.0, 0.0]),
            MotionEntityInput(entity_type="VERTEX", point=[0.0, 30.0, 0.0]),
        ]
        spring = await (await _tool(mcp_server, "add_motion_spring"))(
            AddMotionSpringInput(
                endpoints=endpoints, spring_constant=1500.0, free_length=25.0
            )
        )
        assert spring["status"] == "success"
        assert spring["spring"]["spring_constant"] == 1500.0
        damper = await (await _tool(mcp_server, "add_motion_damper"))(
            AddMotionDamperInput(endpoints=endpoints, damping_constant=5.0)
        )
        assert damper["status"] == "success"
        force = await (await _tool(mcp_server, "add_motion_force"))(
            AddMotionForceInput(
                action=MotionEntityInput(entity_type="FACE", point=[1.0, 1.0, 1.0]),
                magnitude=9.81,
            )
        )
        assert force["status"] == "success"
        assert force["force"]["magnitude"] == 9.81

    @pytest.mark.asyncio
    async def test_add_motion_spring_error_path(
        self, mcp_server, mock_adapter, mock_config
    ):
        """A spring adapter error surfaces as a tool error payload."""
        await register_motion_tools(mcp_server, mock_adapter, mock_config)
        mock_adapter.add_motion_spring = AsyncMock(
            return_value=Mock(is_success=False, error="no study")
        )
        fn = await _tool(mcp_server, "add_motion_spring")
        result = await fn(
            AddMotionSpringInput(
                endpoints=[
                    MotionEntityInput(entity_type="VERTEX", point=[0, 0, 0]),
                    MotionEntityInput(entity_type="VERTEX", point=[0, 1, 0]),
                ],
                spring_constant=1.0,
            )
        )
        assert result["status"] == "error"
        assert "no study" in result["message"]

    @pytest.mark.asyncio
    async def test_create_motion_study_error_path(
        self, mcp_server, mock_adapter, mock_config
    ):
        """An adapter error surfaces as a tool error payload."""
        await register_motion_tools(mcp_server, mock_adapter, mock_config)
        mock_adapter.create_motion_study = AsyncMock(
            return_value=Mock(is_success=False, error="boom")
        )
        fn = await _tool(mcp_server, "create_motion_study")
        result = await fn(CreateMotionStudyInput())
        assert result["status"] == "error"
        assert "boom" in result["message"]

    @pytest.mark.asyncio
    async def test_add_motor_unexpected_exception(
        self, mcp_server, mock_adapter, mock_config
    ):
        """An unexpected exception is caught and reported, not raised."""
        await register_motion_tools(mcp_server, mock_adapter, mock_config)
        mock_adapter.add_motor = AsyncMock(side_effect=RuntimeError("kaboom"))
        fn = await _tool(mcp_server, "add_motor")
        result = await fn(
            AddMotorInput(
                motor_type="rotary",
                entity=MotionEntityInput(entity_type="AXIS", name="Axis1@x"),
            )
        )
        assert result["status"] == "error"
        assert "kaboom" in result["message"]


class TestMotionEntityInputValidation:
    """Validation rules on the motor-entity locator."""

    def test_requires_name_or_point(self):
        with pytest.raises(ValueError, match="needs a name or a point"):
            MotionEntityInput(entity_type="AXIS")

    def test_point_must_be_xyz(self):
        with pytest.raises(ValueError, match="\\[x, y, z\\]"):
            MotionEntityInput(entity_type="FACE", point=[1.0, 2.0])

    def test_entity_type_required(self):
        with pytest.raises(ValueError, match="entity_type is required"):
            MotionEntityInput(entity_type="  ", name="Axis1@x")
