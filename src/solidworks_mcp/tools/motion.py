"""Motion-study tools for the SolidWorks MCP server.

Expose the SOLIDWORKS Motion-study lifecycle as MCP tools: create/activate a
study and set its analysis type, ensure the SOLIDWORKS Motion add-in is
loaded, add a rotary/linear constant-speed motor and gravity, add spring,
damper and force feature elements, solve the study, scrub to a point in time,
export the animation to AVI, and list the document's studies.

These wrap :class:`SolidWorksMotionMixin` on the adapter.
"""

from typing import Any

from fastmcp import FastMCP
from loguru import logger
from pydantic import BaseModel, Field

from ..adapters.base import (
    MateEntityRef,
    MotionDamperParameters,
    MotionExportParameters,
    MotionForceParameters,
    MotionGravityParameters,
    MotionMotorParameters,
    MotionSpringParameters,
    MotionStudyParameters,
    MotionStudyRefParameters,
    MotionTimeParameters,
    SolidWorksAdapter,
)
from .modeling import _normalize_input


def _entity_ref(entity: "MotionEntityInput") -> MateEntityRef:
    """Build a MateEntityRef from a tool-layer MotionEntityInput."""
    return MateEntityRef(
        entity_type=entity.entity_type, name=entity.name, point=entity.point
    )


class MotionEntityInput(BaseModel):
    """A face/edge/axis locator for a motor's location and direction.

    Attributes:
        entity_type (str): Selection type, e.g. ``"FACE"``, ``"EDGE"`` or
            ``"AXIS"``.
        name (str): Entity name — inside a component use ``"Axis1@shaft-1"``
            (the assembly qualifier is appended automatically); empty when
            locating by point.
        point (list[float]): ``[x, y, z]`` in millimetres on the entity
            (view-dependent pick); empty when locating by name.
    """

    entity_type: str = Field(
        default="FACE",
        description="Selection type, e.g. 'FACE', 'EDGE' or 'AXIS'",
    )
    name: str = Field(
        default="",
        description=(
            "Entity name — inside a component use 'Axis1@shaft-1' (the "
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

    def model_post_init(self, __context: Any) -> None:
        """Validate the entity locator.

        Args:
            __context (Any): The context value.

        Raises:
            ValueError: When the locator is missing or malformed.
        """
        if not self.entity_type.strip():
            raise ValueError("entity_type is required")
        if not self.name.strip() and not self.point:
            raise ValueError("the motor entity needs a name or a point")
        if self.point and len(self.point) != 3:
            raise ValueError("point must be [x, y, z] in millimetres")


class CreateMotionStudyInput(BaseModel):
    """Input schema for creating (or re-selecting) a motion study.

    Attributes:
        name (str): Study name; empty creates a new study and uses the
            SolidWorks-assigned name (returned in the result).
        study_type (str): ``"animation"``, ``"physical_simulation"`` (Basic
            Motion) or ``"motion_analysis"`` (SOLIDWORKS Motion).
        duration (float): Study duration in seconds.
        activate (bool): Activate the study after creating it.
    """

    name: str = Field(
        default="",
        description=(
            "Study name; empty creates a new study and uses the "
            "SolidWorks-assigned name (returned in the result)"
        ),
    )
    study_type: str = Field(
        default="motion_analysis",
        description=(
            "'animation', 'physical_simulation' (Basic Motion) or "
            "'motion_analysis' (SOLIDWORKS Motion — the only type that "
            "solves spring/force/gravity dynamics; requires the SOLIDWORKS "
            "Motion add-in)"
        ),
    )
    duration: float = Field(default=5.0, description="Study duration in seconds")
    activate: bool = Field(
        default=True,
        description="Activate the study after creating it (needed before "
        "adding simulation features)",
    )


class AddMotorInput(BaseModel):
    """Input schema for adding a motor to a motion study.

    Attributes:
        motor_type (str): ``"rotary"`` or ``"linear"``.
        entity (MotionEntityInput): Face/edge/axis fixing the motor's
            location and direction.
        speed (float): Constant speed — RPM for rotary, mm/s for linear.
        reverse (bool): Reverse the motor direction.
        component (str): Optional moving component the motor drives.
        study_name (str): Target study name; empty targets the active study.
    """

    motor_type: str = Field(default="rotary", description="'rotary' or 'linear'")
    entity: MotionEntityInput = Field(
        description="Face/edge/axis that fixes the motor's location and "
        "direction (as in the SolidWorks motor dialog)"
    )
    speed: float = Field(
        default=10.0,
        description="Constant speed — RPM for a rotary motor, millimetres "
        "per second for a linear motor",
    )
    reverse: bool = Field(default=False, description="Reverse the motor direction")
    component: str = Field(
        default="",
        description="Optional name of the moving component the motor drives; "
        "empty lets SolidWorks infer it from the selected face",
    )
    study_name: str = Field(
        default="",
        description="Target study name; empty targets the active study",
    )


class AddGravityInput(BaseModel):
    """Input schema for adding gravity to a motion study.

    Attributes:
        axis (str): Gravity axis ``"x"``, ``"y"`` or ``"z"``.
        strength (float): Gravitational acceleration in m/s² (SI).
        reverse (bool): Reverse the gravity direction along the axis.
        study_name (str): Target study name; empty targets the active study.
    """

    axis: str = Field(default="y", description="Gravity axis 'x', 'y' or 'z'")
    strength: float = Field(
        default=9.80665,
        description="Gravitational acceleration in m/s² (SI); defaults to "
        "standard gravity",
    )
    reverse: bool = Field(
        default=True, description="Reverse the gravity direction along the axis"
    )
    study_name: str = Field(
        default="",
        description="Target study name; empty targets the active study",
    )


class MotionStudyRefInput(BaseModel):
    """Input schema referencing one motion study by name.

    Attributes:
        name (str): Study name; empty targets the active study.
    """

    name: str = Field(
        default="", description="Study name; empty targets the active study"
    )


class SetMotionTimeInput(BaseModel):
    """Input schema for positioning a motion study at a point in time.

    Attributes:
        time (float): Time in seconds along the (calculated) study.
        study_name (str): Target study name; empty targets the active study.
    """

    time: float = Field(description="Time in seconds along the calculated study")
    study_name: str = Field(
        default="",
        description="Target study name; empty targets the active study",
    )


class ExportMotionVideoInput(BaseModel):
    """Input schema for exporting a motion study animation to a video file.

    Attributes:
        file_path (str): Output video path; the suffix picks the container —
            ``.mp4`` (recommended), ``.mkv`` or ``.flv``. ``.avi`` is not
            available headlessly.
        study_name (str): Target study name; empty targets the active study.
        frames_per_second (float): Animation frame rate written to the file.
    """

    file_path: str = Field(description="Output video path (.mp4/.mkv/.flv)")
    study_name: str = Field(
        default="",
        description="Target study name; empty targets the active study",
    )
    frames_per_second: float = Field(
        default=25.0, description="Animation frame rate written to the file"
    )


class AddMotionSpringInput(BaseModel):
    """Input schema for adding a spring force element to a motion study.

    Attributes:
        spring_type (str): ``"linear"`` or ``"torsional"``.
        endpoints (list[MotionEntityInput]): The two endpoint entities.
        spring_constant (float): Stiffness k — N/m (linear) or N·m/rad
            (torsional), SI.
        free_length (float | None): Linear rest length in mm; null keeps the
            modeled distance. Ignored for torsional springs.
        free_angle (float | None): Torsional rest angle in degrees; null
            keeps the modeled angle. Ignored for linear springs.
        damping_constant (float): When > 0, enables the spring's damper
            (N·s/m).
        coil_diameter (float): Optional cosmetic mean coil diameter (mm).
        wire_diameter (float): Optional cosmetic wire diameter (mm).
        number_of_coils (float): Optional cosmetic active coil count.
        reverse (bool): Reverse the spring direction.
        study_name (str): Target study name; empty targets the active study.
    """

    spring_type: str = Field(default="linear", description="'linear' or 'torsional'")
    endpoints: list[MotionEntityInput] = Field(
        description="The two endpoint entities (faces/edges/vertices)"
    )
    spring_constant: float = Field(
        description="Stiffness k — N/m (linear) or N·m/rad (torsional), SI"
    )
    free_length: float | None = Field(
        default=None,
        description="Linear spring rest length in mm; null keeps the modeled "
        "distance (ignored for torsional)",
    )
    free_angle: float | None = Field(
        default=None,
        description="Torsional spring rest angle in degrees; null keeps the "
        "modeled angle (ignored for linear)",
    )
    damping_constant: float = Field(
        default=0.0,
        description="When > 0, enables the spring's damper (N·s/m)",
    )
    coil_diameter: float = Field(
        default=0.0, description="Optional cosmetic mean coil diameter (mm)"
    )
    wire_diameter: float = Field(
        default=0.0, description="Optional cosmetic wire diameter (mm)"
    )
    number_of_coils: float = Field(
        default=0.0, description="Optional cosmetic active coil count"
    )
    reverse: bool = Field(default=False, description="Reverse the spring direction")
    study_name: str = Field(
        default="", description="Target study name; empty targets the active study"
    )


class AddMotionDamperInput(BaseModel):
    """Input schema for adding a damper force element to a motion study.

    Attributes:
        damper_type (str): ``"linear"`` or ``"torsional"``.
        endpoints (list[MotionEntityInput]): The two endpoint entities.
        damping_constant (float): Damping coefficient — N·s/m (linear) or
            N·m·s/rad (torsional), SI.
        study_name (str): Target study name; empty targets the active study.
    """

    damper_type: str = Field(default="linear", description="'linear' or 'torsional'")
    endpoints: list[MotionEntityInput] = Field(
        description="The two endpoint entities (faces/edges/vertices)"
    )
    damping_constant: float = Field(
        description="Damping coefficient — N·s/m (linear) or N·m·s/rad (torsional), SI"
    )
    study_name: str = Field(
        default="", description="Target study name; empty targets the active study"
    )


class AddMotionForceInput(BaseModel):
    """Input schema for adding an applied force/torque to a motion study.

    Attributes:
        force_type (str): ``"linear_force"`` or ``"torque"``.
        action (MotionEntityInput): Action-location entity (and torque axis).
        magnitude (float): Constant magnitude — N (force) or N·m (torque), SI.
        action_only (bool): Apply to one component (True) or an
            action-and-reaction pair (False).
        reverse (bool): Reverse the force direction.
        study_name (str): Target study name; empty targets the active study.
    """

    force_type: str = Field(
        default="linear_force", description="'linear_force' or 'torque'"
    )
    action: MotionEntityInput = Field(
        description="Action-location face/edge/vertex (and axis for a torque)"
    )
    magnitude: float = Field(
        description="Constant magnitude — N (force) or N·m (torque), SI"
    )
    action_only: bool = Field(
        default=True,
        description="Apply to one component (True) or an action-and-reaction "
        "pair (False)",
    )
    reverse: bool = Field(default=False, description="Reverse the force direction")
    study_name: str = Field(
        default="", description="Target study name; empty targets the active study"
    )


async def register_motion_tools(
    mcp: FastMCP, adapter: SolidWorksAdapter, config: Any
) -> int:
    """Register motion-study tools with the MCP server.

    Args:
        mcp (FastMCP): The MCP server.
        adapter (SolidWorksAdapter): Adapter instance used for the operation.
        config (Any): Configuration values for the operation.

    Returns:
        int: The number of tools registered.
    """

    @mcp.tool()
    async def create_motion_study(
        input_data: CreateMotionStudyInput,
    ) -> dict[str, Any]:
        """Create (or re-select) a motion study and set its analysis type.

        The study type is written then read back: SolidWorks silently keeps
        an Animation study when an unsupported type is requested (most
        commonly 'motion_analysis' without the SOLIDWORKS Motion add-in), so
        a read-back mismatch is reported as an error rather than degrading
        silently.

        Args:
            input_data (CreateMotionStudyInput): Name, type and duration.

        Returns:
            dict[str, Any]: Status and study name/type/duration.

        Example:
            ```python
            result = await create_motion_study({
                "study_type": "motion_analysis",
                "duration": 6.0,
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, CreateMotionStudyInput)
            result = await adapter.create_motion_study(
                MotionStudyParameters(
                    name=input_data.name,
                    study_type=input_data.study_type,
                    duration=input_data.duration,
                    activate=input_data.activate,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Created motion study: {payload.get('name')}",
                    "study": payload,
                    "execution_time": result.execution_time,
                }
            return {
                "status": "error",
                "message": f"Failed to create motion study: {result.error}",
            }
        except Exception as e:
            logger.error(f"Error in create_motion_study tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def ensure_motion_addin() -> dict[str, Any]:
        """Load the SOLIDWORKS Motion add-in (needed for motion_analysis).

        Best-effort: the binding check is the StudyType read-back in
        create_motion_study. Call this up front so a 'motion_analysis' study
        can be created.

        Returns:
            dict[str, Any]: Status and the add-in load result.
        """
        try:
            result = await adapter.ensure_motion_addin()
            if result.is_success:
                return {
                    "status": "success",
                    "message": "SOLIDWORKS Motion add-in load attempted",
                    "result": result.data or {},
                    "execution_time": result.execution_time,
                }
            return {
                "status": "error",
                "message": f"Failed to ensure Motion add-in: {result.error}",
            }
        except Exception as e:
            logger.error(f"Error in ensure_motion_addin tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def add_motor(input_data: AddMotorInput) -> dict[str, Any]:
        """Add a rotary or linear constant-speed motor to a motion study.

        Selects the location/direction geometry (by name or pick point),
        then creates the motor with a constant speed (RPM for rotary, mm/s
        for linear).

        Args:
            input_data (AddMotorInput): Motor type, entity, speed.

        Returns:
            dict[str, Any]: Status and created motor details.

        Example:
            ```python
            result = await add_motor({
                "motor_type": "rotary",
                "entity": {"entity_type": "AXIS", "name": "Axis1@crank-1"},
                "speed": 30.0,
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, AddMotorInput)
            result = await adapter.add_motor(
                MotionMotorParameters(
                    motor_type=input_data.motor_type,
                    entity=MateEntityRef(
                        entity_type=input_data.entity.entity_type,
                        name=input_data.entity.name,
                        point=input_data.entity.point,
                    ),
                    speed=input_data.speed,
                    reverse=input_data.reverse,
                    component=input_data.component,
                    study_name=input_data.study_name,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Added motor: {payload.get('name')}",
                    "motor": payload,
                    "execution_time": result.execution_time,
                }
            return {
                "status": "error",
                "message": f"Failed to add motor: {result.error}",
            }
        except Exception as e:
            logger.error(f"Error in add_motor tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def add_gravity(input_data: AddGravityInput) -> dict[str, Any]:
        """Add gravity to a motion study.

        Args:
            input_data (AddGravityInput): Axis, strength and direction.

        Returns:
            dict[str, Any]: Status and created gravity details.

        Example:
            ```python
            result = await add_gravity({"axis": "y", "reverse": True})
            ```
        """
        try:
            input_data = _normalize_input(input_data, AddGravityInput)
            result = await adapter.add_gravity(
                MotionGravityParameters(
                    axis=input_data.axis,
                    strength=input_data.strength,
                    reverse=input_data.reverse,
                    study_name=input_data.study_name,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Added gravity: {payload.get('name')}",
                    "gravity": payload,
                    "execution_time": result.execution_time,
                }
            return {
                "status": "error",
                "message": f"Failed to add gravity: {result.error}",
            }
        except Exception as e:
            logger.error(f"Error in add_gravity tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def calculate_motion(input_data: MotionStudyRefInput) -> dict[str, Any]:
        """Solve a motion study.

        Args:
            input_data (MotionStudyRefInput): Target study name.

        Returns:
            dict[str, Any]: Status and calculation result.

        Example:
            ```python
            result = await calculate_motion({})
            ```
        """
        try:
            input_data = _normalize_input(input_data, MotionStudyRefInput)
            result = await adapter.calculate_motion(
                MotionStudyRefParameters(name=input_data.name)
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Calculated motion study: {payload.get('name')}",
                    "result": payload,
                    "execution_time": result.execution_time,
                }
            return {
                "status": "error",
                "message": f"Failed to calculate motion: {result.error}",
            }
        except Exception as e:
            logger.error(f"Error in calculate_motion tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def set_motion_time(input_data: SetMotionTimeInput) -> dict[str, Any]:
        """Position a calculated motion study at a point in time.

        After this, component transforms reflect the solved pose at the
        given time — callers read each component's transform to sample the
        motion.

        Args:
            input_data (SetMotionTimeInput): Time in seconds and study name.

        Returns:
            dict[str, Any]: Status and applied time.

        Example:
            ```python
            result = await set_motion_time({"time": 2.5})
            ```
        """
        try:
            input_data = _normalize_input(input_data, SetMotionTimeInput)
            result = await adapter.set_motion_time(
                MotionTimeParameters(
                    time=input_data.time, study_name=input_data.study_name
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Set motion time: {payload.get('time')}s",
                    "result": payload,
                    "execution_time": result.execution_time,
                }
            return {
                "status": "error",
                "message": f"Failed to set motion time: {result.error}",
            }
        except Exception as e:
            logger.error(f"Error in set_motion_time tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def export_motion_video(input_data: ExportMotionVideoInput) -> dict[str, Any]:
        """Export a motion study animation to a single-file H.264 video.

        The container follows the path suffix (``.mp4``/``.mkv``/``.flv``).
        ``.avi`` is not available headlessly — SOLIDWORKS only writes it via
        the interactive Video-Compression codec dialog.

        Args:
            input_data (ExportMotionVideoInput): Output path and study name.

        Returns:
            dict[str, Any]: Status and output path.

        Example:
            ```python
            result = await export_motion_video({
                "file_path": "C:/out/operation.mp4",
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, ExportMotionVideoInput)
            result = await adapter.export_motion_video(
                MotionExportParameters(
                    file_path=input_data.file_path,
                    study_name=input_data.study_name,
                    frames_per_second=input_data.frames_per_second,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Exported motion video: {payload.get('file_path')}",
                    "result": payload,
                    "execution_time": result.execution_time,
                }
            return {
                "status": "error",
                "message": f"Failed to export motion video: {result.error}",
            }
        except Exception as e:
            logger.error(f"Error in export_motion_video tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def list_motion_studies() -> dict[str, Any]:
        """List the active document's motion studies.

        Returns:
            dict[str, Any]: Status, studies and count.

        Example:
            ```python
            result = await list_motion_studies()
            ```
        """
        try:
            result = await adapter.list_motion_studies()
            if result.is_success:
                studies = result.data or []
                return {
                    "status": "success",
                    "studies": studies,
                    "count": len(studies),
                    "execution_time": result.execution_time,
                }
            return {
                "status": "error",
                "message": f"Failed to list motion studies: {result.error}",
            }
        except Exception as e:
            logger.error(f"Error in list_motion_studies tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def add_motion_spring(input_data: AddMotionSpringInput) -> dict[str, Any]:
        """Add a spring force element between two endpoints in a study.

        A real MotionAnalysis force element (not cosmetic coil geometry): it
        applies a force/torque proportional to its stretch from the free
        length/angle, which the solver balances. Stiffness is SI; lengths are
        millimetres.

        Args:
            input_data (AddMotionSpringInput): Spring type, endpoints, k, L0.

        Returns:
            dict[str, Any]: Status and created spring details.

        Example:
            ```python
            result = await add_motion_spring({
                "spring_type": "linear",
                "endpoints": [
                    {"entity_type": "VERTEX", "point": [10, 20, 0]},
                    {"entity_type": "VERTEX", "point": [10, 50, 0]},
                ],
                "spring_constant": 1500.0,
                "free_length": 25.0,
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, AddMotionSpringInput)
            result = await adapter.add_motion_spring(
                MotionSpringParameters(
                    spring_type=input_data.spring_type,
                    endpoints=[_entity_ref(e) for e in input_data.endpoints],
                    spring_constant=input_data.spring_constant,
                    free_length=input_data.free_length,
                    free_angle=input_data.free_angle,
                    damping_constant=input_data.damping_constant,
                    coil_diameter=input_data.coil_diameter,
                    wire_diameter=input_data.wire_diameter,
                    number_of_coils=input_data.number_of_coils,
                    reverse=input_data.reverse,
                    study_name=input_data.study_name,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Added spring: {payload.get('name')}",
                    "spring": payload,
                    "execution_time": result.execution_time,
                }
            return {
                "status": "error",
                "message": f"Failed to add spring: {result.error}",
            }
        except Exception as e:
            logger.error(f"Error in add_motion_spring tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def add_motion_damper(input_data: AddMotionDamperInput) -> dict[str, Any]:
        """Add a damper force element between two endpoints in a study.

        Applies a resistive force/torque proportional to the relative
        velocity of its endpoints. Damping coefficient is SI.

        Args:
            input_data (AddMotionDamperInput): Damper type, endpoints, c.

        Returns:
            dict[str, Any]: Status and created damper details.

        Example:
            ```python
            result = await add_motion_damper({
                "damper_type": "linear",
                "endpoints": [
                    {"entity_type": "VERTEX", "point": [10, 20, 0]},
                    {"entity_type": "VERTEX", "point": [10, 50, 0]},
                ],
                "damping_constant": 5.0,
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, AddMotionDamperInput)
            result = await adapter.add_motion_damper(
                MotionDamperParameters(
                    damper_type=input_data.damper_type,
                    endpoints=[_entity_ref(e) for e in input_data.endpoints],
                    damping_constant=input_data.damping_constant,
                    study_name=input_data.study_name,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Added damper: {payload.get('name')}",
                    "damper": payload,
                    "execution_time": result.execution_time,
                }
            return {
                "status": "error",
                "message": f"Failed to add damper: {result.error}",
            }
        except Exception as e:
            logger.error(f"Error in add_motion_damper tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def add_motion_force(input_data: AddMotionForceInput) -> dict[str, Any]:
        """Add a constant applied force/torque at a location on a component.

        Applies a constant-magnitude action force (linear) or torque about an
        axis at a location on a component. Magnitude is SI.

        Args:
            input_data (AddMotionForceInput): Force type, location, magnitude.

        Returns:
            dict[str, Any]: Status and created force details.

        Example:
            ```python
            result = await add_motion_force({
                "force_type": "linear_force",
                "action": {"entity_type": "FACE", "point": [10, 20, 0]},
                "magnitude": 9.81,
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, AddMotionForceInput)
            result = await adapter.add_motion_force(
                MotionForceParameters(
                    force_type=input_data.force_type,
                    action=_entity_ref(input_data.action),
                    magnitude=input_data.magnitude,
                    action_only=input_data.action_only,
                    reverse=input_data.reverse,
                    study_name=input_data.study_name,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Added force: {payload.get('name')}",
                    "force": payload,
                    "execution_time": result.execution_time,
                }
            return {
                "status": "error",
                "message": f"Failed to add force: {result.error}",
            }
        except Exception as e:
            logger.error(f"Error in add_motion_force tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    tool_count = 11  # Number of tools registered
    return tool_count
