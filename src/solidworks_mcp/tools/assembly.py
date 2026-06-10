"""Assembly tools for SolidWorks MCP Server (Phases 7A/7B).

Provides tools for managing components of the active assembly document
(insertion, removal, replacement, precise move/rotate, fix/float, local
component patterns) and standard mates (add/list/delete/suppress).
Mechanical mates are Phase 7C.
"""

from typing import Any

from fastmcp import FastMCP
from loguru import logger
from pydantic import BaseModel, Field

from ..adapters.base import (
    AddMateParameters,
    ComponentCircularPatternParameters,
    ComponentLinearPatternParameters,
    ComponentRefParameters,
    InsertComponentParameters,
    MateEntityRef,
    MateRefParameters,
    MoveComponentParameters,
    ReplaceComponentParameters,
    RotateComponentParameters,
    SolidWorksAdapter,
    SuppressMateParameters,
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


class MateEntityInput(BaseModel):
    """Input schema for one entity of a mate, located by name or by point.

    Attributes:
        entity_type (str): SelectByID2 entity-type string.
        name (str): Entity name; empty when locating by point.
        point (list[float]): Pick point in mm; empty when locating by name.
        mark (int): Explicit selection mark; 0 uses the mate-type default.
    """

    entity_type: str = Field(
        description=(
            "SelectByID2 entity-type string: 'FACE', 'EDGE', 'PLANE', "
            "'AXIS', 'VERTEX', ..."
        )
    )
    name: str = Field(
        default="",
        description=(
            "Entity name — inside a component use 'Plane1@shaft-1' (the "
            "assembly qualifier is appended automatically); empty when "
            "locating by point"
        ),
    )
    point: list[float] = Field(
        default=[],
        description=(
            "[x, y, z] in millimetres on the entity (view-dependent pick); "
            "empty when locating by name"
        ),
    )
    mark: int = Field(
        default=0,
        description=(
            "Explicit selection mark; 0 selects with the mate type's "
            "default (1 standard, 16 width tab faces)"
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate the entity locator.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the locator is missing or malformed.
        """
        if not self.entity_type.strip():
            raise ValueError("entity_type is required")
        if not self.name.strip() and not self.point:
            raise ValueError("each entity needs a name or a point")
        if self.point and len(self.point) != 3:
            raise ValueError("point must be [x, y, z] in millimetres")


class AddMateInput(BaseModel):
    """Input schema for adding a standard mate.

    Attributes:
        mate_type (str): Standard mate type name.
        entities (list[MateEntityInput]): Entities to mate.
        alignment (str): Mate alignment.
        flip (bool): Flip to the other valid position.
        distance (float): Distance value in mm.
        distance_limits (list[float]): [min, max] mm for a limit mate.
        angle (float): Angle value in degrees.
        angle_limits (list[float]): [min, max] degrees for a limit mate.
        lock_rotation (bool): Lock rotation (concentric mates).
    """

    mate_type: str = Field(
        description=(
            "'coincident', 'concentric', 'perpendicular', 'parallel', "
            "'tangent', 'distance', 'angle', 'width' or 'lock'"
        )
    )
    entities: list[MateEntityInput] = Field(
        description=(
            "Entities to mate — two for standard mates; width mates take "
            "the two width faces plus the two tab faces"
        )
    )
    alignment: str = Field(
        default="closest",
        description="'aligned', 'anti_aligned' or 'closest'",
    )
    flip: bool = Field(
        default=False,
        description="Flip to the other valid mate position (distance/angle)",
    )
    distance: float = Field(
        default=0.0,
        description="Distance value in millimetres (distance mates)",
    )
    distance_limits: list[float] = Field(
        default=[],
        description=(
            "[min, max] in millimetres for a limit-distance mate; empty "
            "for a fixed distance"
        ),
    )
    angle: float = Field(
        default=0.0,
        description="Angle value in degrees (angle mates)",
    )
    angle_limits: list[float] = Field(
        default=[],
        description=(
            "[min, max] in degrees for a limit-angle mate; empty for a fixed angle"
        ),
    )
    lock_rotation: bool = Field(
        default=False,
        description="Lock component rotation (concentric mates)",
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate the mate definition.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the mate definition is incomplete.
        """
        if not self.mate_type.strip():
            raise ValueError("mate_type is required")
        minimum_entities = 4 if self.mate_type == "width" else 2
        if len(self.entities) < minimum_entities:
            raise ValueError(
                f"{self.mate_type} mate requires at least {minimum_entities} entities"
            )
        if self.distance_limits and len(self.distance_limits) != 2:
            raise ValueError("distance_limits must be [min, max]")
        if self.angle_limits and len(self.angle_limits) != 2:
            raise ValueError("angle_limits must be [min, max]")


class MateRefInput(BaseModel):
    """Input schema referencing one mate of the active assembly.

    Attributes:
        name (str): Mate feature name.
    """

    name: str = Field(
        description="Mate feature name as shown in the tree, e.g. 'Coincident1'"
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate the mate name.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the name is empty.
        """
        if not self.name.strip():
            raise ValueError("name is required")


class SuppressMateInput(MateRefInput):
    """Input schema for suppressing or unsuppressing a mate.

    Attributes:
        name (str): Mate feature name.
        suppress (bool): True to suppress, False to unsuppress.
    """

    suppress: bool = Field(
        default=True,
        description="True to suppress the mate, False to unsuppress it",
    )


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

    @mcp.tool()
    async def add_mate(input_data: AddMateInput) -> dict[str, Any]:
        """Add a standard mate between entities of the active assembly.

        Selects the entities (by name or pick point), then creates the mate
        with the requested alignment and value. Distance/angle without
        limits are fixed at the given value; with limits they become limit
        mates. Width mates take the two width faces plus the two tab faces.

        Args:
            input_data (AddMateInput): Mate type, entities and options.

        Returns:
            dict[str, Any]: Status and created mate details.

        Example:
            ```python
            result = await add_mate({
                "mate_type": "concentric",
                "entities": [
                    {"entity_type": "FACE", "point": [0, 0, 10]},
                    {"entity_type": "AXIS", "name": "Axis1@shaft-1"},
                ],
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, AddMateInput)
            result = await adapter.add_mate(
                AddMateParameters(
                    mate_type=input_data.mate_type,
                    entities=[
                        MateEntityRef(
                            entity_type=e.entity_type,
                            name=e.name,
                            point=e.point,
                            mark=e.mark,
                        )
                        for e in input_data.entities
                    ],
                    alignment=input_data.alignment,
                    flip=input_data.flip,
                    distance=input_data.distance,
                    distance_limits=input_data.distance_limits,
                    angle=input_data.angle,
                    angle_limits=input_data.angle_limits,
                    lock_rotation=input_data.lock_rotation,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Added mate: {payload.get('name')}",
                    "mate": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to add mate: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in add_mate tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def list_mates() -> dict[str, Any]:
        """List the active assembly's mates.

        Walks the MateGroup folder of the feature tree and returns each
        mate's name, type and suppression state.

        Returns:
            dict[str, Any]: Status, mates and count.

        Example:
            ```python
            result = await list_mates()
            ```
        """
        try:
            result = await adapter.list_mates()
            if result.is_success:
                mates = result.data or []
                return {
                    "status": "success",
                    "mates": mates,
                    "count": len(mates),
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to list mates: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in list_mates tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def delete_mate(input_data: MateRefInput) -> dict[str, Any]:
        """Delete a mate of the active assembly by feature name.

        Args:
            input_data (MateRefInput): Mate feature name.

        Returns:
            dict[str, Any]: Status and deletion confirmation.

        Example:
            ```python
            result = await delete_mate({"name": "Coincident1"})
            ```
        """
        try:
            input_data = _normalize_input(input_data, MateRefInput)
            result = await adapter.delete_mate(MateRefParameters(name=input_data.name))
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Deleted mate: {payload.get('name')}",
                    "mate": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to delete mate: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in delete_mate tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def suppress_mate(input_data: SuppressMateInput) -> dict[str, Any]:
        """Suppress or unsuppress a mate of the active assembly.

        Applied across all configurations; the resulting state is read back
        and verified.

        Args:
            input_data (SuppressMateInput): Mate name and target state.

        Returns:
            dict[str, Any]: Status and resulting suppression state.

        Example:
            ```python
            result = await suppress_mate({
                "name": "Distance1",
                "suppress": True,
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, SuppressMateInput)
            result = await adapter.suppress_mate(
                SuppressMateParameters(
                    name=input_data.name,
                    suppress=input_data.suppress,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Set mate suppression: {payload.get('name')}",
                    "mate": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to set mate suppression: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in suppress_mate tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    tool_count = 13  # Number of tools registered
    return tool_count
