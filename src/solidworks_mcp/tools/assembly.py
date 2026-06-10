"""Assembly component tools for SolidWorks MCP Server (Phase 7A).

Provides tools for managing components of the active assembly document:
insertion, removal, replacement, precise move/rotate, fix/float and local
component patterns. Mates are Phase 7B/7C.
"""

from typing import Any

from fastmcp import FastMCP
from loguru import logger
from pydantic import BaseModel, Field

from ..adapters.base import (
    ComponentCircularPatternParameters,
    ComponentLinearPatternParameters,
    ComponentRefParameters,
    InsertComponentParameters,
    MoveComponentParameters,
    ReplaceComponentParameters,
    RotateComponentParameters,
    SolidWorksAdapter,
)
from .modeling import _normalize_input


class InsertComponentInput(BaseModel):
    """Input schema for inserting a component into the active assembly.

    Attributes:
        file_path (str): Path to the .sldprt/.sldasm file to insert.
        position (list[float]): Component-origin position in mm.
        rotation (list[float]): XYZ rotation in degrees.
        configuration (str): Component configuration; empty for active.
    """

    file_path: str = Field(description="Path to the .sldprt or .sldasm file to insert")
    position: list[float] = Field(
        default=[0.0, 0.0, 0.0],
        description=(
            "[x, y, z] component-origin position in assembly space, "
            "millimetres (applied as an exact transform)"
        ),
    )
    rotation: list[float] = Field(
        default=[0.0, 0.0, 0.0],
        description=(
            "[rx, ry, rz] rotation in degrees, applied about the assembly "
            "X, then Y, then Z axes"
        ),
    )
    configuration: str = Field(
        default="",
        description=(
            "Configuration of the inserted component; empty for its active "
            "configuration"
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate the file path and pose vectors.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the path is empty or a vector is malformed.
        """
        if not self.file_path.strip():
            raise ValueError("file_path is required")
        if len(self.position) != 3:
            raise ValueError("position must be [x, y, z] in millimetres")
        if len(self.rotation) != 3:
            raise ValueError("rotation must be [rx, ry, rz] in degrees")


class ComponentRefInput(BaseModel):
    """Input schema referencing one component of the active assembly.

    Attributes:
        name (str): Component name with instance suffix.
    """

    name: str = Field(
        description=(
            "Component name with instance suffix, e.g. 'shaft-1' "
            "('sub-1/part-1' for a child of a subassembly); the '@assembly' "
            "qualifier is optional"
        )
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate the component name.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the name is empty.
        """
        if not self.name.strip():
            raise ValueError("name is required")


class ReplaceComponentInput(ComponentRefInput):
    """Input schema for replacing a component with another model.

    Attributes:
        file_path (str): Path to the replacement model.
        configuration (str): Replacement configuration to use.
        replace_all (bool): Replace all instances of the model.
        reattach_mates (bool): Re-attach existing mates.
    """

    file_path: str = Field(
        description=(
            "Path to the replacement .sldprt/.sldasm (must not have the "
            "same file name as the replaced component)"
        )
    )
    configuration: str = Field(
        default="",
        description=(
            "Configuration of the replacement to use; empty lets SolidWorks "
            "match configuration names"
        ),
    )
    replace_all: bool = Field(
        default=False,
        description="Replace every instance of the component's model",
    )
    reattach_mates: bool = Field(
        default=True,
        description="Re-attach existing mates to the replacement",
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate the component name and file path.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the name or path is empty.
        """
        super().model_post_init(__context)
        if not self.file_path.strip():
            raise ValueError("file_path is required")


class MoveComponentInput(ComponentRefInput):
    """Input schema for moving a component in assembly space.

    Attributes:
        position (list[float]): Target position or delta in mm.
        relative (bool): Interpret position as a delta.
    """

    position: list[float] = Field(
        description=(
            "[x, y, z] in millimetres — target component-origin position, "
            "or a delta when relative=true; rotation is preserved"
        )
    )
    relative: bool = Field(
        default=False,
        description="Interpret position as a delta from the current position",
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate the component name and position.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the name is empty or position malformed.
        """
        super().model_post_init(__context)
        if len(self.position) != 3:
            raise ValueError("position must be [x, y, z] in millimetres")


class RotateComponentInput(ComponentRefInput):
    """Input schema for rotating a component about an axis.

    Attributes:
        angle (float): Rotation angle in degrees.
        axis_vector (list[float]): Rotation-axis direction.
        axis_point (list[float]): Point on the rotation axis in mm.
    """

    angle: float = Field(description="Rotation angle in degrees (right-hand rule)")
    axis_vector: list[float] = Field(
        default=[0.0, 0.0, 1.0],
        description="Rotation-axis direction in assembly space",
    )
    axis_point: list[float] = Field(
        default=[0.0, 0.0, 0.0],
        description="[x, y, z] in millimetres — a point the axis passes through",
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate the component name and axis.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the name is empty or the axis is malformed.
        """
        super().model_post_init(__context)
        if len(self.axis_vector) != 3 or len(self.axis_point) != 3:
            raise ValueError("axis_vector and axis_point must each be [x, y, z]")
        if all(abs(c) < 1e-12 for c in self.axis_vector):
            raise ValueError("axis_vector must be non-zero")


class PatternComponentsLinearInput(BaseModel):
    """Input schema for a local linear component pattern.

    Attributes:
        components (list[str]): Seed component names.
        count (int): Total instances including the seeds.
        spacing (float): Instance spacing in mm.
        direction_name (str): Named direction reference.
        direction_point (list[float]): Point on the direction reference, mm.
    """

    components: list[str] = Field(description="Seed component names, e.g. ['gear-1']")
    count: int = Field(description="Total number of instances, including the seeds")
    spacing: float = Field(description="Distance between instances in millimetres")
    direction_name: str = Field(
        default="",
        description=(
            "Name of a reference feature (e.g. a reference axis) giving the "
            "pattern direction; takes precedence over direction_point"
        ),
    )
    direction_point: list[float] = Field(
        default=[],
        description=(
            "[x, y, z] in millimetres on the direction reference (linear edge or axis)"
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate seeds, count and direction reference.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the pattern definition is incomplete.
        """
        if not self.components:
            raise ValueError("components must name at least one component")
        if self.count < 1:
            raise ValueError("count must be >= 1")
        if not self.direction_name and not self.direction_point:
            raise ValueError("direction_name or direction_point is required")
        if self.direction_point and len(self.direction_point) != 3:
            raise ValueError("direction_point must be [x, y, z] in millimetres")


class PatternComponentsCircularInput(BaseModel):
    """Input schema for a local circular component pattern.

    Attributes:
        components (list[str]): Seed component names.
        count (int): Total instances including the seeds.
        angle (float): Total span (equal spacing) or per-instance spacing, deg.
        equal_spacing (bool): Distribute instances equally across angle.
        axis_name (str): Named reference-axis feature.
        axis_point (list[float]): Point on the axis reference, mm.
    """

    components: list[str] = Field(
        description="Seed component names, e.g. ['cone-gear-1']"
    )
    count: int = Field(description="Total number of instances, including the seeds")
    angle: float = Field(
        default=360.0,
        description=(
            "Total angular span in degrees when equal_spacing is true, "
            "otherwise the spacing between instances"
        ),
    )
    equal_spacing: bool = Field(
        default=True,
        description="Distribute instances equally across angle",
    )
    axis_name: str = Field(
        default="",
        description=(
            "Name of a reference-axis feature to rotate about; takes "
            "precedence over axis_point"
        ),
    )
    axis_point: list[float] = Field(
        default=[],
        description=(
            "[x, y, z] in millimetres on the rotation-axis reference "
            "(cylindrical face, linear edge or axis)"
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate seeds, count and axis reference.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the pattern definition is incomplete.
        """
        if not self.components:
            raise ValueError("components must name at least one component")
        if self.count < 1:
            raise ValueError("count must be >= 1")
        if not self.axis_name and not self.axis_point:
            raise ValueError("axis_name or axis_point is required")
        if self.axis_point and len(self.axis_point) != 3:
            raise ValueError("axis_point must be [x, y, z] in millimetres")


async def register_assembly_tools(
    mcp: FastMCP, adapter: SolidWorksAdapter, config: Any
) -> int:
    """Register assembly component tools with the MCP server.

    Args:
        mcp (FastMCP): The mcp value.
        adapter (SolidWorksAdapter): Adapter instance used for the operation.
        config (Any): Configuration values for the operation.

    Returns:
        int: The number of tools registered.
    """

    @mcp.tool()
    async def insert_component(input_data: InsertComponentInput) -> dict[str, Any]:
        """Insert a part or assembly as a component of the active assembly.

        Preloads the file (an AddComponent5 requirement), inserts it, then
        positions it exactly at the requested pose via a component
        transform. The first component inserted into an empty assembly is
        automatically fixed by SolidWorks.

        Args:
            input_data (InsertComponentInput): File, pose, configuration.

        Returns:
            dict[str, Any]: Status and inserted component details.

        Example:
            ```python
            result = await insert_component({
                "file_path": "C:/parts/shaft.SLDPRT",
                "position": [0, 0, 25],
                "rotation": [0, 90, 0],
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, InsertComponentInput)
            result = await adapter.insert_component(
                InsertComponentParameters(
                    file_path=input_data.file_path,
                    position=input_data.position,
                    rotation=input_data.rotation,
                    configuration=input_data.configuration,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Inserted component: {payload.get('name')}",
                    "component": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to insert component: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in insert_component tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def remove_component(input_data: ComponentRefInput) -> dict[str, Any]:
        """Delete a component from the active assembly.

        The component file stays open in memory; only the assembly instance
        is removed.

        Args:
            input_data (ComponentRefInput): Component name.

        Returns:
            dict[str, Any]: Status and removal confirmation.

        Example:
            ```python
            result = await remove_component({"name": "shaft-1"})
            ```
        """
        try:
            input_data = _normalize_input(input_data, ComponentRefInput)
            result = await adapter.remove_component(
                ComponentRefParameters(name=input_data.name)
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Removed component: {payload.get('name')}",
                    "component": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to remove component: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in remove_component tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def replace_component(input_data: ReplaceComponentInput) -> dict[str, Any]:
        """Replace a component of the active assembly with another model.

        The component must be top-level and the replacement file name must
        differ from the replaced one (ReplaceComponents2 API limits).

        Args:
            input_data (ReplaceComponentInput): Component, file, options.

        Returns:
            dict[str, Any]: Status and replacement summary.

        Example:
            ```python
            result = await replace_component({
                "name": "gear-12t-1",
                "file_path": "C:/parts/gear-24t.SLDPRT",
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, ReplaceComponentInput)
            result = await adapter.replace_component(
                ReplaceComponentParameters(
                    name=input_data.name,
                    file_path=input_data.file_path,
                    configuration=input_data.configuration,
                    replace_all=input_data.replace_all,
                    reattach_mates=input_data.reattach_mates,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Replaced component: {payload.get('name')}",
                    "component": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to replace component: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in replace_component tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def move_component(input_data: MoveComponentInput) -> dict[str, Any]:
        """Move a component to a position in assembly space.

        Sets the component-origin position exactly (rotation preserved) and
        re-solves mates. A fixed component is floated for the move and
        re-fixed at the new position. Mates may pull the component to the
        closest valid location.

        Args:
            input_data (MoveComponentInput): Component and target position.

        Returns:
            dict[str, Any]: Status and resulting position.

        Example:
            ```python
            result = await move_component({
                "name": "shaft-1",
                "position": [0, 0, 50],
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, MoveComponentInput)
            result = await adapter.move_component(
                MoveComponentParameters(
                    name=input_data.name,
                    position=input_data.position,
                    relative=input_data.relative,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Moved component: {payload.get('name')}",
                    "component": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to move component: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in move_component tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def rotate_component(input_data: RotateComponentInput) -> dict[str, Any]:
        """Rotate a component about an axis in assembly space.

        Composes the rotation onto the component's current transform and
        re-solves mates — the primary way to drive a mated gear train
        (rotate the input crank, mates propagate the motion).

        Args:
            input_data (RotateComponentInput): Component, axis and angle.

        Returns:
            dict[str, Any]: Status and rotation summary.

        Example:
            ```python
            result = await rotate_component({
                "name": "crank-1",
                "angle": 90,
                "axis_vector": [1, 0, 0],
                "axis_point": [0, 40, 0],
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, RotateComponentInput)
            result = await adapter.rotate_component(
                RotateComponentParameters(
                    name=input_data.name,
                    angle=input_data.angle,
                    axis_vector=input_data.axis_vector,
                    axis_point=input_data.axis_point,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Rotated component: {payload.get('name')}",
                    "component": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to rotate component: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in rotate_component tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def fix_component(input_data: ComponentRefInput) -> dict[str, Any]:
        """Fix a component of the active assembly (make it immovable).

        Args:
            input_data (ComponentRefInput): Component name.

        Returns:
            dict[str, Any]: Status and resulting fixed state.

        Example:
            ```python
            result = await fix_component({"name": "harmonic-base-1"})
            ```
        """
        try:
            input_data = _normalize_input(input_data, ComponentRefInput)
            result = await adapter.fix_component(
                ComponentRefParameters(name=input_data.name)
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Fixed component: {payload.get('name')}",
                    "component": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to fix component: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in fix_component tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def float_component(input_data: ComponentRefInput) -> dict[str, Any]:
        """Float a component of the active assembly (make it movable).

        Args:
            input_data (ComponentRefInput): Component name.

        Returns:
            dict[str, Any]: Status and resulting fixed state.

        Example:
            ```python
            result = await float_component({"name": "shaft-1"})
            ```
        """
        try:
            input_data = _normalize_input(input_data, ComponentRefInput)
            result = await adapter.float_component(
                ComponentRefParameters(name=input_data.name)
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Floated component: {payload.get('name')}",
                    "component": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to float component: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in float_component tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def pattern_components_linear(
        input_data: PatternComponentsLinearInput,
    ) -> dict[str, Any]:
        """Create a local linear component pattern in the active assembly.

        Patterns the seed components along a direction reference — e.g. the
        20 analyzer channels at the channel pitch.

        Args:
            input_data (PatternComponentsLinearInput): Pattern definition.

        Returns:
            dict[str, Any]: Status and pattern feature details.

        Example:
            ```python
            result = await pattern_components_linear({
                "components": ["rocker-arm-1"],
                "count": 20,
                "spacing": 15.875,
                "direction_name": "Axis1",
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, PatternComponentsLinearInput)
            result = await adapter.pattern_components_linear(
                ComponentLinearPatternParameters(
                    components=input_data.components,
                    count=input_data.count,
                    spacing=input_data.spacing,
                    direction_name=input_data.direction_name,
                    direction_point=input_data.direction_point,
                )
            )
            if result.is_success and result.data:
                return {
                    "status": "success",
                    "message": f"Created component pattern: {result.data.name}",
                    "feature": result.data.model_dump(),
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create component pattern: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in pattern_components_linear tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def pattern_components_circular(
        input_data: PatternComponentsCircularInput,
    ) -> dict[str, Any]:
        """Create a local circular component pattern in the active assembly.

        Patterns the seed components about an axis reference — e.g. bolts
        around a platen, or gears spaced about a shaft.

        Args:
            input_data (PatternComponentsCircularInput): Pattern definition.

        Returns:
            dict[str, Any]: Status and pattern feature details.

        Example:
            ```python
            result = await pattern_components_circular({
                "components": ["platen-bolt-1"],
                "count": 8,
                "axis_name": "Axis1",
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, PatternComponentsCircularInput)
            result = await adapter.pattern_components_circular(
                ComponentCircularPatternParameters(
                    components=input_data.components,
                    count=input_data.count,
                    angle=input_data.angle,
                    equal_spacing=input_data.equal_spacing,
                    axis_name=input_data.axis_name,
                    axis_point=input_data.axis_point,
                )
            )
            if result.is_success and result.data:
                return {
                    "status": "success",
                    "message": f"Created component pattern: {result.data.name}",
                    "feature": result.data.model_dump(),
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create component pattern: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in pattern_components_circular tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    tool_count = 9  # Number of tools registered
    return tool_count
