"""Motion-study mixin for PyWin32 SolidWorks operations.

Implements SOLIDWORKS Motion study automation on the active assembly:
create/activate a study and set its analysis type
(``IModelDocExtension::GetMotionStudyManager`` →
``IMotionStudyManager::CreateMotionStudy`` → ``IMotionStudy::StudyType``),
add a rotary/linear constant-speed motor and gravity
(``IMotionStudy::CreateDefinition`` → set the
``ISimulation*FeatureData`` members → ``IMotionStudy::CreateFeature``),
solve (``IMotionStudy::Calculate``), scrub to a time
(``IMotionStudy::SetTime`` — moves the components so callers can read each
one's transform) and export the animation (``IMotionStudy::SaveToAVI``).

Spring/damper/force feature elements layer on top of this core in a
follow-up change; this module ships the study lifecycle, motor, gravity,
solve, scrub and export.

Units: gravity strength is SI (m/s², the API's unit); motor speed is
passed verbatim to ``ConstantSpeedMotor`` (RPM for a rotary motor, mm/s
for a linear motor — converted to m/s for the linear case); entity pick
points are millimetres (converted by the shared selection helper).

The Motion interfaces live in the SwMotionStudy type library, not
sldworks.tlb, so ``sw_type_info.flag_methods`` does not cover them. Their
zero-argument methods (``Activate``, ``Calculate``, ``CreateMotionStudy``)
are flagged here directly via ``_FlagAsMethod`` so pywin32 invokes them
instead of mis-resolving them as properties.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from ..base import (
    AdapterResult,
    AdapterResultStatus,
    MotionExportParameters,
    MotionGravityParameters,
    MotionMotorParameters,
    MotionStudyParameters,
    MotionStudyRefParameters,
    MotionTimeParameters,
)
from .assembly import _select_mate_entity

try:
    import pythoncom  # noqa: F401
    import win32com.client  # noqa: F401
except ImportError:  # pragma: no cover
    pythoncom = SimpleNamespace()
    win32com = SimpleNamespace(client=SimpleNamespace())

# swMotionStudyType_e — defined only in the .NET interop, absent from the
# COM type library, so the values cannot be flagged/resolved at runtime.
# These are the documented bitmask values; create_motion_study writes the
# requested type then reads StudyType back to confirm it took (a wrong or
# unsupported type — e.g. motion_analysis without the SOLIDWORKS Motion
# add-in — does not stick, and is reported as an error rather than silently
# degrading to an Animation study).
_STUDY_TYPES = {
    "animation": 1,
    "physical_simulation": 2,  # Basic Motion
    "motion_analysis": 4,  # SOLIDWORKS Motion (CosmosMotion)
}

# swFeatureNameID_e (read live from the registered type library)
_FEAT_GRAVITY = 74
_FEAT_LINEAR_MOTOR = 77
_FEAT_ROTARY_MOTOR = 78

_MOTOR_FEATURE = {"rotary": _FEAT_ROTARY_MOTOR, "linear": _FEAT_LINEAR_MOTOR}

# swSimulationGravityAxis_e
_GRAVITY_AXES = {"x": 0, "y": 1, "z": 2}

# Zero-argument Motion methods pywin32 must invoke (not read as properties).
_MOTION_METHODS = (
    "CreateMotionStudy",
    "GetMotionStudy",
    "GetMotionStudyNames",
    "ActivateMotionStudy",
    "Activate",
    "Calculate",
    "CreateDefinition",
    "CreateFeature",
    "GetSupportedStudyTypes",
    "SetDuration",
    "SetTime",
    "ConstantSpeedMotor",
    "SaveToAVI",
)


class SolidWorksMotionMixin:
    """Expose SolidWorks Motion-study methods via mixin-local helpers."""

    async def create_motion_study(
        self, params: MotionStudyParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _create_motion_study_impl(self, params)

    async def ensure_motion_addin(self) -> AdapterResult[dict[str, Any]]:
        return _ensure_motion_addin_impl(self)

    async def add_motor(
        self, params: MotionMotorParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _add_motor_impl(self, params)

    async def add_gravity(
        self, params: MotionGravityParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _add_gravity_impl(self, params)

    async def calculate_motion(
        self, params: MotionStudyRefParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _calculate_motion_impl(self, params)

    async def set_motion_time(
        self, params: MotionTimeParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _set_motion_time_impl(self, params)

    async def export_motion_avi(
        self, params: MotionExportParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _export_motion_avi_impl(self, params)

    async def list_motion_studies(self) -> AdapterResult[list[dict[str, Any]]]:
        return _list_motion_studies_impl(self)


def _flag_motion_methods(obj: Any) -> None:
    """Flag the known zero-argument Motion methods on a dispatch.

    ``_FlagAsMethod`` only records intent; the ``GetIDsOfNames`` round-trip
    happens at call time, so flagging a name the object does not expose is
    harmless here (all names belong to the Motion interfaces).

    Args:
        obj: A Motion COM dispatch (manager or study).
    """
    flag = getattr(obj, "_FlagAsMethod", None)
    if flag is None:
        return
    try:
        flag(*_MOTION_METHODS)
    except Exception:  # pragma: no cover - defensive
        pass


def _motion_manager(adapter: Any) -> Any:
    """Return the active document's motion-study manager (or ``None``).

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.

    Returns:
        Any: ``IMotionStudyManager`` dispatch or ``None``.
    """
    mgr = adapter._attempt(
        lambda: adapter.currentModel.Extension.GetMotionStudyManager(), default=None
    )
    if mgr is not None:
        _flag_motion_methods(mgr)
    return mgr


def _study_names(adapter: Any, mgr: Any) -> list[str]:
    """Return the current motion-study names.

    Args:
        adapter: Connected adapter.
        mgr: ``IMotionStudyManager`` dispatch.

    Returns:
        list[str]: Study names in tree order.
    """
    names = adapter._attempt(lambda: mgr.GetMotionStudyNames(), default=None)
    if not names:
        return []
    return [str(n) for n in names]


def _resolve_study(adapter: Any, mgr: Any, name: str) -> Any:
    """Resolve and activate a study by name (or the active study).

    Args:
        adapter: Connected adapter.
        mgr: ``IMotionStudyManager`` dispatch.
        name: Study name; empty uses ``adapter._active_motion_study``.

    Returns:
        Any: Activated ``IMotionStudy`` dispatch.

    Raises:
        Exception: When no study can be resolved.
    """
    target = name or getattr(adapter, "_active_motion_study", "")
    if not target:
        raise Exception(
            "No motion study specified and none is active; create_motion_study first"
        )
    study = adapter._attempt(lambda: mgr.GetMotionStudy(target), default=None)
    if study is None:
        raise Exception(f"Motion study {target!r} not found")
    _flag_motion_methods(study)
    adapter._attempt(lambda: study.Activate(), default=None)
    adapter._active_motion_study = target
    return study


def _selected_object(adapter: Any) -> Any:
    """Return the first selected object via the selection manager.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.

    Returns:
        Any: The selected COM dispatch or ``None``.
    """
    return adapter._attempt(
        lambda: adapter.currentModel.SelectionManager.GetSelectedObject6(1, -1),
        default=None,
    )


def _create_motion_study_impl(
    adapter: Any, params: MotionStudyParameters
) -> AdapterResult[dict[str, Any]]:
    """Create or re-select a motion study and set its analysis type.

    The study type is written then read back: SolidWorks silently keeps an
    Animation study when an unsupported type is requested (most commonly
    ``motion_analysis`` without the SOLIDWORKS Motion add-in), so a
    read-back mismatch is surfaced as an error.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Study name, type and duration.

    Returns:
        AdapterResult[dict[str, Any]]: Study name/type or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    type_value = _STUDY_TYPES.get(params.study_type)
    if type_value is None:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error=f"Unknown study_type: {params.study_type!r} "
            f"(expected one of {sorted(_STUDY_TYPES)})",
        )

    def _operation() -> dict[str, Any]:
        mgr = _motion_manager(adapter)
        if mgr is None:
            raise Exception(
                "GetMotionStudyManager returned null (MotionManager unavailable)"
            )
        if params.name:
            study = adapter._attempt(
                lambda: mgr.GetMotionStudy(params.name), default=None
            )
            if study is None:
                raise Exception(f"Motion study {params.name!r} not found")
        else:
            before = set(_study_names(adapter, mgr))
            study = adapter._attempt(lambda: mgr.CreateMotionStudy(), default=None)
            if not _is_study(study):
                after = [n for n in _study_names(adapter, mgr) if n not in before]
                if not after:
                    raise Exception("CreateMotionStudy did not create a study")
                study = adapter._attempt(
                    lambda: mgr.GetMotionStudy(after[-1]), default=None
                )
            if study is None:
                raise Exception("CreateMotionStudy returned null")
        _flag_motion_methods(study)

        adapter._attempt(lambda: setattr(study, "StudyType", type_value))
        applied = adapter._attempt(lambda: int(study.StudyType), default=None)
        if applied != type_value:
            hint = (
                " (enable Tools > Add-Ins > SOLIDWORKS Motion)"
                if params.study_type == "motion_analysis"
                else ""
            )
            raise Exception(
                f"StudyType {params.study_type!r} did not take "
                f"(read back {applied}){hint}"
            )

        adapter._attempt(lambda: study.SetDuration(float(params.duration)))
        if params.activate:
            adapter._attempt(lambda: study.Activate(), default=None)
        name = str(adapter._attempt(lambda: study.Name, default="") or "")
        adapter._active_motion_study = name
        return {
            "name": name,
            "study_type": params.study_type,
            "duration": float(params.duration),
        }

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("create_motion_study", _operation),
    )


def _is_study(obj: Any) -> bool:
    """Return ``True`` when ``obj`` looks like an ``IMotionStudy`` dispatch."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return False
    return True


def _ensure_motion_addin_impl(adapter: Any) -> AdapterResult[dict[str, Any]]:
    """Report whether Motion Analysis is available, loading the add-in.

    Attempts ``ISldWorks::LoadAddIn`` for the SOLIDWORKS Motion add-in, then
    reports the study types a fresh study supports. The authoritative check
    is the StudyType read-back in :func:`_create_motion_study_impl`; this
    method is a convenience to load the add-in up front.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.

    Returns:
        AdapterResult[dict[str, Any]]: Add-in/support state or error.
    """
    if not adapter.swApp:
        return AdapterResult(
            status=AdapterResultStatus.ERROR, error="No SolidWorks application"
        )

    def _operation() -> dict[str, Any]:
        # The SOLIDWORKS Motion add-in registers under a stable title; the
        # built-in add-ins load by title via LoadAddIn returning a non-zero
        # error when unavailable. Loading is best-effort — the StudyType
        # read-back in create_motion_study is the binding check.
        loaded = adapter._attempt(
            lambda: adapter.swApp.LoadAddIn("SOLIDWORKS Motion"), default=None
        )
        return {"load_addin_status": loaded}

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("ensure_motion_addin", _operation),
    )


def _add_motor_impl(
    adapter: Any, params: MotionMotorParameters
) -> AdapterResult[dict[str, Any]]:
    """Add a rotary or linear constant-speed motor to a motion study.

    Mirrors the SolidWorks motor dialog: select the location/direction
    geometry, create the motor feature data, set its references and a
    constant speed, then create the feature.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Motor type, entity, speed and optional moving component.

    Returns:
        AdapterResult[dict[str, Any]]: Created motor feature or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    feature_id = _MOTOR_FEATURE.get(params.motor_type)
    if feature_id is None:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error=f"Unknown motor_type: {params.motor_type!r} "
            f"(expected one of {sorted(_MOTOR_FEATURE)})",
        )

    def _operation() -> dict[str, Any]:
        mgr = _motion_manager(adapter)
        if mgr is None:
            raise Exception("MotionManager unavailable")
        study = _resolve_study(adapter, mgr, params.study_name)

        data = adapter._attempt(
            lambda: study.CreateDefinition(feature_id), default=None
        )
        if data is None:
            raise Exception("CreateDefinition failed for motor")

        adapter._attempt(lambda: adapter.currentModel.ClearSelection2(True))
        if not _select_mate_entity(adapter, params.entity, 1):
            located = params.entity.name or params.entity.point
            raise Exception(f"Failed to select motor entity ({located!r})")
        selection = _selected_object(adapter)
        if selection is None:
            raise Exception("Motor location/direction selection returned null")
        adapter._attempt(lambda: setattr(data, "DirectionReference", selection))
        adapter._attempt(lambda: setattr(data, "Location", selection))

        if params.component:
            comp = _resolve_component(adapter, params.component)
            if comp is not None:
                adapter._attempt(lambda: setattr(data, "RelativeComponent", comp))

        speed = float(params.speed)
        # Linear motor speed arrives in mm/s; the API is SI (m/s). Rotary
        # speed passes through (RPM, the rotary motor's native unit).
        if params.motor_type == "linear":
            speed = speed / 1000.0
        adapter._attempt(lambda: data.ConstantSpeedMotor(speed))
        if params.reverse:
            adapter._attempt(lambda: setattr(data, "ReverseDirection", True))

        feature = adapter._attempt(lambda: study.CreateFeature(data), default=None)
        if feature is None:
            raise Exception("CreateFeature failed for motor")
        adapter._attempt(lambda: adapter.currentModel.ClearSelection2(True))
        return {
            "name": str(adapter._attempt(lambda: feature.Name, default="") or ""),
            "motor_type": params.motor_type,
            "speed": float(params.speed),
        }

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("add_motor", _operation),
    )


def _resolve_component(adapter: Any, name: str) -> Any:
    """Resolve an assembly component dispatch by name.

    Args:
        adapter: Connected adapter.
        name: Component name as shown in the tree.

    Returns:
        Any: ``IComponent2`` dispatch or ``None``.
    """
    from .assembly import _qualify_entity_name

    qualified = _qualify_entity_name(adapter, name)
    selected = adapter._attempt(
        lambda: adapter.currentModel.Extension.SelectByID2(
            qualified, "COMPONENT", 0.0, 0.0, 0.0, False, 0, None, 0
        ),
        default=False,
    )
    if not selected:
        return None
    comp = adapter._attempt(
        lambda: adapter.currentModel.SelectionManager.GetSelectedObjectsComponent3(
            1, -1
        ),
        default=None,
    )
    adapter._attempt(lambda: adapter.currentModel.ClearSelection2(True))
    return comp


def _add_gravity_impl(
    adapter: Any, params: MotionGravityParameters
) -> AdapterResult[dict[str, Any]]:
    """Add gravity to a motion study.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Axis, strength and direction.

    Returns:
        AdapterResult[dict[str, Any]]: Created gravity feature or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    axis = _GRAVITY_AXES.get(params.axis)
    if axis is None:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error=f"Unknown axis: {params.axis!r} "
            f"(expected one of {sorted(_GRAVITY_AXES)})",
        )

    def _operation() -> dict[str, Any]:
        mgr = _motion_manager(adapter)
        if mgr is None:
            raise Exception("MotionManager unavailable")
        study = _resolve_study(adapter, mgr, params.study_name)
        data = adapter._attempt(
            lambda: study.CreateDefinition(_FEAT_GRAVITY), default=None
        )
        if data is None:
            raise Exception("CreateDefinition failed for gravity")
        adapter._attempt(lambda: setattr(data, "Axis", axis))
        adapter._attempt(lambda: setattr(data, "Strength", float(params.strength)))
        adapter._attempt(
            lambda: setattr(data, "ReverseDirection", bool(params.reverse))
        )
        feature = adapter._attempt(lambda: study.CreateFeature(data), default=None)
        if feature is None:
            raise Exception("CreateFeature failed for gravity")
        return {
            "name": str(adapter._attempt(lambda: feature.Name, default="") or ""),
            "axis": params.axis,
            "strength": float(params.strength),
        }

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("add_gravity", _operation),
    )


def _calculate_motion_impl(
    adapter: Any, params: MotionStudyRefParameters
) -> AdapterResult[dict[str, Any]]:
    """Solve a motion study.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Target study name.

    Returns:
        AdapterResult[dict[str, Any]]: Calculation result or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")

    def _operation() -> dict[str, Any]:
        mgr = _motion_manager(adapter)
        if mgr is None:
            raise Exception("MotionManager unavailable")
        study = _resolve_study(adapter, mgr, params.name)
        ok = adapter._attempt(lambda: study.Calculate(), default=False)
        if not ok:
            raise Exception("Motion study calculation failed")
        return {"name": adapter._active_motion_study, "calculated": True}

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("calculate_motion", _operation),
    )


def _set_motion_time_impl(
    adapter: Any, params: MotionTimeParameters
) -> AdapterResult[dict[str, Any]]:
    """Position a calculated motion study at a point in time.

    After this, component transforms reflect the solved pose at ``time`` —
    callers read each component's transform to sample the motion.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Time in seconds and target study name.

    Returns:
        AdapterResult[dict[str, Any]]: Applied time or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")

    def _operation() -> dict[str, Any]:
        mgr = _motion_manager(adapter)
        if mgr is None:
            raise Exception("MotionManager unavailable")
        study = _resolve_study(adapter, mgr, params.study_name)
        adapter._attempt(lambda: study.SetTime(float(params.time)))
        return {"name": adapter._active_motion_study, "time": float(params.time)}

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("set_motion_time", _operation),
    )


def _export_motion_avi_impl(
    adapter: Any, params: MotionExportParameters
) -> AdapterResult[dict[str, Any]]:
    """Export a motion study animation to an AVI file.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Output path and target study name.

    Returns:
        AdapterResult[dict[str, Any]]: Output path or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")

    def _operation() -> dict[str, Any]:
        mgr = _motion_manager(adapter)
        if mgr is None:
            raise Exception("MotionManager unavailable")
        study = _resolve_study(adapter, mgr, params.study_name)
        avi_params = adapter._attempt(lambda: mgr.CreateAVIParameter(), default=None)
        ok = adapter._attempt(
            lambda: study.SaveToAVI(params.file_path, avi_params), default=False
        )
        if not ok:
            raise Exception(f"SaveToAVI failed for {params.file_path!r}")
        return {"name": adapter._active_motion_study, "file_path": params.file_path}

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("export_motion_avi", _operation),
    )


def _list_motion_studies_impl(adapter: Any) -> AdapterResult[list[dict[str, Any]]]:
    """List the motion studies of the active document.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.

    Returns:
        AdapterResult[list[dict[str, Any]]]: One entry per study or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")

    def _operation() -> list[dict[str, Any]]:
        mgr = _motion_manager(adapter)
        if mgr is None:
            raise Exception("MotionManager unavailable")
        studies: list[dict[str, Any]] = []
        for name in _study_names(adapter, mgr):
            study = adapter._attempt(lambda n=name: mgr.GetMotionStudy(n), default=None)
            study_type = (
                adapter._attempt(lambda s=study: int(s.StudyType), default=None)
                if study is not None
                else None
            )
            studies.append({"name": name, "study_type": study_type})
        return studies

    return cast(
        AdapterResult[list[dict[str, Any]]],
        adapter._handle_com_operation("list_motion_studies", _operation),
    )
