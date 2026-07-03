"""Reference-geometry tools for SolidWorks MCP Server (Phase 3).

Provides tools for creating datum features: constraint-based reference
planes, reference axes, reference points, and numerically positioned
coordinate systems.
"""

from typing import Any

from fastmcp import FastMCP
from loguru import logger
from pydantic import BaseModel, Field

from ..adapters.base import (
    CreateAxisParameters,
    CreateCoordinateSystemParameters,
    CreatePlaneParameters,
    CreateReferencePointParameters,
    SolidWorksAdapter,
)
from .modeling import _normalize_input, _result_value

PLANE_MODES = ("offset", "angle", "three_point", "parallel_point")
AXIS_MODES = ("two_planes", "cylindrical_face", "two_points", "edge")
POINT_MODES = ("face_center", "arc_center", "along_curve")
ALONG_TYPES = ("distance", "percentage", "evenly")


class CreatePlaneInput(BaseModel):
    """Input schema for creating a constraint-based reference plane.

    Attributes:
        mode (str): The construction mode.
        base_plane (str): The base plane name.
        offset (float): The offset distance in mm.
        angle (float): The rotation angle in degrees.
        edge_point (list[float] | None): Point on the pivot edge in mm.
        points (list[list[float]]): Vertex points in mm.
    """

    mode: str = Field(
        description=(
            "Construction mode: 'offset' (parallel to base_plane at a "
            "distance), 'angle' (rotated about an edge from base_plane), "
            "'three_point' (through three vertices), or 'parallel_point' "
            "(parallel to base_plane through a vertex)"
        )
    )
    base_plane: str = Field(
        default="",
        description=(
            "Name of the base reference plane or planar face (e.g. 'Front "
            "Plane') — required for offset/angle/parallel_point modes"
        ),
    )
    offset: float = Field(
        default=0.0,
        description=(
            "Signed offset distance in millimetres (offset mode); the sign "
            "selects the side of base_plane — negative builds the far side"
        ),
    )
    angle: float = Field(
        default=0.0,
        description=(
            "Signed rotation in degrees (angle mode); the sign selects which "
            "of the two valid angled planes is built — negative builds the "
            "alternate side"
        ),
    )
    edge_point: list[float] | None = Field(
        default=None,
        description="Point [x, y, z] in mm on the pivot edge (angle mode)",
    )
    points: list[list[float]] = Field(
        default_factory=list,
        description=(
            "Vertex points [x, y, z] in mm — three for three_point mode, "
            "one for parallel_point mode"
        ),
    )
    def model_post_init(self, __context: Any) -> None:
        """Validate mode-specific requirements.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the mode is unknown or its references are missing.
        """
        if self.mode not in PLANE_MODES:
            raise ValueError(f"mode must be one of {PLANE_MODES}")
        if self.mode in ("offset", "angle", "parallel_point") and not self.base_plane:
            raise ValueError(f"mode {self.mode!r} requires base_plane")
        if self.mode == "angle" and not self.edge_point:
            raise ValueError("mode 'angle' requires edge_point")
        if self.mode == "three_point" and len(self.points) != 3:
            raise ValueError("mode 'three_point' requires exactly 3 points")
        if self.mode == "parallel_point" and len(self.points) != 1:
            raise ValueError("mode 'parallel_point' requires exactly 1 point")


class CreateAxisInput(BaseModel):
    """Input schema for creating a reference axis.

    Attributes:
        mode (str): The construction mode.
        planes (list[str]): Two plane names.
        face_point (list[float] | None): Point on the cylindrical face in mm.
        points (list[list[float]]): Two vertex points in mm.
        edge_point (list[float] | None): Point on the linear edge in mm.
    """

    mode: str = Field(
        description=(
            "Construction mode: 'two_planes' (intersection of two planes), "
            "'cylindrical_face' (axis of a cylinder located by a point on "
            "it), 'two_points' (through two vertices), or 'edge' (along a "
            "linear edge located by a point on it)"
        )
    )
    planes: list[str] = Field(
        default_factory=list,
        description="Two plane names (two_planes mode), e.g. ['Front Plane', 'Top Plane']",
    )
    face_point: list[float] | None = Field(
        default=None,
        description="Point [x, y, z] in mm on the cylindrical face (cylindrical_face mode)",
    )
    points: list[list[float]] = Field(
        default_factory=list,
        description="Two vertex points [x, y, z] in mm (two_points mode)",
    )
    edge_point: list[float] | None = Field(
        default=None,
        description="Point [x, y, z] in mm on the edge (edge mode)",
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate mode-specific requirements.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the mode is unknown or its references are missing.
        """
        if self.mode not in AXIS_MODES:
            raise ValueError(f"mode must be one of {AXIS_MODES}")
        if self.mode == "two_planes" and len(self.planes) != 2:
            raise ValueError("mode 'two_planes' requires exactly 2 plane names")
        if self.mode == "cylindrical_face" and not self.face_point:
            raise ValueError("mode 'cylindrical_face' requires face_point")
        if self.mode == "two_points" and len(self.points) != 2:
            raise ValueError("mode 'two_points' requires exactly 2 points")
        if self.mode == "edge" and not self.edge_point:
            raise ValueError("mode 'edge' requires edge_point")


class CreateReferencePointInput(BaseModel):
    """Input schema for creating reference point(s).

    Attributes:
        mode (str): The construction mode.
        face_point (list[float] | None): Point on the face in mm.
        edge_point (list[float] | None): Point on the edge in mm.
        along (str): Distribution along the curve.
        distance (float): Distance in mm.
        percentage (float): Percentage of curve length.
        count (int): Number of evenly distributed points.
    """

    mode: str = Field(
        description=(
            "Construction mode: 'face_center' (center of a face located by "
            "a point on it), 'arc_center' (center of a circular edge), or "
            "'along_curve' (point(s) along an edge)"
        )
    )
    face_point: list[float] | None = Field(
        default=None,
        description="Point [x, y, z] in mm on the face (face_center mode)",
    )
    edge_point: list[float] | None = Field(
        default=None,
        description="Point [x, y, z] in mm on the edge (arc_center/along_curve modes)",
    )
    along: str = Field(
        default="distance",
        description=(
            "along_curve distribution: 'distance' (at `distance` mm), "
            "'percentage' (at `percentage` % of length), or 'evenly' "
            "(`count` evenly distributed points)"
        ),
    )
    distance: float = Field(
        default=0.0, description="Distance in millimetres (along='distance')"
    )
    percentage: float = Field(
        default=0.0, description="Percentage 0-100 of curve length (along='percentage')"
    )
    count: int = Field(
        default=1, description="Number of points (along='evenly')"
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate mode-specific requirements.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the mode is unknown or its references are missing.
        """
        if self.mode not in POINT_MODES:
            raise ValueError(f"mode must be one of {POINT_MODES}")
        if self.mode == "face_center" and not self.face_point:
            raise ValueError("mode 'face_center' requires face_point")
        if self.mode in ("arc_center", "along_curve") and not self.edge_point:
            raise ValueError(f"mode {self.mode!r} requires edge_point")
        if self.mode == "along_curve" and self.along not in ALONG_TYPES:
            raise ValueError(f"along must be one of {ALONG_TYPES}")
        if self.along == "evenly" and self.count < 1:
            raise ValueError("count must be >= 1")


class CreateCoordinateSystemInput(BaseModel):
    """Input schema for creating a coordinate-system feature.

    Attributes:
        position (list[float]): Origin in mm.
        rotation (list[float]): Rotation about the global axes in degrees.
    """

    position: list[float] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0],
        description="Origin [x, y, z] in millimetres relative to the global origin",
    )
    rotation: list[float] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0],
        description="Rotation [rx, ry, rz] in degrees about the global axes",
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate vector lengths.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When position or rotation is not 3 elements.
        """
        if len(self.position) != 3:
            raise ValueError("position must have exactly 3 elements")
        if len(self.rotation) != 3:
            raise ValueError("rotation must have exactly 3 elements")


async def register_reference_geometry_tools(
    mcp: FastMCP, adapter: SolidWorksAdapter, config: Any
) -> int:
    """Register reference-geometry tools with the MCP server.

    Args:
        mcp (FastMCP): The mcp value.
        adapter (SolidWorksAdapter): Adapter instance used for the operation.
        config (Any): Configuration values for the operation.

    Returns:
        int: The number of tools registered.
    """

    @mcp.tool()
    async def create_plane(input_data: CreatePlaneInput) -> dict[str, Any]:
        """Create a constraint-based reference plane (datum plane).

        Four modes: 'offset' builds parallel to a named base plane at a
        distance (the workhorse for laying out repeated channel datums);
        'angle' rotates from a base plane about an edge located by a point;
        'three_point' passes through three vertices; 'parallel_point' is
        parallel to a base plane through a vertex.

        Args:
            input_data (CreatePlaneInput): Mode, references, distance/angle.

        Returns:
            dict[str, Any]: Status and plane details.

        Example:
            ```python
            # Datum 16 mm in front of the Front plane
            result = await create_plane({
                "mode": "offset",
                "base_plane": "Front Plane",
                "offset": 16.0,
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, CreatePlaneInput)
            result = await adapter.create_plane(
                CreatePlaneParameters(
                    mode=input_data.mode,
                    base_plane=input_data.base_plane,
                    offset=input_data.offset,
                    angle=input_data.angle,
                    edge_point=input_data.edge_point or [],
                    points=input_data.points,
                )
            )
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created plane: {_result_value(feature, 'feature_name', 'name', default='Plane')}",
                    "plane": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="Plane"
                        ),
                        "mode": input_data.mode,
                        "base_plane": input_data.base_plane,
                        "offset": input_data.offset,
                        "angle": input_data.angle,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create plane: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in create_plane tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def create_axis(input_data: CreateAxisInput) -> dict[str, Any]:
        """Create a reference axis (datum axis).

        Four modes: 'two_planes' takes the intersection of two named planes;
        'cylindrical_face' takes the axis of a cylinder/cone located by a
        point on it (e.g. a shaft surface); 'two_points' passes through two
        vertices; 'edge' runs along a linear edge located by a point.

        Args:
            input_data (CreateAxisInput): Mode and references.

        Returns:
            dict[str, Any]: Status and axis details.

        Example:
            ```python
            # Axis of a shaft through its outer cylindrical face
            result = await create_axis({
                "mode": "cylindrical_face",
                "face_point": [4.7625, 50.0, 0.0],
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, CreateAxisInput)
            result = await adapter.create_axis(
                CreateAxisParameters(
                    mode=input_data.mode,
                    planes=input_data.planes,
                    face_point=input_data.face_point or [],
                    points=input_data.points,
                    edge_point=input_data.edge_point or [],
                )
            )
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created axis: {_result_value(feature, 'feature_name', 'name', default='Axis')}",
                    "axis": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="Axis"
                        ),
                        "mode": input_data.mode,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create axis: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in create_axis tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def create_reference_point(
        input_data: CreateReferencePointInput,
    ) -> dict[str, Any]:
        """Create one or more reference points (datum points).

        Three modes: 'face_center' at the center of a face located by a point
        on it; 'arc_center' at the center of a circular edge; 'along_curve'
        along an edge — at a distance, a percentage of length, or several
        evenly distributed points.

        Args:
            input_data (CreateReferencePointInput): Mode, references,
                distribution.

        Returns:
            dict[str, Any]: Status and point details.

        Example:
            ```python
            # Center of a bore's circular edge
            result = await create_reference_point({
                "mode": "arc_center",
                "edge_point": [25.5, 0.0, 1.5],
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, CreateReferencePointInput)
            result = await adapter.create_reference_point(
                CreateReferencePointParameters(
                    mode=input_data.mode,
                    face_point=input_data.face_point or [],
                    edge_point=input_data.edge_point or [],
                    along=input_data.along,
                    distance=input_data.distance,
                    percentage=input_data.percentage,
                    count=input_data.count,
                )
            )
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created reference point: {_result_value(feature, 'feature_name', 'name', default='Point')}",
                    "reference_point": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="Point"
                        ),
                        "mode": input_data.mode,
                        "count": input_data.count,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create reference point: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in create_reference_point tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def create_coordinate_system(
        input_data: CreateCoordinateSystemInput,
    ) -> dict[str, Any]:
        """Create a coordinate-system feature at a numeric position/rotation.

        Positions the coordinate system relative to the global origin without
        requiring any selections — position in millimetres, rotation in
        degrees about the global axes.

        Args:
            input_data (CreateCoordinateSystemInput): Position and rotation.

        Returns:
            dict[str, Any]: Status and coordinate-system details.

        Example:
            ```python
            # Channel-1 frame: 16 mm along Z, rotated 90 deg about Y
            result = await create_coordinate_system({
                "position": [0.0, 0.0, 16.0],
                "rotation": [0.0, 90.0, 0.0],
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, CreateCoordinateSystemInput)
            result = await adapter.create_coordinate_system(
                CreateCoordinateSystemParameters(
                    position=input_data.position,
                    rotation=input_data.rotation,
                )
            )
            if result.is_success:
                feature = result.data
                return {
                    "status": "success",
                    "message": f"Created coordinate system: {_result_value(feature, 'feature_name', 'name', default='CoordSys')}",
                    "coordinate_system": {
                        "name": _result_value(
                            feature, "feature_name", "name", default="CoordSys"
                        ),
                        "position": input_data.position,
                        "rotation": input_data.rotation,
                    },
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create coordinate system: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in create_coordinate_system tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    tool_count = 4  # Number of tools registered
    return tool_count
