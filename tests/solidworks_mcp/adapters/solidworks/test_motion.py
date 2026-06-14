"""Direct branch coverage tests for adapters.solidworks.motion."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
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
)
from solidworks_mcp.adapters.solidworks.motion import SolidWorksMotionMixin


class _FakeStudy:
    """A minimal IMotionStudy stand-in recording the calls made to it."""

    def __init__(self, name: str = "Motion Study 1") -> None:
        self.Name = name
        self.StudyType = 1  # defaults to Animation until set
        self.duration: float | None = None
        self.activated = 0
        self.times: list[float] = []
        self.calculate_result = True
        self.created_features: list[object] = []
        self.definitions: list[int] = []
        self.flagged: list[str] = []
        self.saved_avi: tuple[str, object] | None = None
        self.save_avi_result = True

    def _FlagAsMethod(self, *names):  # noqa: N802
        self.flagged.extend(names)

    def Activate(self):  # noqa: N802
        self.activated += 1

    def SetDuration(self, value):  # noqa: N802
        self.duration = float(value)

    def SetTime(self, value):  # noqa: N802
        self.times.append(float(value))

    def Calculate(self):  # noqa: N802
        return self.calculate_result

    def CreateDefinition(self, feature_id):  # noqa: N802
        self.definitions.append(feature_id)
        self.last_definition = _FakeFeatureData()
        return self.last_definition

    def CreateFeature(self, data):  # noqa: N802
        feature = _FakeFeature(f"Feature{len(self.created_features) + 1}")
        self.created_features.append(feature)
        return feature

    def SaveToAVI(self, path, params):  # noqa: N802
        self.saved_avi = (path, params)
        return self.save_avi_result


class _FakeFeatureData:
    """An ISimulation*FeatureData stand-in capturing assigned members."""

    def __init__(self) -> None:
        self.DirectionReference = None
        self.Location = None
        self.RelativeComponent = None
        self.ReverseDirection = False
        self.Axis = None
        self.Strength = None
        self.constant_speed: float | None = None
        self.endpoints: tuple | None = None

    def ConstantSpeedMotor(self, speed):  # noqa: N802
        self.constant_speed = float(speed)

    def SetEndPoints(self, p1, p2):  # noqa: N802
        self.endpoints = (p1, p2)


class _FakeFeature:
    def __init__(self, name: str) -> None:
        self.Name = name


class _FakeManager:
    def __init__(self, study: _FakeStudy) -> None:
        self._study = study
        self.created = 0
        self.flagged: list[str] = []
        self.avi_params_made = 0

    def _FlagAsMethod(self, *names):  # noqa: N802
        self.flagged.extend(names)

    def GetMotionStudyNames(self):  # noqa: N802
        return [self._study.Name] if self.created else []

    def CreateMotionStudy(self):  # noqa: N802
        self.created += 1
        return self._study

    def GetMotionStudy(self, name):  # noqa: N802
        if name == self._study.Name:
            return self._study
        return None

    def CreateAVIParameter(self):  # noqa: N802
        self.avi_params_made += 1
        return object()


class _FakeSelectionManager:
    def __init__(self, selected) -> None:
        self._selected = selected

    def GetSelectedObject6(self, mark, which):  # noqa: N802
        return self._selected

    def GetSelectedObjectsComponent3(self, mark, which):  # noqa: N802
        return _FakeComponentRef()


class _FakeComponentRef:
    Name2 = "spinner-1"


class _FakeExtension:
    def __init__(self, manager, select_ok: bool = True) -> None:
        self._manager = manager
        self._select_ok = select_ok

    def GetMotionStudyManager(self):  # noqa: N802
        return self._manager

    def SelectByID2(self, *args):  # noqa: N802
        return self._select_ok


class _FakeModel:
    def __init__(self, manager, selected, select_ok: bool = True) -> None:
        self.Extension = _FakeExtension(manager, select_ok)
        self.SelectionManager = _FakeSelectionManager(selected)
        self.cleared = 0

    def GetTitle(self):  # noqa: N802
        return "asm.SLDASM"

    def ClearSelection2(self, flag):  # noqa: N802
        self.cleared += 1


class _FakeApp:
    def __init__(self) -> None:
        self.loaded: list[str] = []

    def LoadAddIn(self, title):  # noqa: N802
        self.loaded.append(title)
        return 0


class _MotionAdapter(SolidWorksMotionMixin):
    """A SolidWorksMotionMixin wired to fake COM objects for unit tests."""

    def __init__(self, model=None, app=None) -> None:
        self.currentModel = model
        self.swApp = app
        self._active_motion_study = ""

    def _handle_com_operation(self, _name, callback):
        try:
            return AdapterResult(status=AdapterResultStatus.SUCCESS, data=callback())
        except Exception as exc:
            return AdapterResult(status=AdapterResultStatus.ERROR, error=str(exc))

    def _attempt(self, callback, default=None):
        try:
            return callback()
        except Exception:
            return default


def _adapter_with_study(study: _FakeStudy, selected=None, select_ok=True):
    manager = _FakeManager(study)
    model = _FakeModel(
        manager, selected if selected is not None else object(), select_ok
    )
    return _MotionAdapter(model=model, app=_FakeApp()), manager


@pytest.mark.asyncio
async def test_create_motion_study_sets_type_and_activates():
    study = _FakeStudy()

    # Setting StudyType updates the read-back value (mirror real behaviour).
    class _TrackingStudy(_FakeStudy):
        pass

    study = _TrackingStudy()
    adapter, manager = _adapter_with_study(study)

    result = await adapter.create_motion_study(
        MotionStudyParameters(study_type="motion_analysis", duration=6.0)
    )
    assert result.status is AdapterResultStatus.SUCCESS
    assert result.data["study_type"] == "motion_analysis"
    assert result.data["duration"] == 6.0
    assert study.StudyType == 4  # motion_analysis
    assert study.duration == 6.0
    assert study.activated >= 1
    assert adapter._active_motion_study == study.Name


@pytest.mark.asyncio
async def test_create_motion_study_unknown_type_errors():
    adapter, _ = _adapter_with_study(_FakeStudy())
    result = await adapter.create_motion_study(MotionStudyParameters(study_type="nope"))
    assert result.status is AdapterResultStatus.ERROR
    assert "Unknown study_type" in result.error


@pytest.mark.asyncio
async def test_create_motion_study_no_model_errors():
    adapter = _MotionAdapter(model=None)
    result = await adapter.create_motion_study(MotionStudyParameters())
    assert result.status is AdapterResultStatus.ERROR
    assert "No active model" in result.error


@pytest.mark.asyncio
async def test_create_motion_study_type_not_applied_errors():
    class _StubbornStudy(_FakeStudy):
        def __setattr__(self, key, value):
            # Refuse to change StudyType — simulate add-in not loaded.
            if key == "StudyType" and getattr(self, "_locked", False):
                return
            super().__setattr__(key, value)

    study = _StubbornStudy()
    study._locked = True
    adapter, _ = _adapter_with_study(study)
    result = await adapter.create_motion_study(
        MotionStudyParameters(study_type="motion_analysis")
    )
    assert result.status is AdapterResultStatus.ERROR
    assert "did not take" in result.error
    assert "SOLIDWORKS Motion" in result.error


@pytest.mark.asyncio
async def test_add_motor_rotary_sets_constant_speed():
    study = _FakeStudy()
    selected = object()
    adapter, _ = _adapter_with_study(study, selected=selected)
    adapter._active_motion_study = study.Name

    result = await adapter.add_motor(
        MotionMotorParameters(
            motor_type="rotary",
            entity=MateEntityRef(entity_type="AXIS", name="Axis1@crank-1@asm"),
            speed=30.0,
        )
    )
    assert result.status is AdapterResultStatus.SUCCESS
    assert result.data["motor_type"] == "rotary"
    assert result.data["speed"] == 30.0
    assert study.definitions == [78]  # rotary motor feature id
    data = study.created_features  # feature created
    assert len(data) == 1


@pytest.mark.asyncio
async def test_add_motor_linear_converts_mm_per_s_to_m_per_s():
    study = _FakeStudy()
    captured: dict[str, float] = {}

    class _CapturingStudy(_FakeStudy):
        def CreateDefinition(self, feature_id):  # noqa: N802
            self.definitions.append(feature_id)
            data = _FakeFeatureData()
            orig = data.ConstantSpeedMotor

            def _capture(speed):
                captured["speed"] = speed
                orig(speed)

            data.ConstantSpeedMotor = _capture
            return data

    study = _CapturingStudy()
    adapter, _ = _adapter_with_study(study, selected=object())
    adapter._active_motion_study = study.Name

    result = await adapter.add_motor(
        MotionMotorParameters(
            motor_type="linear",
            entity=MateEntityRef(entity_type="EDGE", name="Edge1@slide-1@asm"),
            speed=1000.0,  # mm/s
        )
    )
    assert result.status is AdapterResultStatus.SUCCESS
    assert captured["speed"] == pytest.approx(1.0)  # 1000 mm/s -> 1 m/s
    assert study.definitions == [77]  # linear motor feature id


@pytest.mark.asyncio
async def test_add_motor_unknown_type_errors():
    adapter, _ = _adapter_with_study(_FakeStudy())
    result = await adapter.add_motor(
        MotionMotorParameters(
            motor_type="screw",
            entity=MateEntityRef(entity_type="AXIS", name="Axis1@x@asm"),
        )
    )
    assert result.status is AdapterResultStatus.ERROR
    assert "Unknown motor_type" in result.error


@pytest.mark.asyncio
async def test_add_motor_selection_failure_errors():
    study = _FakeStudy()
    adapter, _ = _adapter_with_study(study, selected=object(), select_ok=False)
    adapter._active_motion_study = study.Name
    result = await adapter.add_motor(
        MotionMotorParameters(
            motor_type="rotary",
            entity=MateEntityRef(entity_type="AXIS", name="Axis1@crank-1@asm"),
        )
    )
    assert result.status is AdapterResultStatus.ERROR
    assert "Failed to resolve motor entity" in result.error


@pytest.mark.asyncio
async def test_add_motor_by_component_uses_corresponding_face(monkeypatch):
    study = _FakeStudy()
    adapter, _ = _adapter_with_study(study, selected=object())
    adapter._active_motion_study = study.Name
    import solidworks_mcp.adapters.solidworks.motion as motion

    sentinel = object()
    seen: dict[str, object] = {}

    def _fake_face(_adapter, component, point=None):
        seen["component"] = component
        seen["point"] = point
        return sentinel

    monkeypatch.setattr(motion, "_component_cylindrical_face", _fake_face)

    result = await adapter.add_motor(
        MotionMotorParameters(
            motor_type="rotary",
            entity=MateEntityRef(
                entity_type="FACE", component="drive-train-1/crankshaft-1"
            ),
            speed=30.0,
        )
    )
    assert result.status is AdapterResultStatus.SUCCESS
    assert seen["component"] == "drive-train-1/crankshaft-1"
    # The corresponding entity is assigned directly as the motor reference.
    assert study.last_definition.Location is sentinel
    assert study.last_definition.DirectionReference is sentinel


@pytest.mark.asyncio
async def test_add_motor_by_component_axis_uses_named_feature(monkeypatch):
    """component + name resolves the named axis via GetCorresponding (no face
    walk) -- the depth-2 cam/crank path."""
    study = _FakeStudy()
    adapter, _ = _adapter_with_study(study, selected=object())
    adapter._active_motion_study = study.Name
    import solidworks_mcp.adapters.solidworks.motion as motion

    sentinel = object()
    seen: dict[str, object] = {}

    def _fake_named(_adapter, component, feature_name):
        seen["component"] = component
        seen["feature"] = feature_name
        return sentinel

    def _explode(*_a, **_k):  # the face walk must NOT be taken for a named axis
        raise AssertionError("cylindrical-face walk used for a named axis")

    monkeypatch.setattr(motion, "_component_named_feature", _fake_named)
    monkeypatch.setattr(motion, "_component_cylindrical_face", _explode)

    result = await adapter.add_motor(
        MotionMotorParameters(
            motor_type="rotary",
            entity=MateEntityRef(
                entity_type="AXIS",
                component="drive-train-1/crankshaft-1",
                name="Axis1",
            ),
            speed=20.0,
        )
    )
    assert result.status is AdapterResultStatus.SUCCESS
    assert seen == {"component": "drive-train-1/crankshaft-1", "feature": "Axis1"}
    assert study.last_definition.Location is sentinel
    assert study.last_definition.DirectionReference is sentinel


@pytest.mark.asyncio
async def test_add_motor_by_component_not_found_errors(monkeypatch):
    study = _FakeStudy()
    adapter, _ = _adapter_with_study(study, selected=object())
    adapter._active_motion_study = study.Name
    import solidworks_mcp.adapters.solidworks.motion as motion

    monkeypatch.setattr(
        motion, "_component_cylindrical_face", lambda *a, **k: None
    )
    result = await adapter.add_motor(
        MotionMotorParameters(
            motor_type="rotary",
            entity=MateEntityRef(entity_type="FACE", component="ghost-1/part-1"),
        )
    )
    assert result.status is AdapterResultStatus.ERROR
    assert "Failed to resolve motor entity" in result.error
    assert "ghost-1/part-1" in result.error


@pytest.mark.asyncio
async def test_add_gravity_sets_axis_and_strength():
    study = _FakeStudy()
    adapter, _ = _adapter_with_study(study)
    adapter._active_motion_study = study.Name
    result = await adapter.add_gravity(
        MotionGravityParameters(axis="y", strength=9.81, reverse=True)
    )
    assert result.status is AdapterResultStatus.SUCCESS
    assert result.data["axis"] == "y"
    assert study.definitions == [74]  # gravity feature id


@pytest.mark.asyncio
async def test_add_gravity_unknown_axis_errors():
    adapter, _ = _adapter_with_study(_FakeStudy())
    result = await adapter.add_gravity(MotionGravityParameters(axis="w"))
    assert result.status is AdapterResultStatus.ERROR
    assert "Unknown axis" in result.error


@pytest.mark.asyncio
async def test_calculate_motion_success_and_failure():
    study = _FakeStudy()
    adapter, _ = _adapter_with_study(study)
    adapter._active_motion_study = study.Name
    ok = await adapter.calculate_motion(MotionStudyRefParameters())
    assert ok.status is AdapterResultStatus.SUCCESS
    assert ok.data["calculated"] is True

    study.calculate_result = False
    fail = await adapter.calculate_motion(MotionStudyRefParameters())
    assert fail.status is AdapterResultStatus.ERROR
    assert "calculation failed" in fail.error


@pytest.mark.asyncio
async def test_calculate_motion_no_active_study_errors():
    adapter, _ = _adapter_with_study(_FakeStudy())
    # No active study, none named.
    result = await adapter.calculate_motion(MotionStudyRefParameters())
    assert result.status is AdapterResultStatus.ERROR
    assert "No motion study specified" in result.error


@pytest.mark.asyncio
async def test_set_motion_time_records_time():
    study = _FakeStudy()
    adapter, _ = _adapter_with_study(study)
    adapter._active_motion_study = study.Name
    result = await adapter.set_motion_time(MotionTimeParameters(time=2.5))
    assert result.status is AdapterResultStatus.SUCCESS
    assert study.times == [2.5]


@pytest.mark.asyncio
async def test_export_motion_video_success(tmp_path, monkeypatch):
    import solidworks_mcp.adapters.solidworks.motion as motion

    # Make the writer "finish" instantly and have SaveToAVI drop a real file.
    monkeypatch.setattr(motion, "_VIDEO_POLL_INTERVAL", 0.0)
    monkeypatch.setattr(motion, "_VIDEO_STABLE_POLLS", 1)

    def _fake_save(self, path, params):
        Path(path).write_bytes(b"FAKE-H264-DATA")
        self.saved_avi = (path, params)
        return self.save_avi_result

    monkeypatch.setattr(_FakeStudy, "SaveToAVI", _fake_save)

    study = _FakeStudy()
    adapter, manager = _adapter_with_study(study)
    adapter._active_motion_study = study.Name
    out = tmp_path / "op.mp4"
    ok = await adapter.export_motion_video(MotionExportParameters(file_path=str(out)))
    assert ok.status is AdapterResultStatus.SUCCESS
    assert ok.data["file_path"] == str(out)
    assert ok.data["bytes"] > 0
    assert manager.avi_params_made == 1
    assert out.exists()


@pytest.mark.asyncio
async def test_export_motion_video_rejects_avi():
    study = _FakeStudy()
    adapter, _ = _adapter_with_study(study)
    adapter._active_motion_study = study.Name
    res = await adapter.export_motion_video(
        MotionExportParameters(file_path="C:/out/op.avi")
    )
    assert res.status is AdapterResultStatus.ERROR
    assert ".avi" in res.error and "headlessly" in res.error


@pytest.mark.asyncio
async def test_export_motion_video_save_returns_false(tmp_path, monkeypatch):
    import solidworks_mcp.adapters.solidworks.motion as motion

    monkeypatch.setattr(motion, "_VIDEO_POLL_INTERVAL", 0.0)
    monkeypatch.setattr(motion, "_VIDEO_STABLE_POLLS", 1)
    study = _FakeStudy()
    study.save_avi_result = False
    adapter, _ = _adapter_with_study(study)
    adapter._active_motion_study = study.Name
    res = await adapter.export_motion_video(
        MotionExportParameters(file_path=str(tmp_path / "op.mp4"))
    )
    assert res.status is AdapterResultStatus.ERROR
    assert "SaveToAVI returned false" in res.error


@pytest.mark.asyncio
async def test_list_motion_studies_returns_entries():
    study = _FakeStudy()
    adapter, manager = _adapter_with_study(study)
    manager.created = 1  # so GetMotionStudyNames returns the study
    result = await adapter.list_motion_studies()
    assert result.status is AdapterResultStatus.SUCCESS
    assert result.data[0]["name"] == study.Name


@pytest.mark.asyncio
async def test_ensure_motion_addin_loads():
    adapter, _ = _adapter_with_study(_FakeStudy())
    result = await adapter.ensure_motion_addin()
    assert result.status is AdapterResultStatus.SUCCESS
    assert adapter.swApp.loaded == ["SOLIDWORKS Motion"]


def _two_endpoints():
    return [
        MateEntityRef(entity_type="VERTEX", point=[0.0, 0.0, 0.0]),
        MateEntityRef(entity_type="VERTEX", point=[0.0, 30.0, 0.0]),
    ]


@pytest.mark.asyncio
async def test_add_motion_spring_linear_sets_k_and_free_length():
    study = _FakeStudy()
    adapter, _ = _adapter_with_study(study)
    adapter._active_motion_study = study.Name
    result = await adapter.add_motion_spring(
        MotionSpringParameters(
            spring_type="linear",
            endpoints=_two_endpoints(),
            spring_constant=1500.0,
            free_length=25.0,
            damping_constant=4.0,
        )
    )
    assert result.status is AdapterResultStatus.SUCCESS
    assert study.definitions == [81]  # linear motion spring feature id
    data = study.last_definition
    assert data.endpoints is not None  # SetEndPoints called
    assert data.SpringConstant == 1500.0
    assert data.FreeLength == pytest.approx(0.025)  # 25 mm -> 0.025 m
    assert data.HasDamper is True
    assert data.DampingConstant == 4.0


@pytest.mark.asyncio
async def test_add_motion_spring_torsional_sets_free_angle():
    study = _FakeStudy()
    adapter, _ = _adapter_with_study(study)
    adapter._active_motion_study = study.Name
    result = await adapter.add_motion_spring(
        MotionSpringParameters(
            spring_type="torsional",
            endpoints=_two_endpoints(),
            spring_constant=2.5,
            free_angle=90.0,
        )
    )
    assert result.status is AdapterResultStatus.SUCCESS
    assert study.definitions == [82]  # torsional motion spring feature id
    assert study.last_definition.FreeAngle == pytest.approx(math.pi / 2)


@pytest.mark.asyncio
async def test_add_motion_spring_unknown_type_errors():
    adapter, _ = _adapter_with_study(_FakeStudy())
    result = await adapter.add_motion_spring(
        MotionSpringParameters(
            spring_type="coil", endpoints=_two_endpoints(), spring_constant=1.0
        )
    )
    assert result.status is AdapterResultStatus.ERROR
    assert "Unknown spring_type" in result.error


@pytest.mark.asyncio
async def test_add_motion_spring_requires_two_endpoints():
    adapter, _ = _adapter_with_study(_FakeStudy())
    result = await adapter.add_motion_spring(
        MotionSpringParameters(
            endpoints=[MateEntityRef(entity_type="VERTEX", point=[0, 0, 0])],
            spring_constant=1.0,
        )
    )
    assert result.status is AdapterResultStatus.ERROR
    assert "exactly two endpoints" in result.error


@pytest.mark.asyncio
async def test_add_motion_damper_sets_constant():
    study = _FakeStudy()
    adapter, _ = _adapter_with_study(study)
    adapter._active_motion_study = study.Name
    result = await adapter.add_motion_damper(
        MotionDamperParameters(endpoints=_two_endpoints(), damping_constant=7.0)
    )
    assert result.status is AdapterResultStatus.SUCCESS
    assert study.definitions == [83]  # linear damper feature id
    assert study.last_definition.DampingConstant == 7.0


@pytest.mark.asyncio
async def test_add_motion_force_constant_value_and_action():
    study = _FakeStudy()
    adapter, _ = _adapter_with_study(study)
    adapter._active_motion_study = study.Name
    result = await adapter.add_motion_force(
        MotionForceParameters(
            force_type="linear_force",
            action=MateEntityRef(entity_type="FACE", point=[1.0, 1.0, 1.0]),
            magnitude=9.81,
        )
    )
    assert result.status is AdapterResultStatus.SUCCESS
    assert study.definitions == [75]  # linear force feature id
    data = study.last_definition
    assert data.ActionType == 0  # action only
    assert data.FunctionConstantValue == 9.81
    assert data.ActionLocation is not None


@pytest.mark.asyncio
async def test_add_motion_force_torque_uses_torque_feature():
    study = _FakeStudy()
    adapter, _ = _adapter_with_study(study)
    adapter._active_motion_study = study.Name
    result = await adapter.add_motion_force(
        MotionForceParameters(
            force_type="torque",
            action=MateEntityRef(entity_type="AXIS", name="Axis1@x@asm"),
            magnitude=1.2,
            action_only=False,
        )
    )
    assert result.status is AdapterResultStatus.SUCCESS
    assert study.definitions == [76]  # torque feature id
    assert study.last_definition.ActionType == 1  # action and reaction


@pytest.mark.asyncio
async def test_add_motion_force_unknown_type_errors():
    adapter, _ = _adapter_with_study(_FakeStudy())
    result = await adapter.add_motion_force(
        MotionForceParameters(
            force_type="drag",
            action=MateEntityRef(entity_type="FACE", point=[0, 0, 0]),
            magnitude=1.0,
        )
    )
    assert result.status is AdapterResultStatus.ERROR
    assert "Unknown force_type" in result.error
