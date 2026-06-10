"""Modeling tools for SolidWorks MCP Server.

Provides tools for creating and manipulating SolidWorks models, including parts,
assemblies, drawings, and features like extrusions, revolves, etc.
"""

from typing import Any, TypeVar

from fastmcp import FastMCP
from loguru import logger
from pydantic import BaseModel, Field

from ..adapters.base import (
    CircularPatternParameters,
    DraftParameters,
    ExtrusionParameters,
    LinearPatternParameters,
    LoftParameters,
    MirrorFeatureParameters,
    RevolveParameters,
    ShellParameters,
    SolidWorksAdapter,
    SweepParameters,
)
from .input_compat import CompatInput

TInput = TypeVar("TInput", bound=BaseModel)


# Input schemas using Python 3.14 built-in types


def _result_value(data: Any, *keys: str, default: Any = None) -> Any:
    """Build internal result value.

    Args:
        data (Any): The data value.
        *keys (str): Additional positional arguments forwarded to the call.
        default (Any): Fallback value returned when the operation fails. Defaults to None.

    Returns:
        Any: The result produced by the operation.
    """
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
        return default

    for key in keys:
        if hasattr(data, key):
            value = getattr(data, key)
            if value is not None:
                return value
    return default


def _normalize_input(input_data: Any, model_type: type[TInput]) -> TInput:
    """Build internal normalize input.

    Args:
        input_data (Any): The input data value.
        model_type (type[TInput]): The model type value.

    Returns:
        TInput: The result produced by the operation.
    """
    if isinstance(input_data, model_type):
        return input_data
    return model_type.model_validate(input_data)


class OpenModelInput(BaseModel):
    """Input schema for opening a SolidWorks model.

    Attributes:
        file_path (str): The file path value.
    """

    file_path: str = Field(
        description="Full path to the SolidWorks file (.sldprt, .sldasm, .slddrw)"
    )


class CreatePartInput(CompatInput):
    """Input schema for creating a new SolidWorks part.

    Attributes:
        material (str | None): The material value.
        name (str): The name value.
        template (str | None): The template value.
        units (str | None): The units value.
    """

    name: str = Field(description="Name for the new part")
    template: str | None = Field(
        default=None, description="Template file path for the new part"
    )
    units: str | None = Field(default=None, description="Document units")
    material: str | None = Field(default=None, description="Material name")

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the create part input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: Name is required.
        """
        if not self.name.strip():
            raise ValueError("name is required")


class CreateExtrusionInput(CompatInput):
    """Input schema for creating an extrusion feature.

    Attributes:
        both_directions (bool): The both directions value.
        depth (float): The depth value.
        direction (str): The direction value.
        draft_angle (float): The draft angle value.
        end_condition (str): The end condition value.
        merge_result (bool): The merge result value.
        reverse (bool | None): The reverse value.
        reverse_direction (bool): The reverse direction value.
        sketch_name (str): The sketch name value.
        thin_feature (bool): The thin feature value.
        thin_thickness (float | None): The thin thickness value.
    """

    sketch_name: str = Field(description="Sketch name to extrude")
    depth: float = Field(description="Extrusion depth in millimeters")
    direction: str = Field(default="blind", description="Extrusion direction")
    reverse: bool | None = Field(default=None, description="Reverse direction alias")
    draft_angle: float = Field(default=0.0, description="Draft angle in degrees")
    reverse_direction: bool = Field(
        default=False, description="Reverse extrusion direction"
    )
    both_directions: bool = Field(
        default=False, description="Extrude in both directions"
    )
    thin_feature: bool = Field(default=False, description="Create as thin wall feature")
    thin_thickness: float | None = Field(
        default=None, description="Thickness for thin wall feature in mm"
    )
    end_condition: str = Field(default="Blind", description="End condition type")
    merge_result: bool = Field(default=True, description="Merge with existing geometry")

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the create extrusion input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: Sketch_name is required.
        """
        if self.depth <= 0:
            raise ValueError("depth must be positive")
        if not self.sketch_name.strip():
            raise ValueError("sketch_name is required")
        if self.reverse is not None:
            self.reverse_direction = self.reverse


class CreateRevolveInput(CompatInput):
    """Input schema for creating a revolve feature.

    Attributes:
        angle (float): The angle value.
        axis_entity (str): The axis entity value.
        both_directions (bool): The both directions value.
        direction (str): The direction value.
        merge_result (bool): The merge result value.
        reverse_direction (bool): The reverse direction value.
        sketch_name (str): The sketch name value.
        thin_feature (bool): The thin feature value.
        thin_thickness (float | None): The thin thickness value.
    """

    sketch_name: str = Field(description="Sketch name to revolve")
    axis_entity: str = Field(description="Axis entity for the revolve")
    angle: float = Field(description="Revolve angle in degrees")
    direction: str = Field(default="one_direction", description="Revolve direction")
    reverse_direction: bool = Field(
        default=False, description="Reverse revolve direction"
    )
    both_directions: bool = Field(
        default=False, description="Revolve in both directions"
    )
    thin_feature: bool = Field(default=False, description="Create as thin wall feature")
    thin_thickness: float | None = Field(
        default=None, description="Thickness for thin wall feature in mm"
    )
    merge_result: bool = Field(default=True, description="Merge with existing geometry")

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the create revolve input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: Angle must be positive.
        """
        if self.angle <= 0:
            raise ValueError("angle must be positive")


class CreateSweepInput(BaseModel):
    """Input schema for creating a sweep feature.

    Attributes:
        merge_result (bool): The merge result value.
        path (str): The path value.
        twist_along_path (bool): The twist along path value.
        twist_angle (float): The twist angle value.
    """

    path: str = Field(description="Name or ID of the sweep path")
    twist_along_path: bool = Field(default=False, description="Twist along path")
    twist_angle: float = Field(default=0.0, description="Twist angle in degrees")
    merge_result: bool = Field(default=True, description="Merge with existing geometry")


class CreateLoftInput(BaseModel):
    """Input schema for creating a loft feature.

    Attributes:
        end_tangent (str | None): The end tangent value.
        guide_curves (list[str] | None): The guide curves value.
        merge_result (bool): The merge result value.
        profiles (list[str]): The profiles value.
        start_tangent (str | None): The start tangent value.
    """

    profiles: list[str] = Field(description="List of profile names or IDs")
    guide_curves: list[str] | None = Field(
        default=None, description="List of guide curve names or IDs"
    )
    start_tangent: str | None = Field(
        default=None, description="Start tangent condition"
    )
    end_tangent: str | None = Field(default=None, description="End tangent condition")
    merge_result: bool = Field(default=True, description="Merge with existing geometry")


class GetDimensionInput(CompatInput):
    """Input schema for getting a dimension value.

    Attributes:
        dimension_name (str | None): The dimension name value.
        name (str | None): The name value.
    """

    name: str | None = Field(
        default=None,
        description="Dimension name (e.g., 'D1@Sketch1', 'D1@Boss-Extrude1')",
    )
    dimension_name: str | None = Field(default=None, description="Dimension name alias")

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the get dimension input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: Name is required.
        """
        if self.name is None:
            self.name = self.dimension_name
        if not self.name:
            raise ValueError("name is required")


class SetDimensionInput(CompatInput):
    """Input schema for setting a dimension value.

    Attributes:
        dimension_name (str | None): The dimension name value.
        name (str | None): The name value.
        units (str | None): The units value.
        value (float): The value value.
    """

    name: str | None = Field(
        default=None,
        description="Dimension name (e.g., 'D1@Sketch1', 'D1@Boss-Extrude1')",
    )
    dimension_name: str | None = Field(default=None, description="Dimension name alias")
    value: float = Field(description="New dimension value in millimeters")
    units: str | None = Field(default=None, description="Units alias")

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the set dimension input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: Name is required.
        """
        if self.name is None:
            self.name = self.dimension_name
        if not self.name:
            raise ValueError("name is required")


class CloseModelInput(BaseModel):
    """Input schema for closing a model.

    Attributes:
        save (bool): The save value.
    """

    save: bool = Field(default=False, description="Save the model before closing")


class CreateCutExtrudeInput(CompatInput):
    """Input schema for creating a cut-extrude feature.

    Attributes:
        depth (float): Cut depth in millimeters.
        draft_angle (float): Draft angle in degrees.
        end_condition (str): End condition type.
        reverse_direction (bool): Reverse cut direction.
    """

    depth: float = Field(description="Cut depth in millimeters")
    draft_angle: float = Field(default=0.0, description="Draft angle in degrees")
    reverse_direction: bool = Field(default=False, description="Reverse cut direction")
    end_condition: str = Field(default="Blind", description="End condition type")

    def model_post_init(self, __context: Any) -> None:
        if self.depth <= 0:
            raise ValueError("depth must be positive")


class AddFilletInput(CompatInput):
    """Input schema for adding a fillet feature.

    Attributes:
        radius (float): Fillet radius in millimeters.
        edge_points (list[list[float]]): Points ``[x, y, z]`` (mm), one per edge.
    """

    radius: float = Field(description="Fillet radius in millimeters")
    edge_points: list[list[float]] = Field(
        description=(
            "Edges to fillet, located by a point [x, y, z] in mm lying on each "
            "edge (SolidWorks edges have no stable name)."
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        if self.radius <= 0:
            raise ValueError("radius must be positive")
        if not self.edge_points:
            raise ValueError("at least one edge point is required")
        if any(len(p) != 3 for p in self.edge_points):
            raise ValueError("each edge point must be [x, y, z]")


class AddChamferInput(CompatInput):
    """Input schema for adding a chamfer feature.

    Attributes:
        distance (float): Chamfer leg length in millimeters.
        edge_points (list[list[float]]): Points ``[x, y, z]`` (mm), one per edge.
    """

    distance: float = Field(description="Chamfer distance in millimeters")
    edge_points: list[list[float]] = Field(
        description=(
            "Edges to chamfer, located by a point [x, y, z] in mm lying on each "
            "edge (SolidWorks edges have no stable name)."
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        if self.distance <= 0:
            raise ValueError("distance must be positive")
        if not self.edge_points:
            raise ValueError("at least one edge point is required")
        if any(len(p) != 3 for p in self.edge_points):
            raise ValueError("each edge point must be [x, y, z]")


class MirrorFeatureInput(BaseModel):
    """Input schema for a 3D mirror-feature operation.

    Attributes:
        plane (str): Name of the mirror plane or planar face.
        features (list[str]): Names of features to mirror.
        merge (bool): Merge resulting bodies.
        geometry_pattern (bool): Mirror geometry only.
    """

    plane: str = Field(description="Mirror plane name, e.g. 'Right Plane'")
    features: list[str] = Field(description="Names of features to mirror")
    merge: bool = Field(default=True, description="Merge resulting bodies")
    geometry_pattern: bool = Field(
        default=False, description="Mirror geometry only (faster, no re-solve)"
    )

    def model_post_init(self, __context: Any) -> None:
        if not self.features:
            raise ValueError("at least one feature to mirror is required")


class CircularPatternInput(BaseModel):
    """Input schema for a circular feature pattern.

    Attributes:
        axis_point (list[float]): Point [x, y, z] mm on the rotation axis ref.
        axis_name (str): Reference-axis feature name (preferred over point).
        features (list[str]): Names of seed features to pattern.
        count (int): Total instances including the seed.
        angle (float): Total span in degrees when equal_spacing, else step.
        equal_spacing (bool): Distribute equally across angle.
        geometry_pattern (bool): Copy seed geometry verbatim per instance.
    """

    axis_point: list[float] = Field(
        default=[],
        description=(
            "Point [x, y, z] in mm on the rotation-axis reference: a "
            "cylindrical face or a linear edge. Ignored when axis_name is "
            "given; the point pick projects through the view and fails on "
            "axes buried inside solid material."
        ),
    )
    axis_name: str = Field(
        default="",
        description=(
            "Name of a reference-axis feature (e.g. 'Axis1') to rotate "
            "about. Takes precedence over axis_point; robust for axes from "
            "create_axis."
        ),
    )
    features: list[str] = Field(description="Names of seed features to pattern")
    count: int = Field(description="Total number of instances, including the seed")
    angle: float = Field(
        default=360.0,
        description="Total angle in degrees (equal spacing) or step angle",
    )
    equal_spacing: bool = Field(
        default=True, description="Distribute instances equally across the angle"
    )
    geometry_pattern: bool = Field(
        default=False,
        description=(
            "Copy the seed feature's geometry verbatim instead of re-solving "
            "it per instance (required for equation-driven seed profiles)"
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        if not self.axis_name and not self.axis_point:
            raise ValueError("axis_name or axis_point is required")
        if self.axis_point and len(self.axis_point) != 3:
            raise ValueError("axis_point must be [x, y, z]")
        if not self.features:
            raise ValueError("at least one feature is required")
        if self.count < 1:
            raise ValueError("count must be >= 1")


class LinearPatternInput(BaseModel):
    """Input schema for a linear feature pattern.

    Attributes:
        direction_point (list[float]): Point [x, y, z] mm on the direction ref.
        features (list[str]): Names of seed features to pattern.
        count (int): Total instances including the seed.
        spacing (float): Distance between instances in mm.
    """

    direction_point: list[float] = Field(
        description=(
            "Point [x, y, z] in mm on the direction reference, typically a "
            "linear edge."
        )
    )
    features: list[str] = Field(description="Names of seed features to pattern")
    count: int = Field(description="Total number of instances, including the seed")
    spacing: float = Field(description="Distance between instances in mm")

    def model_post_init(self, __context: Any) -> None:
        if len(self.direction_point) != 3:
            raise ValueError("direction_point must be [x, y, z]")
        if not self.features:
            raise ValueError("at least one feature is required")
        if self.count < 1:
            raise ValueError("count must be >= 1")
        if self.spacing <= 0:
            raise ValueError("spacing must be positive")


class ShellInput(BaseModel):
    """Input schema for a shell operation.

    Attributes:
        thickness (float): Wall thickness in mm.
        face_points (list[list[float]]): Points on faces to remove.
        outward (bool): Thicken outward instead of inward.
    """

    thickness: float = Field(description="Wall thickness in mm")
    face_points: list[list[float]] = Field(
        default_factory=list,
        description=(
            "Faces to remove, located by a point [x, y, z] in mm on each. "
            "Empty shells the body closed (no opening)."
        ),
    )
    outward: bool = Field(
        default=False, description="Add thickness outward instead of inward"
    )

    def model_post_init(self, __context: Any) -> None:
        if self.thickness <= 0:
            raise ValueError("thickness must be positive")
        if any(len(p) != 3 for p in self.face_points):
            raise ValueError("each face point must be [x, y, z]")


class DraftInput(BaseModel):
    """Input schema for a neutral-plane draft operation.

    Attributes:
        angle (float): Draft angle in degrees.
        neutral_plane (str): Name of the neutral plane/planar face.
        face_points (list[list[float]]): Points on faces to draft.
        flip (bool): Reverse the draft direction.
    """

    angle: float = Field(description="Draft angle in degrees")
    neutral_plane: str = Field(
        description="Neutral plane name, e.g. 'Top Plane'"
    )
    face_points: list[list[float]] = Field(
        description="Faces to draft, located by a point [x, y, z] in mm on each"
    )
    flip: bool = Field(default=False, description="Reverse the draft direction")

    def model_post_init(self, __context: Any) -> None:
        if not self.neutral_plane:
            raise ValueError("neutral_plane is required")
        if not self.face_points:
            raise ValueError("at least one face point is required")
        if any(len(p) != 3 for p in self.face_points):
            raise ValueError("each face point must be [x, y, z]")


class CreateAssemblyInput(CompatInput):
    """Input schema for creating a new assembly.

    Attributes:
        components (list[str]): The components value.
        name (str): The name value.
        template (str | None): The template value.
    """

    name: str = Field(description="Name for the new assembly")
    template: str | None = Field(
        default=None, description="Assembly template file path"
    )
    components: list[str] = Field(default_factory=list, description="Component list")


class CreateDrawingInput(CompatInput):
    """Input schema for creating a new drawing.

    Attributes:
        model_path (str | None): The model path value.
        name (str): The name value.
        sheet_format (str | None): The sheet format value.
        template (str | None): The template value.
    """

    name: str = Field(description="Name for the new drawing")
    template: str | None = Field(default=None, description="Drawing template file path")
    model_path: str | None = Field(default=None, description="Source model path")
    sheet_format: str | None = Field(default=None, description="Sheet format template")


async def register_modeling_tools(
    mcp: FastMCP, adapter: SolidWorksAdapter, config: dict[str, Any]
) -> int:
    """Register modeling tools with FastMCP.

    Registers comprehensive modeling tools for SolidWorks automation including model
    creation, feature creation, and model management operations.

    Args:
        mcp (FastMCP): The mcp value.
        adapter (SolidWorksAdapter): Adapter instance used for the operation.
        config (dict[str, Any]): Configuration values for the operation.

    Returns:
        int: The computed numeric result.

    Example:
                        ```python
                        from solidworks_mcp.tools.modeling import register_modeling_tools

                        tool_count = await register_modeling_tools(mcp, adapter, config)
                        print(f"Registered {tool_count} modeling tools")
                        ```
    """
    tool_count = 0

    @mcp.tool()
    async def open_model(input_data: OpenModelInput) -> dict[str, Any]:
        """Open a SolidWorks model (part, assembly, or drawing).

        Opens an existing SolidWorks file and makes it the active document for further
        operations. Supports all standard SolidWorks file formats and provides detailed model
        information upon successful opening.

        Args:
            input_data (OpenModelInput): The input data value.

        Returns:
            dict[str, Any]: A dictionary containing the resulting values.

        Example:
                            ```python
                            result = await open_model({
                                "file_path": "C:/Models/bracket.sldprt"
                            })

                            if result["status"] == "success":
                                model = result["model"]
                                print(f"Opened {model['type']}: {model['name']}")
                                print(f"Configuration: {model['configuration']}")
                            ```

                        Note:
                            File path must be absolute and accessible to SolidWorks.
                            Model becomes the active document for subsequent operations.
        """
        try:
            input_data = _normalize_input(input_data, OpenModelInput)
            result = await adapter.open_model(input_data.file_path)

            if result.is_success:
                model = result.data
                title = _result_value(
                    model, "title", "name", default=input_data.file_path
                )
                model_type = _result_value(model, "type", default="Part")
                path = _result_value(
                    model, "path", "file_path", default=input_data.file_path
                )
                configuration = _result_value(model, "configuration", default="Default")
                return {
                    "status": "success",
                    "message": f"Opened {model_type}: {title}",
                    "model": {
                        "title": title,
                        "name": title,
                        "type": model_type,
                        "path": path,
                        "configuration": configuration,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to open model: {result.error}",
                }

        except Exception as e:
            logger.error(f"Error in open_model tool: {e}")
            return {
                "status": "error",
                "message": f"Unexpected error: {str(e)}",
            }

    @mcp.tool()
    async def create_part(input_data: CreatePartInput) -> dict[str, Any]:
        """Create a new SolidWorks part document.

        Creates a new SolidWorks part document using the default part template. The new part
        becomes the active document and is ready for modeling operations such as sketch creation
        and feature addition.

        Args:
            input_data (CreatePartInput): The input data value.

        Returns:
            dict[str, Any]: A dictionary containing the resulting values.

        Example:
                            ```python
                            result = await create_part()

                            if result["status"] == "success":
                                part = result["model"]
                                print(f"Created new part: {part['name']}")
                                # Ready for sketching and feature creation
                            ```

                        Note:
                            - Uses default SolidWorks part template
                            - Part document is created in memory (not saved)
                            - Use save operations to persist to disk
                            - Subsequent modeling operations will apply to this part
        """
        try:
            input_data = _normalize_input(input_data, CreatePartInput)
            result = await adapter.create_part(input_data.name, input_data.units)

            if result.is_success:
                model = result.data
                part_name = _result_value(model, "name", default=input_data.name)
                units = _result_value(model, "units", default=input_data.units or "mm")
                return {
                    "status": "success",
                    "message": f"Created new part: {part_name}",
                    "part": {
                        "name": part_name,
                        "units": units,
                        "material": input_data.material,
                        "template": input_data.template,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create part: {result.error}",
                }

        except Exception as e:
            logger.error(f"Error in create_part tool: {e}")
            return {
                "status": "error",
                "message": f"Unexpected error: {str(e)}",
            }

    @mcp.tool()
    async def create_assembly(input_data: CreateAssemblyInput) -> dict[str, Any]:
        """Create a new SolidWorks assembly document.

        Creates a new SolidWorks assembly document using the default assembly template. The new
        assembly becomes the active document and is ready for component insertion, mating, and
        assembly-level operations.

        Args:
            input_data (CreateAssemblyInput): The input data value.

        Returns:
            dict[str, Any]: A dictionary containing the resulting values.

        Example:
                            ```python
                            result = await create_assembly()

                            if result["status"] == "success":
                                assembly = result["model"]
                                print(f"Created new assembly: {assembly['name']}")
                                # Ready for component insertion and mating
                            ```

                        Note:
                            - Uses default SolidWorks assembly template
                            - Assembly document is created in memory (not saved)
                            - Use save operations to persist to disk
                            - Ready for component insertion and mate creation
                            - Assembly tree will initially be empty

                        This tool creates a new assembly document using the default assembly template.
                        The new assembly will become the active document.
        """
        try:
            input_data = _normalize_input(input_data, CreateAssemblyInput)
            result = await adapter.create_assembly(input_data.name)

            if result.is_success:
                model = result.data
                assembly_name = _result_value(model, "name", default=input_data.name)
                return {
                    "status": "success",
                    "message": f"Created new assembly: {assembly_name}",
                    "assembly": {
                        "name": assembly_name,
                        "components": input_data.components,
                        "template": input_data.template,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create assembly: {result.error}",
                }

        except Exception as e:
            logger.error(f"Error in create_assembly tool: {e}")
            return {
                "status": "error",
                "message": f"Unexpected error: {str(e)}",
            }

    @mcp.tool()
    async def create_drawing(input_data: CreateDrawingInput) -> dict[str, Any]:
        """Create a new SolidWorks drawing document.

        This tool creates a new drawing document using the default drawing template. The new
        drawing will become the active document.

        Args:
            input_data (CreateDrawingInput): The input data value.

        Returns:
            dict[str, Any]: A dictionary containing the resulting values.
        """
        try:
            input_data = _normalize_input(input_data, CreateDrawingInput)
            result = await adapter.create_drawing(input_data.name)

            if result.is_success:
                model = result.data
                drawing_name = _result_value(model, "name", default=input_data.name)
                sheet_format = _result_value(
                    model, "sheet_format", default=input_data.sheet_format
                )
                return {
                    "status": "success",
                    "message": f"Created new drawing: {drawing_name}",
                    "drawing": {
                        "name": drawing_name,
                        "model_path": input_data.model_path,
                        "sheet_format": sheet_format,
                        "template": input_data.template,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create drawing: {result.error}",
                }

        except Exception as e:
            logger.error(f"Error in create_drawing tool: {e}")
            return {
                "status": "error",
                "message": f"Unexpected error: {str(e)}",
            }

    @mcp.tool()
    async def close_model(input_data: CloseModelInput) -> dict[str, Any]:
        """Close the current SolidWorks model.

        Closes the currently active SolidWorks document with an option to save changes before
        closing. This is essential for proper model lifecycle management and preventing data
        loss.

        Args:
            input_data (CloseModelInput): The input data value.

        Returns:
            dict[str, Any]: A dictionary containing the resulting values.

        Example:
                            ```python
                            # Close without saving
                            result = await close_model({"save": False})

                            # Save and close
                            result = await close_model({"save": True})

                            if result["status"] == "success":
                                print(f"Model closed, saved: {result['saved']}")
                            ```

                        Note:
                            - Unsaved changes will be lost if save=False
                            - Always save important work before closing
                            - Model must be open to close it
        """
        try:
            input_data = _normalize_input(input_data, CloseModelInput)
            result = await adapter.close_model(input_data.save)

            if result.is_success:
                return {
                    "status": "success",
                    "message": "Model closed successfully",
                    "saved": input_data.save,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to close model: {result.error}",
                }

        except Exception as e:
            logger.error(f"Error in close_model tool: {e}")
            return {
                "status": "error",
                "message": f"Unexpected error: {str(e)}",
            }

    @mcp.tool()
    async def create_extrusion(input_data: CreateExtrusionInput) -> dict[str, Any]:
        """Create an extrusion feature from the active sketch.

        Creates a 3D extrusion feature (boss or cut) from the currently active 2D sketch.
        Supports advanced options like draft angles, thin features, bidirectional extrusion, and
        various end conditions for professional modeling workflows.

        Args:
            input_data (CreateExtrusionInput): The input data value.

        Returns:
            dict[str, Any]: A dictionary containing the resulting values.

        Example:
                            ```python
                            # Simple boss extrusion
                            result = await create_extrusion({
                                "depth": 25.0,
                                "merge_result": True
                            })

                            # Cut with draft angle
                            result = await create_extrusion({
                                "depth": 10.0,
                                "reverse_direction": True,
                                "draft_angle": 2.0
                            })

                            # Thin wall feature
                            result = await create_extrusion({
                                "depth": 50.0,
                                "thin_feature": True,
                                "thin_thickness": 2.0
                            })
                            ```
        """
        try:
            input_data = _normalize_input(input_data, CreateExtrusionInput)
            # Convert input to ExtrusionParameters
            params = ExtrusionParameters(
                depth=input_data.depth,
                draft_angle=input_data.draft_angle,
                reverse_direction=input_data.reverse_direction,
                both_directions=input_data.both_directions,
                thin_feature=input_data.thin_feature,
                thin_thickness=input_data.thin_thickness,
                end_condition=input_data.end_condition,
                merge_result=input_data.merge_result,
                feature_scope=False,
                auto_select=True,
            )

            result = await adapter.create_extrusion(params)

            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created extrusion: {_result_value(feature, 'feature_name', 'name', default='Extrusion')}",
                    "extrusion": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="Extrusion"
                        ),
                        "sketch": input_data.sketch_name,
                        "depth": input_data.depth,
                        "direction": input_data.direction,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create extrusion: {result.error}",
                }

        except Exception as e:
            logger.error(f"Error in create_extrusion tool: {e}")
            return {
                "status": "error",
                "message": f"Unexpected error: {str(e)}",
            }

    @mcp.tool()
    async def create_revolve(input_data: CreateRevolveInput) -> dict[str, Any]:
        """Create a revolve feature from the active sketch.

        Creates a 3D revolve feature by rotating the active 2D sketch profile around a specified
        axis of revolution. Supports full and partial revolves, thin features, and bidirectional
        revolution for comprehensive rotational modeling.

        Args:
            input_data (CreateRevolveInput): The input data value.

        Returns:
            dict[str, Any]: A dictionary containing the resulting values.

        Example:
                            ```python
                            # Full revolution (cylinder)
                            result = await create_revolve({
                                "angle": 360.0,
                                "merge_result": True
                            })

                            # Partial revolution (arc section)
                            result = await create_revolve({
                                "angle": 120.0,
                                "both_directions": True
                            })

                            # Thin wall revolution (pipe)
                            result = await create_revolve({
                                "angle": 360.0,
                                "thin_feature": True,
                                "thin_thickness": 3.0
                            })
                            ```
        """
        try:
            input_data = _normalize_input(input_data, CreateRevolveInput)
            # Convert input to RevolveParameters
            params = RevolveParameters(
                angle=input_data.angle,
                reverse_direction=input_data.reverse_direction,
                both_directions=input_data.both_directions,
                thin_feature=input_data.thin_feature,
                thin_thickness=input_data.thin_thickness,
                merge_result=input_data.merge_result,
            )

            result = await adapter.create_revolve(params)

            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created revolve: {_result_value(feature, 'feature_name', 'name', default='Revolve')}",
                    "revolve": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="Revolve"
                        ),
                        "sketch": input_data.sketch_name,
                        "axis_entity": input_data.axis_entity,
                        "angle": input_data.angle,
                        "direction": input_data.direction,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create revolve: {result.error}",
                }

        except Exception as e:
            logger.error(f"Error in create_revolve tool: {e}")
            return {
                "status": "error",
                "message": f"Unexpected error: {str(e)}",
            }

    @mcp.tool()
    async def get_dimension(input_data: GetDimensionInput) -> dict[str, Any]:
        """Get the value of a dimension from the current model.

        Retrieves the current value of a named dimension from the active SolidWorks model.
        Dimensions can be from sketches, features, or global dimensions. Useful for parametric
        modeling and design validation.

        Args:
            input_data (GetDimensionInput): The input data value.

        Returns:
            dict[str, Any]: A dictionary containing the resulting values.

        Example:
                            ```python
                            # Get sketch dimension
                            result = await get_dimension({
                                "name": "D1@Sketch1"
                            })

                            if result["status"] == "success":
                                dim = result["dimension"]
                                print(f"Dimension {dim['name']}: {dim['value']} {dim['units']}")

                            # Get feature dimension
                            result = await get_dimension({
                                "name": "D1@Boss-Extrude1"
                            })
                            ```
        """
        try:
            input_data = _normalize_input(input_data, GetDimensionInput)
            if not input_data.name:
                return {"status": "error", "message": "Dimension name is required"}
            result = await adapter.get_dimension(input_data.name)

            if result.is_success:
                value = result.data
                dimension_value = _result_value(value, "value", default=value)
                dimension_units = _result_value(value, "units", default="mm")
                return {
                    "status": "success",
                    "message": f"Dimension {input_data.name} = {dimension_value} {dimension_units}",
                    "dimension": {
                        "name": input_data.name,
                        "value": dimension_value,
                        "units": dimension_units,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to get dimension: {result.error}",
                }

        except Exception as e:
            logger.error(f"Error in get_dimension tool: {e}")
            return {
                "status": "error",
                "message": f"Unexpected error: {str(e)}",
            }

    @mcp.tool()
    async def set_dimension(input_data: SetDimensionInput) -> dict[str, Any]:
        """Set the value of a dimension in the current model.

        This tool modifies the value of a named dimension and rebuilds the model. Use this to
        parametrically modify your model dimensions.

        Args:
            input_data (SetDimensionInput): The input data value.

        Returns:
            dict[str, Any]: A dictionary containing the resulting values.
        """
        try:
            input_data = _normalize_input(input_data, SetDimensionInput)
            if not input_data.name:
                return {"status": "error", "message": "Dimension name is required"}
            result = await adapter.set_dimension(input_data.name, input_data.value)

            if result.is_success:
                payload = result.data
                return {
                    "status": "success",
                    "message": f"Set dimension {input_data.name} = {input_data.value} mm",
                    "dimension_update": {
                        "name": input_data.name,
                        "old_value": _result_value(payload, "old_value"),
                        "new_value": _result_value(
                            payload, "new_value", default=input_data.value
                        ),
                        "units": input_data.units or "mm",
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to set dimension: {result.error}",
                }

        except Exception as e:
            logger.error(f"Error in set_dimension tool: {e}")
            return {
                "status": "error",
                "message": f"Unexpected error: {str(e)}",
            }

    @mcp.tool()
    async def create_cut_extrude(input_data: CreateCutExtrudeInput) -> dict[str, Any]:
        """Cut material from the active model using the current sketch profile.

        Creates a Cut-Extrude feature (Insert > Cut > Extrude) from the active sketch.
        Use this after exit_sketch when you want to remove material — e.g. to create
        windows, holes, slots, or any through/blind cut in an existing solid body.

        Args:
            input_data (CreateCutExtrudeInput): Depth, direction and draft parameters.

        Returns:
            dict[str, Any]: Status and feature details.

        Example:
            ```python
            # Cut a blind pocket 10 mm deep
            result = await create_cut_extrude({"depth": 10.0})

            # Through-all cut (use a depth larger than the solid)
            result = await create_cut_extrude({"depth": 200.0})
            ```
        """
        try:
            input_data = _normalize_input(input_data, CreateCutExtrudeInput)
            params = ExtrusionParameters(
                depth=input_data.depth,
                draft_angle=input_data.draft_angle,
                reverse_direction=input_data.reverse_direction,
                both_directions=False,
                thin_feature=False,
                thin_thickness=None,
                end_condition=input_data.end_condition,
                merge_result=False,
                feature_scope=False,
                auto_select=True,
            )
            result = await adapter.create_cut_extrude(params)
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created cut-extrude: {_result_value(feature, 'feature_name', 'name', default='Cut-Extrude')}",
                    "cut_extrude": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="Cut-Extrude"
                        ),
                        "depth": input_data.depth,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create cut-extrude: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in create_cut_extrude tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def add_fillet(input_data: AddFilletInput) -> dict[str, Any]:
        """Add a constant-radius fillet (rounded edge) to the current model.

        Rounds the edges located by the given points. Each edge is identified by
        a point ``[x, y, z]`` in millimetres lying on it, because SolidWorks
        edges have no caller-stable name.

        Args:
            input_data (AddFilletInput): Radius and edge points.

        Returns:
            dict[str, Any]: Status and feature details.

        Example:
            ```python
            # Fillet the edge passing through (25, 0, 50) mm with a 2 mm radius
            result = await add_fillet({"radius": 2.0, "edge_points": [[25, 0, 50]]})
            ```
        """
        try:
            input_data = _normalize_input(input_data, AddFilletInput)
            result = await adapter.add_fillet(
                input_data.radius, input_data.edge_points
            )
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created fillet: {_result_value(feature, 'feature_name', 'name', default='Fillet')}",
                    "fillet": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="Fillet"
                        ),
                        "radius": input_data.radius,
                        "edge_points": input_data.edge_points,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to add fillet: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in add_fillet tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def add_chamfer(input_data: AddChamferInput) -> dict[str, Any]:
        """Add an equal-distance (45°) chamfer to the current model.

        Bevels the edges located by the given points. Each edge is identified by
        a point ``[x, y, z]`` in millimetres lying on it.

        Args:
            input_data (AddChamferInput): Distance and edge points.

        Returns:
            dict[str, Any]: Status and feature details.

        Example:
            ```python
            # Chamfer the edge through (25, 0, 50) mm with a 1.5 mm leg
            result = await add_chamfer({"distance": 1.5, "edge_points": [[25, 0, 50]]})
            ```
        """
        try:
            input_data = _normalize_input(input_data, AddChamferInput)
            result = await adapter.add_chamfer(
                input_data.distance, input_data.edge_points
            )
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created chamfer: {_result_value(feature, 'feature_name', 'name', default='Chamfer')}",
                    "chamfer": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="Chamfer"
                        ),
                        "distance": input_data.distance,
                        "edge_points": input_data.edge_points,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to add chamfer: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in add_chamfer tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def mirror_feature(input_data: MirrorFeatureInput) -> dict[str, Any]:
        """Mirror existing features about a reference plane (3D mirror).

        Distinct from ``sketch_mirror`` (which reflects 2D sketch entities).
        Features to mirror are named (e.g. ``"Boss-Extrude1"``); the mirror
        plane is named (e.g. ``"Right Plane"``).

        Args:
            input_data (MirrorFeatureInput): Plane, features, and options.

        Returns:
            dict[str, Any]: Status and feature details.

        Example:
            ```python
            result = await mirror_feature({
                "plane": "Right Plane",
                "features": ["Boss-Extrude1"],
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, MirrorFeatureInput)
            result = await adapter.mirror_feature(
                MirrorFeatureParameters(
                    plane=input_data.plane,
                    features=input_data.features,
                    merge=input_data.merge,
                    geometry_pattern=input_data.geometry_pattern,
                )
            )
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created mirror: {_result_value(feature, 'feature_name', 'name', default='Mirror')}",
                    "mirror": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="Mirror"
                        ),
                        "plane": input_data.plane,
                        "features": input_data.features,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to mirror feature: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in mirror_feature tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def circular_pattern_feature(
        input_data: CircularPatternInput,
    ) -> dict[str, Any]:
        """Create a circular pattern of features about an axis.

        The rotation axis is a named reference axis (axis_name, preferred)
        or located by a point on a cylindrical face or a linear edge; the
        seed features are named.

        Args:
            input_data (CircularPatternInput): Axis ref, features, count, angle.

        Returns:
            dict[str, Any]: Status and feature details.

        Example:
            ```python
            # 6 copies evenly around a reference axis from create_axis
            result = await circular_pattern_feature({
                "axis_name": "Axis1",
                "features": ["Cut-Extrude1"],
                "count": 6,
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, CircularPatternInput)
            result = await adapter.circular_pattern_feature(
                CircularPatternParameters(
                    axis_point=input_data.axis_point,
                    axis_name=input_data.axis_name,
                    features=input_data.features,
                    count=input_data.count,
                    angle=input_data.angle,
                    equal_spacing=input_data.equal_spacing,
                    geometry_pattern=input_data.geometry_pattern,
                )
            )
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created circular pattern: {_result_value(feature, 'feature_name', 'name', default='CircularPattern')}",
                    "circular_pattern": {
                        "name": _result_value(
                            feature,
                            "feature_name",
                            "name",
                            default="CircularPattern",
                        ),
                        "count": input_data.count,
                        "angle": input_data.angle,
                        "features": input_data.features,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create circular pattern: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in circular_pattern_feature tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def linear_pattern_feature(
        input_data: LinearPatternInput,
    ) -> dict[str, Any]:
        """Create a linear pattern of features along a direction.

        The direction is located by a point on a linear edge (or axis); the
        seed features are named.

        Args:
            input_data (LinearPatternInput): Direction point, features, count, spacing.

        Returns:
            dict[str, Any]: Status and feature details.

        Example:
            ```python
            # 4 copies 20 mm apart along the edge through (50, 0, 0)
            result = await linear_pattern_feature({
                "direction_point": [50, 0, 0],
                "features": ["Cut-Extrude1"],
                "count": 4,
                "spacing": 20.0,
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, LinearPatternInput)
            result = await adapter.linear_pattern_feature(
                LinearPatternParameters(
                    direction_point=input_data.direction_point,
                    features=input_data.features,
                    count=input_data.count,
                    spacing=input_data.spacing,
                )
            )
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created linear pattern: {_result_value(feature, 'feature_name', 'name', default='LinearPattern')}",
                    "linear_pattern": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="LinearPattern"
                        ),
                        "count": input_data.count,
                        "spacing": input_data.spacing,
                        "features": input_data.features,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create linear pattern: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in linear_pattern_feature tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def shell(input_data: ShellInput) -> dict[str, Any]:
        """Hollow out the solid body to a wall thickness, optionally opening faces.

        Faces to remove are located by a point on each; an empty face list
        produces a closed hollow.

        Args:
            input_data (ShellInput): Thickness, faces to remove, direction.

        Returns:
            dict[str, Any]: Status and feature details.

        Example:
            ```python
            # 2 mm wall, opening the top face at (0, 0, 100)
            result = await shell({"thickness": 2.0, "face_points": [[0, 0, 100]]})
            ```
        """
        try:
            input_data = _normalize_input(input_data, ShellInput)
            result = await adapter.shell(
                ShellParameters(
                    thickness=input_data.thickness,
                    face_points=input_data.face_points,
                    outward=input_data.outward,
                )
            )
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created shell: {_result_value(feature, 'feature_name', 'name', default='Shell')}",
                    "shell": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="Shell"
                        ),
                        "thickness": input_data.thickness,
                        "face_points": input_data.face_points,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create shell: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in shell tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def draft(input_data: DraftInput) -> dict[str, Any]:
        """Apply a neutral-plane draft (taper) to selected faces.

        The neutral plane (which stays fixed) is named; faces to taper are
        located by a point on each.

        Args:
            input_data (DraftInput): Angle, neutral plane, faces, direction.

        Returns:
            dict[str, Any]: Status and feature details.

        Example:
            ```python
            # 3-degree draft on the side face at (25, 0, 50), pivoting about Top
            result = await draft({
                "angle": 3.0,
                "neutral_plane": "Top Plane",
                "face_points": [[25, 0, 50]],
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, DraftInput)
            result = await adapter.draft(
                DraftParameters(
                    angle=input_data.angle,
                    neutral_plane=input_data.neutral_plane,
                    face_points=input_data.face_points,
                    flip=input_data.flip,
                )
            )
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created draft: {_result_value(feature, 'feature_name', 'name', default='Draft')}",
                    "draft": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="Draft"
                        ),
                        "angle": input_data.angle,
                        "neutral_plane": input_data.neutral_plane,
                        "face_points": input_data.face_points,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create draft: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in draft tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def create_sweep(input_data: CreateSweepInput) -> dict[str, Any]:
        """Sweep the active profile sketch along a named path sketch.

        Creates a swept boss/protrusion (Insert > Boss/Base > Sweep). Requires
        two sketches in the active part: a closed profile sketch and an open
        path sketch named by ``path``. The profile is inferred as the sketch
        that is not the path (in the usual "draw profile, draw path, sweep"
        flow this is unambiguous). Optionally applies a constant twist along
        the path.

        Args:
            input_data (CreateSweepInput): Path name and twist/merge options.

        Returns:
            dict[str, Any]: Status and feature details.

        Example:
            ```python
            # Sweep a circular profile along "Sketch2"
            result = await create_sweep({"path": "Sketch2"})

            # Sweep with a 90-degree twist along the path
            result = await create_sweep({
                "path": "Sketch2",
                "twist_along_path": True,
                "twist_angle": 90.0,
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, CreateSweepInput)
            params = SweepParameters(
                path=input_data.path,
                twist_along_path=input_data.twist_along_path,
                twist_angle=input_data.twist_angle,
                merge_result=input_data.merge_result,
            )
            result = await adapter.create_sweep(params)
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created sweep: {_result_value(feature, 'feature_name', 'name', default='Sweep')}",
                    "sweep": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="Sweep"
                        ),
                        "path": input_data.path,
                        "twist_along_path": input_data.twist_along_path,
                        "twist_angle": input_data.twist_angle,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create sweep: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in create_sweep tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def create_loft(input_data: CreateLoftInput) -> dict[str, Any]:
        """Loft a solid between two or more profile sketches.

        Creates a lofted boss/protrusion (Insert > Boss/Base > Loft) blending
        the listed profile sketches in order. Each profile must be a closed
        contour. Optional guide curves shape the transition between profiles.

        Args:
            input_data (CreateLoftInput): Profile names, optional guide curves,
                and tangency/merge options.

        Returns:
            dict[str, Any]: Status and feature details.

        Example:
            ```python
            # Loft between two profiles (e.g. a tapered bevel)
            result = await create_loft({"profiles": ["Sketch1", "Sketch2"]})

            # Loft with guide curves
            result = await create_loft({
                "profiles": ["Sketch1", "Sketch2"],
                "guide_curves": ["Sketch3"],
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, CreateLoftInput)
            params = LoftParameters(
                profiles=input_data.profiles,
                guide_curves=input_data.guide_curves,
                start_tangent=input_data.start_tangent,
                end_tangent=input_data.end_tangent,
                merge_result=input_data.merge_result,
            )
            result = await adapter.create_loft(params)
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created loft: {_result_value(feature, 'feature_name', 'name', default='Loft')}",
                    "loft": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="Loft"
                        ),
                        "profiles": input_data.profiles,
                        "guide_curves": input_data.guide_curves,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create loft: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in create_loft tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    tool_count = 18  # Number of tools registered
    return tool_count
