"""Base adapter interface for SolidWorks integration.

Defines the common interface that all SolidWorks adapters must implement, following the
adapter pattern from the original TypeScript implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class AdapterHealth(BaseModel):
    """Health status information for adapters.

    Attributes:
        average_response_time (float): The average response time value.
        connection_status (str): The connection status value.
        error_count (int): The error count value.
        healthy (bool): The healthy value.
        last_check (datetime): The last check value.
        metrics (dict[str, Any] | None): The metrics value.
        success_count (int): The success count value.
    """

    healthy: bool
    last_check: datetime
    error_count: int
    success_count: int
    average_response_time: float
    connection_status: str
    metrics: dict[str, Any] | None = None

    def __getitem__(self, key: str) -> Any:
        """Build internal getitem.

        Args:
            key (str): The key value.

        Returns:
            Any: The result produced by the operation.
        """
        if key == "status":
            return "healthy" if self.healthy else "unhealthy"
        if key == "connected":
            return self.connection_status == "connected"
        if key == "adapter_type":
            return (self.metrics or {}).get("adapter_type")
        if key == "version":
            return (self.metrics or {}).get("version", "mock-1.0")
        if key == "uptime":
            return (self.metrics or {}).get("uptime", 0.0)
        return self.model_dump().get(key)

    def __contains__(self, key: str) -> bool:
        """Build internal contains.

        Args:
            key (str): The key value.

        Returns:
            bool: True if contains, otherwise False.
        """
        legacy_keys = {"status", "connected", "adapter_type", "version", "uptime"}
        if key in legacy_keys:
            return True
        return key in self.model_dump()


class AdapterResultStatus(StrEnum):
    """Result status for adapter operations.

    Attributes:
        ERROR (Any): The error value.
        SUCCESS (Any): The success value.
        TIMEOUT (Any): The timeout value.
        WARNING (Any): The warning value.
    """

    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    TIMEOUT = "timeout"


@dataclass
class AdapterResult(Generic[T]):
    """Result wrapper for adapter operations.

    Attributes:
        data (T | None): The data value.
        error (str | None): The error value.
        execution_time (float | None): The execution time value.
        metadata (dict[str, Any] | None): The metadata value.
        status (AdapterResultStatus): The status value.
    """

    status: AdapterResultStatus
    data: T | None = None
    error: str | None = None
    execution_time: float | None = None
    metadata: dict[str, Any] | None = None

    @property
    def is_success(self) -> bool:
        """Check if operation was successful.

        Returns:
            bool: True if success, otherwise False.
        """
        return self.status == AdapterResultStatus.SUCCESS

    @property
    def is_error(self) -> bool:
        """Check if operation had an error.

        Returns:
            bool: True if error, otherwise False.
        """
        return self.status == AdapterResultStatus.ERROR


# SolidWorks data models
class SolidWorksModel(BaseModel):
    """SolidWorks model information.

    Attributes:
        configuration (str | None): The configuration value.
        is_active (bool): The is active value.
        name (str): The name value.
        path (str): The path value.
        properties (dict[str, Any] | None): The properties value.
        type (str): The type value.
    """

    path: str
    name: str
    type: str  # "Part", "Assembly", "Drawing"
    is_active: bool
    configuration: str | None = None
    properties: dict[str, Any] | None = None

    def __getitem__(self, key: str) -> Any:
        """Build internal getitem.

        Args:
            key (str): The key value.

        Returns:
            Any: The result produced by the operation.
        """
        if key == "title":
            return self.name
        if key == "units":
            return (self.properties or {}).get("units")
        return self.model_dump().get(key)


class SolidWorksFeature(BaseModel):
    """SolidWorks feature information.

    Attributes:
        id (str | None): The id value.
        name (str): The name value.
        parameters (dict[str, Any] | None): The parameters value.
        parent (str | None): The parent value.
        properties (dict[str, Any] | None): The properties value.
        type (str): The type value.
    """

    name: str
    type: str
    id: str | None = None
    parent: str | None = None
    properties: dict[str, Any] | None = None
    parameters: dict[str, Any] | None = None

    def __getitem__(self, key: str) -> Any:
        """Build internal getitem.

        Args:
            key (str): The key value.

        Returns:
            Any: The result produced by the operation.
        """
        if self.parameters and key in self.parameters:
            return self.parameters.get(key)
        return self.model_dump().get(key)


class ExtrusionParameters(BaseModel):
    """Parameters for extrusion operations.

    Attributes:
        auto_select (bool): The auto select value.
        both_directions (bool): The both directions value.
        depth (float): The depth value.
        draft_angle (float): The draft angle value.
        end_condition (str): The end condition value.
        feature_scope (bool): The feature scope value.
        merge_result (bool): The merge result value.
        reverse_direction (bool): The reverse direction value.
        thin_feature (bool): The thin feature value.
        thin_thickness (float | None): The thin thickness value.
        up_to_surface (str | None): The up to surface value.
    """

    depth: float
    draft_angle: float = 0.0
    reverse_direction: bool = False
    both_directions: bool = False
    thin_feature: bool = False
    thin_thickness: float | None = None
    auto_fillet_corners: bool = False
    fillet_corners_radius: float = 0.0
    end_condition: str = "Blind"
    up_to_surface: str | None = None
    merge_result: bool = True
    feature_scope: bool = False
    auto_select: bool = True


class RevolveParameters(BaseModel):
    """Parameters for revolve operations.

    Attributes:
        angle (float): The angle value.
        both_directions (bool): The both directions value.
        merge_result (bool): The merge result value.
        reverse_direction (bool): The reverse direction value.
        thin_feature (bool): The thin feature value.
        thin_thickness (float | None): The thin thickness value.
    """

    angle: float
    reverse_direction: bool = False
    both_directions: bool = False
    thin_feature: bool = False
    thin_thickness: float | None = None
    merge_result: bool = True


class SweepParameters(BaseModel):
    """Parameters for sweep operations.

    Attributes:
        merge_result (bool): The merge result value.
        path (str): The path value.
        twist_along_path (bool): The twist along path value.
        twist_angle (float): The twist angle value.
    """

    path: str
    twist_along_path: bool = False
    twist_angle: float = 0.0
    merge_result: bool = True


class LoftParameters(BaseModel):
    """Parameters for loft operations.

    Attributes:
        end_tangent (str | None): The end tangent value.
        guide_curves (list[str] | None): The guide curves value.
        merge_result (bool): The merge result value.
        profiles (list[str]): The profiles value.
        start_tangent (str | None): The start tangent value.
    """

    profiles: list[str]
    guide_curves: list[str] | None = None
    start_tangent: str | None = None
    end_tangent: str | None = None
    merge_result: bool = True


class MirrorFeatureParameters(BaseModel):
    """Parameters for a 3D mirror-feature operation.

    Mirrors existing features about a reference plane or planar face. Distinct
    from the sketch-level ``sketch_mirror`` (which reflects 2D sketch entities).

    Attributes:
        plane (str): Name of the mirror plane or planar face (e.g.
            ``"Right Plane"``). Selected under mark 2.
        features (list[str]): Names of the features to mirror (e.g.
            ``["Boss-Extrude1"]``). Selected under mark 1.
        geometry_pattern (bool): Mirror only the feature geometry rather than
            re-solving the whole feature.
        merge (bool): Merge resulting bodies into a single solid.
    """

    plane: str
    features: list[str]
    geometry_pattern: bool = False
    merge: bool = True


class CircularPatternParameters(BaseModel):
    """Parameters for a circular feature-pattern operation.

    Attributes:
        axis_point (list[float]): A point ``[x, y, z]`` in millimetres on the
            rotation-axis reference — a cylindrical face (uses its axis) or a
            linear edge. Selected under mark 1.
        features (list[str]): Names of the seed features to pattern. Selected
            under mark 4.
        count (int): Total number of instances, including the seed.
        angle (float): Total angular span in degrees when ``equal_spacing`` is
            true, otherwise the spacing between instances in degrees.
        equal_spacing (bool): Distribute instances equally across ``angle``.
    """

    axis_point: list[float]
    features: list[str]
    count: int
    angle: float = 360.0
    equal_spacing: bool = True


class LinearPatternParameters(BaseModel):
    """Parameters for a linear feature-pattern operation.

    Attributes:
        direction_point (list[float]): A point ``[x, y, z]`` in millimetres on
            the direction reference — typically a linear edge. Selected under
            mark 1.
        features (list[str]): Names of the seed features to pattern. Selected
            under mark 4.
        count (int): Total number of instances, including the seed.
        spacing (float): Distance between instances in millimetres.
    """

    direction_point: list[float]
    features: list[str]
    count: int
    spacing: float


class ShellParameters(BaseModel):
    """Parameters for a shell operation (hollow out a solid).

    Attributes:
        thickness (float): Wall thickness in millimetres.
        face_points (list[list[float]]): Points ``[x, y, z]`` in millimetres,
            one per face to remove (open the shell on). An empty list shells the
            body with no face removed (a closed hollow). Each is selected under
            mark 1.
        outward (bool): Add the thickness outward (grow the body) rather than
            inward.
    """

    thickness: float
    face_points: list[list[float]] = []
    outward: bool = False


class DraftParameters(BaseModel):
    """Parameters for a neutral-plane draft operation.

    Attributes:
        angle (float): Draft angle in degrees.
        neutral_plane (str): Name of the neutral plane or planar face that the
            draft pivots about (e.g. ``"Top Plane"``). Selected under mark 1.
        face_points (list[list[float]]): Points ``[x, y, z]`` in millimetres,
            one per face to draft. Each is selected under mark 2.
        flip (bool): Reverse the draft direction.
    """

    angle: float
    neutral_plane: str
    face_points: list[list[float]]
    flip: bool = False


class CreatePlaneParameters(BaseModel):
    """Parameters for a constraint-based reference-plane operation.

    Exactly one mode is used per call; the other mode's fields are ignored.

    Attributes:
        mode (str): One of ``"offset"`` (parallel to ``base_plane`` at
            ``offset``), ``"angle"`` (rotated ``angle`` about an edge from
            ``base_plane``), ``"three_point"`` (through three vertices), or
            ``"parallel_point"`` (parallel to ``base_plane`` through a vertex).
        base_plane (str): Name of the reference plane or planar face the new
            plane is built from (``offset``/``angle``/``parallel_point``).
        offset (float): Offset distance in millimetres (``offset`` mode).
        angle (float): Rotation in degrees (``angle`` mode).
        edge_point (list[float]): Point ``[x, y, z]`` in millimetres on the
            pivot edge (``angle`` mode).
        points (list[list[float]]): Vertex points ``[x, y, z]`` in
            millimetres — three for ``three_point``, one for
            ``parallel_point``.
        flip (bool): Build to the other side (offset/angle modes).
    """

    mode: str
    base_plane: str = ""
    offset: float = 0.0
    angle: float = 0.0
    edge_point: list[float] = []
    points: list[list[float]] = []
    flip: bool = False


class CreateAxisParameters(BaseModel):
    """Parameters for a reference-axis operation.

    Exactly one mode is used per call; the other mode's fields are ignored.

    Attributes:
        mode (str): One of ``"two_planes"`` (intersection of two planes),
            ``"cylindrical_face"`` (axis of a cylinder/cone located by a point
            on it), ``"two_points"`` (through two vertices), or ``"edge"``
            (along a linear edge located by a point on it).
        planes (list[str]): Two plane names (``two_planes`` mode).
        face_point (list[float]): Point ``[x, y, z]`` in millimetres on the
            cylindrical face (``cylindrical_face`` mode).
        points (list[list[float]]): Two vertex points ``[x, y, z]`` in
            millimetres (``two_points`` mode).
        edge_point (list[float]): Point ``[x, y, z]`` in millimetres on the
            edge (``edge`` mode).
    """

    mode: str
    planes: list[str] = []
    face_point: list[float] = []
    points: list[list[float]] = []
    edge_point: list[float] = []


class CreateReferencePointParameters(BaseModel):
    """Parameters for a reference-point operation.

    Exactly one mode is used per call; the other mode's fields are ignored.

    Attributes:
        mode (str): One of ``"face_center"`` (center of a face located by a
            point on it), ``"arc_center"`` (center of a circular edge located
            by a point on it), or ``"along_curve"`` (one or more points along
            an edge located by a point on it).
        face_point (list[float]): Point ``[x, y, z]`` in millimetres on the
            face (``face_center`` mode).
        edge_point (list[float]): Point ``[x, y, z]`` in millimetres on the
            edge (``arc_center``/``along_curve`` modes).
        along (str): Distribution for ``along_curve`` — ``"distance"`` (at
            ``distance`` mm from the closer end), ``"percentage"`` (at
            ``percentage`` % of the length), or ``"evenly"`` (``count``
            evenly distributed points).
        distance (float): Distance in millimetres (``along == "distance"``).
        percentage (float): Percentage 0–100 (``along == "percentage"``).
        count (int): Number of points (``along == "evenly"``); 1 otherwise.
    """

    mode: str
    face_point: list[float] = []
    edge_point: list[float] = []
    along: str = "distance"
    distance: float = 0.0
    percentage: float = 0.0
    count: int = 1


class CreateCoordinateSystemParameters(BaseModel):
    """Parameters for a numerically positioned coordinate-system feature.

    Attributes:
        position (list[float]): Origin ``[x, y, z]`` in millimetres relative
            to the global origin.
        rotation (list[float]): Rotation ``[rx, ry, rz]`` in degrees about the
            global axes.
    """

    position: list[float] = [0.0, 0.0, 0.0]
    rotation: list[float] = [0.0, 0.0, 0.0]


class CreateEquationCurveParameters(BaseModel):
    """Parameters for an equation-driven sketch curve.

    Expressions are passed verbatim to SolidWorks (same syntax as the
    Equation Driven Curve sketch tool); lengths evaluate in **metres**.

    Attributes:
        x_expression (str): ``x(t)`` for a parametric curve; empty string for
            an explicit ``y = f(x)`` curve.
        y_expression (str): ``y(t)`` (parametric) or ``f(x)`` (explicit).
        z_expression (str): ``z(t)`` for a 3D parametric curve; empty for 2D.
        range_start (str): Start of the ``t`` (or ``x``) range — a string so
            expressions like ``"-pi/2"`` or dimension names work.
        range_end (str): End of the range.
        is_angle_range (bool): ``True`` when the range represents an angle in
            radians.
        lock_start (bool): Lock the curve's start point.
        lock_end (bool): Lock the curve's end point.
    """

    x_expression: str = ""
    y_expression: str
    z_expression: str = ""
    range_start: str
    range_end: str
    is_angle_range: bool = False
    lock_start: bool = True
    lock_end: bool = True


class SetGlobalVariableParameters(BaseModel):
    """Parameters for adding or updating an equation-manager global variable.

    Attributes:
        name (str): Global variable name without quotes (e.g. ``ToothCount``).
        expression (str): Right-hand side, e.g. ``"24"`` or
            ``'"PitchDiameter" / "Module"'`` (referenced names in embedded
            double quotes).
        configuration (str): Configuration the assignment applies to; empty
            string applies it to all configurations.
    """

    name: str
    expression: str
    configuration: str = ""


class CreateEquationParameters(BaseModel):
    """Parameters for adding or updating a full driving equation.

    Attributes:
        equation (str): Complete equation with quoted names, e.g.
            ``'"D1@Boss-Extrude1" = "ToothCount" / "DiametralPitch"'``.
        configuration (str): Configuration the equation applies to; empty
            string applies it to all configurations.
    """

    equation: str
    configuration: str = ""


class CreateConfigurationParameters(BaseModel):
    """Parameters for creating a configuration.

    Attributes:
        name (str): New configuration name.
        comment (str): Comment shown in Configuration Properties.
        parent (str): Parent configuration name (derived configuration);
            empty for a top-level configuration.
        description (str): Configuration description text.
    """

    name: str
    comment: str = ""
    parent: str = ""
    description: str = ""


class MeasureEntityRef(BaseModel):
    """One entity to include in a measurement selection.

    Entities with caller-stable names (reference planes, axes, sketches)
    are located by ``name``; faces, edges and vertices have no stable name
    and are located by a ``point`` lying on them.

    Attributes:
        entity_type (str): ``SelectByID2`` entity-type string, e.g.
            ``"FACE"``, ``"EDGE"``, ``"VERTEX"``, ``"PLANE"``, ``"AXIS"``.
        name (str): Entity name for named entities; empty when locating by
            point.
        point (list[float]): ``[x, y, z]`` in millimetres on the entity;
            empty when locating by name.
    """

    entity_type: str
    name: str = ""
    point: list[float] = []


class MeasureParameters(BaseModel):
    """Parameters for a measurement over one or more selected entities.

    Attributes:
        entities (list[MeasureEntityRef]): Entities to measure — one for
            intrinsic properties (edge length, face area, circle diameter),
            two or more for relational ones (distance, angle).
        arc_option (str): Distance anchor for arcs/circles — ``"center"``
            (center to center), ``"minimum"`` or ``"maximum"``.
    """

    entities: list[MeasureEntityRef]
    arc_option: str = "center"


class ApplyMaterialParameters(BaseModel):
    """Parameters for assigning a material to a part.

    Attributes:
        material (str): Material name exactly as it appears in the database,
            e.g. ``"Plain Carbon Steel"``, ``"Brass"``, ``"Gray Cast Iron"``.
        database (str): Material database; empty for the default SolidWorks
            materials database, otherwise a ``.sldmat`` file name or path.
        configuration (str): Configuration to assign the material in; empty
            for the active configuration.
    """

    material: str
    database: str = ""
    configuration: str = ""


class AddThreadParameters(BaseModel):
    """Parameters for a cosmetic thread on a circular edge.

    Attributes:
        edge_point (list[float]): ``[x, y, z]`` in millimetres on the
            circular edge of the cylindrical face to thread.
        standard (str): Thread standard — one of ``"none"``, ``"ansi_inch"``,
            ``"ansi_metric"``, ``"iso"``, ``"din"``, ``"jis"``, ``"bsi"``,
            ``"helicoil_inch"``, ``"helicoil_metric"``.
        standard_type (str): Thread type within the standard, e.g.
            ``"Machine Threads"``.
        size (str): Thread size designation, e.g. ``"1/4-20"`` or ``"M6x1.0"``.
        diameter (float): Thread (minor/drill) diameter in millimetres.
        end_type (str): ``"blind"``, ``"blind_upto_next"``, ``"through"`` or
            ``"blind_2dia"``.
        depth (float): Thread depth in millimetres (blind end types only).
        note (str): Callout text shown in drawings.
    """

    edge_point: list[float]
    standard: str = "ansi_inch"
    standard_type: str = ""
    size: str = ""
    diameter: float = 0.0
    end_type: str = "blind"
    depth: float = 0.0
    note: str = ""


class CreateBomParameters(BaseModel):
    """Parameters for inserting a BOM table into the active document.

    Attributes:
        bom_type (str): ``"parts_only"``, ``"top_level"``, ``"indented"`` or
            ``"flattened"``.
        configuration (str): Configuration the BOM reflects; empty for the
            active configuration (SolidWorks has no implicit default).
        template (str): Path to a ``.sldbomtbt`` BOM template; empty to use
            the installed ``bom-standard`` template.
        file_path (str): CSV output path (``export_bom_csv`` only).
    """

    bom_type: str = "parts_only"
    configuration: str = ""
    template: str = ""
    file_path: str = ""


class MassProperties(BaseModel):
    """Mass properties information.

    Attributes:
        center_of_mass (list[float]): The center of mass value.
        mass (float): The mass value.
        moments_of_inertia (dict[str, float]): The moments of inertia value.
        principal_axes (dict[str, list[float]] | None): The principal axes value.
        surface_area (float): The surface area value.
        volume (float): The volume value.
    """

    volume: float
    surface_area: float
    mass: float
    center_of_mass: list[float]  # [x, y, z]
    moments_of_inertia: dict[str, float]
    principal_axes: dict[str, list[float]] | None = None


class SolidWorksAdapter(ABC):
    """Base adapter interface for SolidWorks integration.

    Args:
        config (object | None): Configuration values for the operation. Defaults to None.

    Attributes:
        _metrics (Any): The metrics value.
        config (Any): The config value.
        config_dict (Any): The config dict value.
    """

    def __init__(self, config: object | None = None):
        """Initialize adapter with configuration.

        Args:
            config (object | None): Configuration values for the operation. Defaults to None.
        """
        if config is None:
            normalized_config: dict[str, Any] = {}
        elif isinstance(config, Mapping):
            normalized_config = dict(config)
        elif hasattr(config, "model_dump"):
            normalized_config = dict(config.model_dump())
        else:
            normalized_config = {}

        # Preserve original config object for compatibility with tests and
        # call sites that compare object identity/equality.
        self.config = config
        # Keep a normalized mapping for adapter internals.
        self.config_dict = normalized_config
        self._metrics = {
            "operations_count": 0,
            "errors_count": 0,
            "average_response_time": 0.0,
        }
        # SolidWorks-as-Code session logging. Set soc_session_id to enable
        # automatic ToolCallRecord writes for every adapter operation.
        self.soc_session_id: str | None = None
        self.soc_db_path: Path | None = None

    # Connection Management
    @abstractmethod
    async def connect(self) -> None:
        """Connect to SolidWorks application.

        Returns:
            None: None.
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from SolidWorks application.

        Returns:
            None: None.
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected to SolidWorks.

        Returns:
            bool: True if connected, otherwise False.
        """
        pass

    @abstractmethod
    async def health_check(self) -> AdapterHealth:
        """Get adapter health status.

        Returns:
            AdapterHealth: The result produced by the operation.
        """
        pass

    # Model Operations
    @abstractmethod
    async def open_model(self, file_path: str) -> AdapterResult[SolidWorksModel]:
        """Open a SolidWorks model (part, assembly, or drawing).

        Args:
            file_path (str): Path to the target file.

        Returns:
            AdapterResult[SolidWorksModel]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def close_model(self, save: bool = False) -> AdapterResult[None]:
        """Close the current model.

        Args:
            save (bool): The save value. Defaults to False.

        Returns:
            AdapterResult[None]: The result produced by the operation.
        """
        pass

    async def save_file(self, file_path: str | None = None) -> AdapterResult[Any]:
        """Save the active model to the existing path or the provided path.

        Args:
            file_path (str | None): Path to the target file. Defaults to None.

        Returns:
            AdapterResult[Any]: The result produced by the operation.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="save_file is not implemented by this adapter",
        )

    @abstractmethod
    async def get_model_info(self) -> AdapterResult[dict[str, Any]]:
        """Get metadata for the active model.

        Returns:
            AdapterResult[dict[str, Any]]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def list_features(
        self, include_suppressed: bool = False
    ) -> AdapterResult[list[dict[str, Any]]]:
        """List model features from the feature tree.

        Args:
            include_suppressed (bool): The include suppressed value. Defaults to False.

        Returns:
            AdapterResult[list[dict[str, Any]]]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def list_configurations(self) -> AdapterResult[list[str]]:
        """List configuration names for the active model.

        Returns:
            AdapterResult[list[str]]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def create_part(
        self, name: str | None = None, units: str | None = None
    ) -> AdapterResult[SolidWorksModel]:
        """Create a new part document.

        Args:
            name (str | None): The name value. Defaults to None.
            units (str | None): The units value. Defaults to None.

        Returns:
            AdapterResult[SolidWorksModel]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def create_assembly(
        self, name: str | None = None
    ) -> AdapterResult[SolidWorksModel]:
        """Create a new assembly document.

        Args:
            name (str | None): The name value. Defaults to None.

        Returns:
            AdapterResult[SolidWorksModel]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def create_drawing(
        self, name: str | None = None
    ) -> AdapterResult[SolidWorksModel]:
        """Create a new drawing document.

        Args:
            name (str | None): The name value. Defaults to None.

        Returns:
            AdapterResult[SolidWorksModel]: The result produced by the operation.
        """
        pass

    # Feature Operations
    @abstractmethod
    async def create_extrusion(
        self, params: ExtrusionParameters
    ) -> AdapterResult[SolidWorksFeature]:
        """Create an extrusion feature.

        Args:
            params (ExtrusionParameters): The params value.

        Returns:
            AdapterResult[SolidWorksFeature]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def create_revolve(
        self, params: RevolveParameters
    ) -> AdapterResult[SolidWorksFeature]:
        """Create a revolve feature.

        Args:
            params (RevolveParameters): The params value.

        Returns:
            AdapterResult[SolidWorksFeature]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def create_sweep(
        self, params: SweepParameters
    ) -> AdapterResult[SolidWorksFeature]:
        """Create a sweep feature.

        Args:
            params (SweepParameters): The params value.

        Returns:
            AdapterResult[SolidWorksFeature]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def create_loft(
        self, params: LoftParameters
    ) -> AdapterResult[SolidWorksFeature]:
        """Create a loft feature.

        Args:
            params (LoftParameters): The params value.

        Returns:
            AdapterResult[SolidWorksFeature]: The result produced by the operation.
        """
        pass

    # Sketch Operations
    @abstractmethod
    async def create_sketch(self, plane: str) -> AdapterResult[str]:
        """Create a new sketch on the specified plane.

        Args:
            plane (str): The plane value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def add_line(
        self, x1: float, y1: float, x2: float, y2: float
    ) -> AdapterResult[str]:
        """Add a line to the current sketch.

        Args:
            x1 (float): The x1 value.
            y1 (float): The y1 value.
            x2 (float): The x2 value.
            y2 (float): The y2 value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def add_circle(
        self, center_x: float, center_y: float, radius: float
    ) -> AdapterResult[str]:
        """Add a circle to the current sketch.

        Args:
            center_x (float): The center x value.
            center_y (float): The center y value.
            radius (float): The radius value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def add_rectangle(
        self, x1: float, y1: float, x2: float, y2: float
    ) -> AdapterResult[str]:
        """Add a rectangle to the current sketch.

        Args:
            x1 (float): The x1 value.
            y1 (float): The y1 value.
            x2 (float): The x2 value.
            y2 (float): The y2 value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        pass

    async def add_arc(
        self,
        center_x: float,
        center_y: float,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
    ) -> AdapterResult[str]:
        """Add an arc to the current sketch.

        Args:
            center_x (float): The center x value.
            center_y (float): The center y value.
            start_x (float): The start x value.
            start_y (float): The start y value.
            end_x (float): The end x value.
            end_y (float): The end y value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="add_arc is not implemented by this adapter",
        )

    async def add_spline(self, points: list[dict[str, float]]) -> AdapterResult[str]:
        """Add a spline through the provided points.

        Args:
            points (list[dict[str, float]]): The points value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="add_spline is not implemented by this adapter",
        )

    async def add_centerline(
        self, x1: float, y1: float, x2: float, y2: float
    ) -> AdapterResult[str]:
        """Add a centerline to the current sketch.

        Args:
            x1 (float): The x1 value.
            y1 (float): The y1 value.
            x2 (float): The x2 value.
            y2 (float): The y2 value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="add_centerline is not implemented by this adapter",
        )

    async def add_polygon(
        self, center_x: float, center_y: float, radius: float, sides: int
    ) -> AdapterResult[str]:
        """Add a regular polygon to the current sketch.

        Args:
            center_x (float): The center x value.
            center_y (float): The center y value.
            radius (float): The radius value.
            sides (int): The sides value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="add_polygon is not implemented by this adapter",
        )

    async def add_ellipse(
        self,
        center_x: float,
        center_y: float,
        major_axis: float,
        minor_axis: float,
    ) -> AdapterResult[str]:
        """Add an ellipse to the current sketch.

        Args:
            center_x (float): The center x value.
            center_y (float): The center y value.
            major_axis (float): The major axis value.
            minor_axis (float): The minor axis value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="add_ellipse is not implemented by this adapter",
        )

    async def add_sketch_constraint(
        self,
        entity1: str,
        entity2: str | None,
        relation_type: str,
        entity3: str | None = None,
    ) -> AdapterResult[str]:
        """Apply a geometric constraint between sketch entities.

        Args:
            entity1 (str): The entity1 value.
            entity2 (str | None): The entity2 value.
            relation_type (str): The relation type value.
            entity3 (str | None): Third entity ID — only used by the
                ``symmetric`` relation (the centerline of symmetry). All
                other relation types reject a non-null ``entity3``.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="add_sketch_constraint is not implemented by this adapter",
        )

    async def add_sketch_dimension(
        self,
        entity1: str,
        entity2: str | None,
        dimension_type: str,
        value: float,
    ) -> AdapterResult[str]:
        """Add a sketch dimension.

        Args:
            entity1 (str): The entity1 value.
            entity2 (str | None): The entity2 value.
            dimension_type (str): The dimension type value.
            value (float): The value value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="add_sketch_dimension is not implemented by this adapter",
        )

    async def check_sketch_fully_defined(
        self, sketch_name: str | None = None
    ) -> AdapterResult[dict[str, Any]]:
        """Check whether a sketch is fully defined.

        Args:
            sketch_name (str | None): Optional sketch name to inspect. Defaults to None.

        Returns:
            AdapterResult[dict[str, Any]]: Definition status payload.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="check_sketch_fully_defined is not implemented by this adapter",
        )

    async def sketch_linear_pattern(
        self,
        entities: list[str],
        direction_x: float,
        direction_y: float,
        spacing: float,
        count: int,
    ) -> AdapterResult[str]:
        """Create a linear pattern of sketch entities.

        Args:
            entities (list[str]): The entities value.
            direction_x (float): The direction x value.
            direction_y (float): The direction y value.
            spacing (float): The spacing value.
            count (int): The count value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="sketch_linear_pattern is not implemented by this adapter",
        )

    async def sketch_circular_pattern(
        self,
        entities: list[str],
        angle: float,
        count: int,
    ) -> AdapterResult[str]:
        """Create a circular pattern of sketch entities around the sketch origin.

        The rotation axis is always the sketch origin — SW's
        ``CreateCircularSketchStepAndRepeat`` has no pattern-centre
        parameter and derives the axis from the seed's geometry. Place
        the seed entity at the desired radius from the origin.

        Args:
            entities (list[str]): The entities value.
            angle (float): The angle value.
            count (int): The count value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="sketch_circular_pattern is not implemented by this adapter",
        )

    async def sketch_mirror(
        self, entities: list[str], mirror_line: str
    ) -> AdapterResult[str]:
        """Mirror sketch entities about a mirror line.

        Args:
            entities (list[str]): The entities value.
            mirror_line (str): The mirror line value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="sketch_mirror is not implemented by this adapter",
        )

    async def sketch_offset(
        self,
        entities: list[str],
        offset_distance: float,
        reverse_direction: bool,
    ) -> AdapterResult[str]:
        """Offset sketch entities.

        Args:
            entities (list[str]): The entities value.
            offset_distance (float): The offset distance value.
            reverse_direction (bool): The reverse direction value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="sketch_offset is not implemented by this adapter",
        )

    async def add_sketch_circle(
        self,
        center_x: float,
        center_y: float,
        radius: float,
        construction: bool = False,
    ) -> AdapterResult[str]:
        """Alias for add_circle used by some tool flows.

        Args:
            center_x (float): The center x value.
            center_y (float): The center y value.
            radius (float): The radius value.
            construction (bool): The construction value. Defaults to False.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        return await self.add_circle(center_x, center_y, radius)

    async def create_cut(self, sketch_name: str, depth: float) -> AdapterResult[str]:
        """Create a cut feature from an existing sketch.

        Args:
            sketch_name (str): The sketch name value.
            depth (float): The depth value.

        Returns:
            AdapterResult[str]: The result produced by the operation.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="create_cut is not implemented by this adapter",
        )

    async def create_cut_extrude(
        self, params: ExtrusionParameters
    ) -> AdapterResult[Any]:
        """Create a cut-extrude feature from the active sketch.

        Cuts material from the current solid body using the active sketch profile.
        Equivalent to SolidWorks Insert > Cut > Extrude.

        Args:
            params (ExtrusionParameters): Depth and direction parameters.

        Returns:
            AdapterResult: Feature result or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="create_cut_extrude is not implemented by this adapter",
        )

    async def add_fillet(
        self, radius: float, edge_points: list[list[float]]
    ) -> AdapterResult[Any]:
        """Add a fillet feature to edges located by coordinate.

        Rounds edges of the current solid body with the given radius. Each edge
        is located by a point ``[x, y, z]`` (millimetres) lying on it, since
        SolidWorks edges have no caller-stable name.

        Args:
            radius (float): Fillet radius in millimeters.
            edge_points (list[list[float]]): Points ``[x, y, z]`` in mm, one per
                edge to fillet.

        Returns:
            AdapterResult: Feature result or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="add_fillet is not implemented by this adapter",
        )

    async def add_chamfer(
        self, distance: float, edge_points: list[list[float]]
    ) -> AdapterResult[Any]:
        """Add an equal-distance chamfer to edges located by coordinate.

        Args:
            distance (float): Chamfer distance in millimeters.
            edge_points (list[list[float]]): Points ``[x, y, z]`` in mm, one per
                edge to chamfer.

        Returns:
            AdapterResult: Feature result or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="add_chamfer is not implemented by this adapter",
        )

    async def mirror_feature(
        self, params: MirrorFeatureParameters
    ) -> AdapterResult[Any]:
        """Mirror existing features about a reference plane.

        Args:
            params (MirrorFeatureParameters): Mirror plane, features, options.

        Returns:
            AdapterResult: Feature result or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="mirror_feature is not implemented by this adapter",
        )

    async def circular_pattern_feature(
        self, params: CircularPatternParameters
    ) -> AdapterResult[Any]:
        """Create a circular pattern of features about an axis.

        Args:
            params (CircularPatternParameters): Axis, features, count, angle.

        Returns:
            AdapterResult: Feature result or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="circular_pattern_feature is not implemented by this adapter",
        )

    async def linear_pattern_feature(
        self, params: LinearPatternParameters
    ) -> AdapterResult[Any]:
        """Create a linear pattern of features along a direction.

        Args:
            params (LinearPatternParameters): Direction, features, count, spacing.

        Returns:
            AdapterResult: Feature result or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="linear_pattern_feature is not implemented by this adapter",
        )

    async def shell(self, params: ShellParameters) -> AdapterResult[Any]:
        """Hollow out the solid body, optionally removing faces.

        Args:
            params (ShellParameters): Thickness, faces to remove, direction.

        Returns:
            AdapterResult: Feature result or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="shell is not implemented by this adapter",
        )

    async def draft(self, params: DraftParameters) -> AdapterResult[Any]:
        """Apply a neutral-plane draft to selected faces.

        Args:
            params (DraftParameters): Angle, neutral plane, faces, direction.

        Returns:
            AdapterResult: Feature result or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="draft is not implemented by this adapter",
        )

    async def create_plane(self, params: CreatePlaneParameters) -> AdapterResult[Any]:
        """Create a constraint-based reference plane.

        Args:
            params (CreatePlaneParameters): Mode, references, distance/angle.

        Returns:
            AdapterResult: Feature result or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="create_plane is not implemented by this adapter",
        )

    async def create_axis(self, params: CreateAxisParameters) -> AdapterResult[Any]:
        """Create a reference axis.

        Args:
            params (CreateAxisParameters): Mode and references.

        Returns:
            AdapterResult: Feature result or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="create_axis is not implemented by this adapter",
        )

    async def create_reference_point(
        self, params: CreateReferencePointParameters
    ) -> AdapterResult[Any]:
        """Create one or more reference points.

        Args:
            params (CreateReferencePointParameters): Mode, references,
                distribution.

        Returns:
            AdapterResult: Feature result or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="create_reference_point is not implemented by this adapter",
        )

    async def create_coordinate_system(
        self, params: CreateCoordinateSystemParameters
    ) -> AdapterResult[Any]:
        """Create a coordinate-system feature at a numeric position/rotation.

        Args:
            params (CreateCoordinateSystemParameters): Position and rotation.

        Returns:
            AdapterResult: Feature result or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="create_coordinate_system is not implemented by this adapter",
        )

    async def create_equation_driven_curve(
        self, params: CreateEquationCurveParameters
    ) -> AdapterResult[str]:
        """Create an equation-driven curve in the active sketch.

        Args:
            params (CreateEquationCurveParameters): Expressions and range.

        Returns:
            AdapterResult[str]: Registered sketch-entity ID or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="create_equation_driven_curve is not implemented by this adapter",
        )

    async def set_global_variable(
        self, params: SetGlobalVariableParameters
    ) -> AdapterResult[dict[str, Any]]:
        """Add or update a global variable in the equation manager.

        Args:
            params (SetGlobalVariableParameters): Name, expression, scope.

        Returns:
            AdapterResult[dict[str, Any]]: Equation index/text or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="set_global_variable is not implemented by this adapter",
        )

    async def create_equation(
        self, params: CreateEquationParameters
    ) -> AdapterResult[dict[str, Any]]:
        """Add or update a driving equation in the equation manager.

        Args:
            params (CreateEquationParameters): Equation text and scope.

        Returns:
            AdapterResult[dict[str, Any]]: Equation index/text or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="create_equation is not implemented by this adapter",
        )

    async def create_configuration(
        self, params: CreateConfigurationParameters
    ) -> AdapterResult[dict[str, Any]]:
        """Create a configuration on the active model.

        Args:
            params (CreateConfigurationParameters): Name and metadata.

        Returns:
            AdapterResult[dict[str, Any]]: Configuration name or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="create_configuration is not implemented by this adapter",
        )

    async def set_active_configuration(
        self, name: str
    ) -> AdapterResult[dict[str, Any]]:
        """Activate a configuration by name and rebuild.

        Args:
            name (str): Configuration name to activate.

        Returns:
            AdapterResult[dict[str, Any]]: Activation details or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="set_active_configuration is not implemented by this adapter",
        )

    async def measure(self, params: MeasureParameters) -> AdapterResult[dict[str, Any]]:
        """Measure the given entities (distances, lengths, areas, angles).

        Args:
            params (MeasureParameters): Entities and arc-distance option.

        Returns:
            AdapterResult[dict[str, Any]]: Measured values (millimetres,
            mm², degrees) or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="measure is not implemented by this adapter",
        )

    async def apply_material(
        self, params: ApplyMaterialParameters
    ) -> AdapterResult[dict[str, Any]]:
        """Assign a material to the active part.

        Args:
            params (ApplyMaterialParameters): Material, database, scope.

        Returns:
            AdapterResult[dict[str, Any]]: Applied material details or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="apply_material is not implemented by this adapter",
        )

    async def add_thread(
        self, params: AddThreadParameters
    ) -> AdapterResult[dict[str, Any]]:
        """Add a cosmetic thread to a circular edge.

        Args:
            params (AddThreadParameters): Edge location and thread spec.

        Returns:
            AdapterResult[dict[str, Any]]: Thread feature details or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="add_thread is not implemented by this adapter",
        )

    async def create_bom(
        self, params: CreateBomParameters
    ) -> AdapterResult[dict[str, Any]]:
        """Insert a BOM table and return its contents.

        Args:
            params (CreateBomParameters): BOM type, configuration, template.

        Returns:
            AdapterResult[dict[str, Any]]: Table contents or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="create_bom is not implemented by this adapter",
        )

    async def export_bom_csv(
        self, params: CreateBomParameters
    ) -> AdapterResult[dict[str, Any]]:
        """Insert a BOM table and write its contents to a CSV file.

        Args:
            params (CreateBomParameters): BOM options plus ``file_path``.

        Returns:
            AdapterResult[dict[str, Any]]: Export summary or error.
        """
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="export_bom_csv is not implemented by this adapter",
        )

    @abstractmethod
    async def exit_sketch(self) -> AdapterResult[None]:
        """Exit sketch editing mode.

        Returns:
            AdapterResult[None]: The result produced by the operation.
        """
        pass

    # Analysis Operations
    @abstractmethod
    async def get_mass_properties(self) -> AdapterResult[MassProperties]:
        """Get mass properties of the current model.

        Returns:
            AdapterResult[MassProperties]: The result produced by the operation.
        """
        pass

    # Export Operations
    @abstractmethod
    async def export_image(self, payload: dict) -> AdapterResult[dict]:
        """Export a viewport screenshot (PNG/JPG) of the current model.

        Payload keys: file_path (str): Absolute output path. width (int): Image width in pixels.
        height (int): Image height in pixels. view_orientation (str): One of "isometric",
        "front", "top", "right", "back", "bottom", "current".

        Args:
            payload (dict): The payload value.

        Returns:
            AdapterResult[dict]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def export_file(
        self, file_path: str, format_type: str
    ) -> AdapterResult[None]:
        """Export the current model to a file.

        Args:
            file_path (str): Path to the target file.
            format_type (str): The format type value.

        Returns:
            AdapterResult[None]: The result produced by the operation.
        """
        pass

    # Dimension Operations
    @abstractmethod
    async def get_dimension(self, name: str) -> AdapterResult[float]:
        """Get the value of a dimension.

        Args:
            name (str): The name value.

        Returns:
            AdapterResult[float]: The result produced by the operation.
        """
        pass

    @abstractmethod
    async def set_dimension(self, name: str, value: float) -> AdapterResult[None]:
        """Set the value of a dimension.

        Args:
            name (str): The name value.
            value (float): The value value.

        Returns:
            AdapterResult[None]: The result produced by the operation.
        """
        pass

    # Utility Methods
    def update_metrics(self, operation_time: float, success: bool) -> None:
        """Update adapter metrics.

        Args:
            operation_time (float): The operation time value.
            success (bool): The success value.

        Returns:
            None: None.
        """
        self._metrics["operations_count"] += 1
        if not success:
            self._metrics["errors_count"] += 1

        # Update average response time
        current_avg = self._metrics["average_response_time"]
        count = self._metrics["operations_count"]
        self._metrics["average_response_time"] = (
            current_avg * (count - 1) + operation_time
        ) / count

    def get_metrics(self) -> dict[str, Any]:
        """Get adapter metrics.

        Returns:
            dict[str, Any]: A dictionary containing the resulting values.
        """
        return self._metrics.copy()
