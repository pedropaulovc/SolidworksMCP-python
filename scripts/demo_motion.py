r"""Live end-to-end demo for the Motion-study core surface (PR-M1).

Builds a throwaway one-revolute spinner from scratch and drives it with a
constant-speed rotary motor in a SOLIDWORKS Motion (MotionAnalysis) study,
then proves the solver ran by scrubbing the calculated study to several
times and reading the spinner's transform — a constant-speed motor is
kinematic, so the spin angle must advance linearly at ``speed`` RPM.

Geometry (mirrors ``demo_assembly_mates.py``'s throwaway-part style):

* a fixed **shaft** disc (auto-fixed as the first component), and
* a **spinner** disc mated ``concentric`` (coaxial) + ``coincident`` (front
  planes) to the shaft — exactly the one rotational DOF a motor can drive.

Then: ``ensure_motion_addin`` → ``create_motion_study`` (motion_analysis) →
``add_motor`` (rotary, on the spinner axis) → ``calculate_motion`` →
``set_motion_time`` at several times (reading the spin each time) →
``export_motion_avi``. The acceptance check is that the measured spin rate
matches the commanded ``speed`` RPM within tolerance.

Run with the project virtualenv on a Windows box with SOLIDWORKS open and
the SOLIDWORKS Motion add-in available::

    .\.venv\Scripts\python.exe scripts\demo_motion.py
"""

from __future__ import annotations

import asyncio
import math
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from solidworks_mcp.adapters.base import (  # noqa: E402
    AddMateParameters,
    CreateAxisParameters,
    ExtrusionParameters,
    InsertComponentParameters,
    MateEntityRef,
    MotionExportParameters,
    MotionGravityParameters,
    MotionMotorParameters,
    MotionStudyParameters,
    MotionStudyRefParameters,
    MotionTimeParameters,
)
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter  # noqa: E402

SHAFT_RADIUS = 5.0
SHAFT_THICKNESS = 40.0
SPINNER_RADIUS = 25.0
SPINNER_THICKNESS = 8.0

# Constant-speed rotary motor: 60 RPM == 360 deg/s, so after t seconds the
# spinner has turned 360*t degrees. Sample inside one revolution (t < 1 s)
# to keep each measured angle unambiguous under atan2 wrap.
MOTOR_RPM = 60.0
DEG_PER_S = MOTOR_RPM * 360.0 / 60.0  # 360 deg/s
STUDY_DURATION = 2.0
SAMPLE_TIMES = (0.0, 0.1, 0.2, 0.25)  # 0, 36, 72, 90 deg
ANGLE_TOLERANCE_DEG = 5.0


def _check(label: str, result) -> None:
    """Raise with the COM error attached when an adapter result is not success."""
    if not result.is_success:
        raise RuntimeError(f"{label} failed: {result.error}")
    print(f"  OK  {label}")


def _read_member(obj, name):
    """Read a COM accessor that pywin32 may expose as a method or a property."""
    member = getattr(obj, name, None)
    if not callable(member):
        return member
    try:
        return member()
    except Exception:
        return member


def _component_z_rotation_deg(adapter, name: str) -> float:
    """Read a component's rotation about Z from its transform rows."""
    component = adapter.currentModel.GetComponentByName(name)
    if component is None:
        raise RuntimeError(f"Component not found for transform readback: {name!r}")
    array = list(_read_member(_read_member(component, "Transform2"), "ArrayData"))
    # Row 0 is the image of the component x-axis in assembly space.
    return math.degrees(math.atan2(float(array[1]), float(array[0])))


async def _build_disc(adapter, radius: float, thickness: float, path: Path) -> None:
    """Build a disc part with a reference axis down the cylinder."""
    _check("create_part", await adapter.create_part())
    _check("create_sketch Front", await adapter.create_sketch("Front"))
    _check(f"add_circle R{radius}", await adapter.add_circle(0.0, 0.0, radius))
    _check("exit_sketch", await adapter.exit_sketch())
    _check(
        f"create_extrusion depth={thickness} (midplane)",
        await adapter.create_extrusion(
            ExtrusionParameters(depth=thickness, both_directions=True)
        ),
    )
    _check(
        "create_axis (cylindrical_face)",
        await adapter.create_axis(
            CreateAxisParameters(mode="cylindrical_face", face_point=[radius, 0.0, 0.0])
        ),
    )
    _check(f"save_file -> {path.name}", await adapter.save_file(str(path)))


def _front_plane(component: str) -> MateEntityRef:
    return MateEntityRef(entity_type="PLANE", name=f"Front Plane@{component}")


async def build_demo(out_dir: Path) -> dict[str, str]:
    """Build the spinner, drive it with a motor study, and verify the solve."""
    out_dir.mkdir(parents=True, exist_ok=True)
    shaft_path = (out_dir / "motion_demo_shaft.SLDPRT").resolve()
    spinner_path = (out_dir / "motion_demo_spinner.SLDPRT").resolve()
    asm_path = (out_dir / "motion_demo_assembly.SLDASM").resolve()
    avi_path = (out_dir / "motion_demo_operation.avi").resolve()

    adapter = PyWin32Adapter({})
    print("Connecting to SolidWorks ...")
    await adapter.connect()
    print(f"Connected: swApp={type(adapter.swApp).__name__}")

    try:
        adapter._attempt(lambda: adapter.swApp.CloseAllDocuments(True), default=None)
        print("  OK  CloseAllDocuments (start from a clean session)")

        # --- Throwaway parts -------------------------------------------------
        print("Part: fixed shaft")
        await _build_disc(adapter, SHAFT_RADIUS, SHAFT_THICKNESS, shaft_path)
        print("Part: spinner")
        await _build_disc(adapter, SPINNER_RADIUS, SPINNER_THICKNESS, spinner_path)

        # --- Assembly: one revolute DOF -------------------------------------
        print("Assembly: shaft (fixed) + spinner (concentric + coincident)")
        _check("create_assembly", await adapter.create_assembly())
        shaft = await adapter.insert_component(
            InsertComponentParameters(file_path=str(shaft_path))
        )
        _check("insert_component shaft (auto-fixed)", shaft)
        shaft_name = shaft.data["name"]

        spinner = await adapter.insert_component(
            InsertComponentParameters(file_path=str(spinner_path))
        )
        _check("insert_component spinner", spinner)
        spinner_name = spinner.data["name"]

        # Concentric on the cylinder faces (axis-axis concentric is rejected;
        # pick the faces by point at z=0, the midplane both bodies straddle),
        # then coincident front planes — leaves exactly the spin DOF.
        _check(
            "add_mate concentric spinner <-> shaft (cylinder faces)",
            await adapter.add_mate(
                AddMateParameters(
                    mate_type="concentric",
                    entities=[
                        MateEntityRef(
                            entity_type="FACE", point=[SPINNER_RADIUS, 0.0, 0.0]
                        ),
                        MateEntityRef(
                            entity_type="FACE", point=[SHAFT_RADIUS, 0.0, 0.0]
                        ),
                    ],
                )
            ),
        )
        _check(
            "add_mate coincident spinner <-> shaft (front planes)",
            await adapter.add_mate(
                AddMateParameters(
                    mate_type="coincident",
                    entities=[_front_plane(spinner_name), _front_plane(shaft_name)],
                )
            ),
        )
        _check(f"save_file -> {asm_path.name}", await adapter.save_file(str(asm_path)))

        # --- Motion study ----------------------------------------------------
        print("Motion: add-in + study + motor + solve")
        _check("ensure_motion_addin", await adapter.ensure_motion_addin())
        study = await adapter.create_motion_study(
            MotionStudyParameters(study_type="motion_analysis", duration=STUDY_DURATION)
        )
        _check("create_motion_study (motion_analysis)", study)
        study_name = study.data["name"]
        print(f"  study: {study_name}")

        _check(
            f"add_motor rotary {MOTOR_RPM} RPM on spinner axis",
            await adapter.add_motor(
                MotionMotorParameters(
                    motor_type="rotary",
                    entity=MateEntityRef(
                        entity_type="AXIS", name=f"Axis1@{spinner_name}"
                    ),
                    speed=MOTOR_RPM,
                    component=spinner_name,
                    study_name=study_name,
                )
            ),
        )
        # Gravity is incidental here (the motor is kinematic) but exercises
        # the add_gravity path live.
        _check(
            "add_gravity (-Y)",
            await adapter.add_gravity(
                MotionGravityParameters(axis="y", reverse=True, study_name=study_name)
            ),
        )
        _check(
            "calculate_motion",
            await adapter.calculate_motion(MotionStudyRefParameters(name=study_name)),
        )

        # --- Verify the kinematic solve -------------------------------------
        print("Motion: scrub the solved study and read the spin")
        base = None
        measurements: list[tuple[float, float]] = []
        for t in SAMPLE_TIMES:
            _check(
                f"set_motion_time t={t}",
                await adapter.set_motion_time(
                    MotionTimeParameters(time=t, study_name=study_name)
                ),
            )
            raw = _component_z_rotation_deg(adapter, spinner_name)
            if base is None:
                base = raw
            swing = (raw - base) % 360.0
            expected = (DEG_PER_S * t) % 360.0
            measurements.append((t, swing))
            print(f"    t={t:.2f}s  spin={swing:7.2f} deg  (expected {expected:6.2f})")
            if abs((swing - expected + 180.0) % 360.0 - 180.0) > ANGLE_TOLERANCE_DEG:
                raise RuntimeError(
                    f"motion solve mismatch at t={t}: spin {swing:.2f} deg, "
                    f"expected {expected:.2f} deg (motor not driving the DOF)"
                )
        print(f"  OK  constant-speed motor drove {MOTOR_RPM} RPM through the solve")

        _check(
            f"export_motion_avi -> {avi_path.name}",
            await adapter.export_motion_avi(
                MotionExportParameters(file_path=str(avi_path), study_name=study_name)
            ),
        )
        return {"assembly": str(asm_path), "avi": str(avi_path)}
    finally:
        try:
            await adapter.disconnect()
            print("Disconnected.")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN disconnect failed: {exc}")


def main() -> int:
    out_dir = REPO_ROOT / "out"
    try:
        artefacts = asyncio.run(build_demo(out_dir))
    except Exception:
        traceback.print_exc()
        return 1
    print("\nDemo artefacts:")
    for key, value in artefacts.items():
        print(f"  {key}: {value or '(skipped)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
