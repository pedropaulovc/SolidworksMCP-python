r"""Live end-to-end demo for the flexible-subassembly surface (PR-M4).

Proves the three PR-M4 additions together by driving a part that lives INSIDE
a subassembly from a TOP-LEVEL motor — the pattern needed to animate a device
whose moving parts are organised into subassemblies:

* ``set_component_solving`` — make the subassembly **flexible** so its internal
  mates solve with the parent and its parts move within their DOF;
* ``suppress_mate(component=...)`` — free the pinned spin DOF by suppressing the
  driving-dimension mate that lives INSIDE the subassembly's own document
  (unreachable from the parent tree by name);
* ``add_motor(entity=MateEntityRef(component=...))`` — locate the motor on the
  spinner's cylindrical face mapped into assembly context via
  ``GetCorrespondingEntity`` (robust for a part nested in a flexible sub, where
  hand-built ``Axis1@a@b@title`` selection strings mis-resolve).

Geometry (throwaway, built from scratch):

* a **shaft** disc and a **spinner** disc are mated ``concentric`` +
  ``coincident`` inside a **subassembly**, plus an ``angle`` driver mate that
  pins the spin so the subassembly saves fully-defined;
* the subassembly is inserted into a top assembly, floated, grounded to the
  origin by three plane mates, and made **flexible**;
* the spin DOF is freed by suppressing the angle driver in the sub document, a
  rotary motor is placed on the spinner's cylindrical face, and a Basic Motion
  study is solved. The acceptance check: the spinner's pose changes across the
  solved timeline — i.e. a top-level motor drove a part inside a flexible sub.

The subassembly file is never re-saved after it is made flexible/suppressed, so
its on-disk fully-defined state is preserved.

Run with the project virtualenv on a Windows box with SOLIDWORKS open and the
SOLIDWORKS Motion add-in available::

    .\.venv\Scripts\python.exe scripts\demo_flexible_motion.py
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
    ComponentRefParameters,
    ExtrusionParameters,
    InsertComponentParameters,
    MateEntityRef,
    MotionMotorParameters,
    MotionStudyParameters,
    MotionStudyRefParameters,
    MotionTimeParameters,
    SetComponentSolvingParameters,
    SuppressMateParameters,
)
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter  # noqa: E402

SHAFT_RADIUS = 5.0
SHAFT_THICKNESS = 40.0
SPINNER_RADIUS = 25.0
SPINNER_THICKNESS = 8.0

MOTOR_RPM = 60.0
STUDY_DURATION = 2.0
SAMPLE_TIMES = (0.0, 0.1, 0.2, 0.25)


def _check(label: str, result) -> None:
    if not result.is_success:
        raise RuntimeError(f"{label} failed: {result.error}")
    print(f"  OK  {label}")


def _read_member(obj, name):
    member = getattr(obj, name, None)
    if not callable(member):
        return member
    try:
        return member()
    except Exception:
        return member


def _find_component(adapter, needle: str):
    """Return (dispatch, Name2) of the first component whose name contains needle.

    Uses GetComponents(False) so parts nested inside a subassembly are visible.
    """
    model = adapter.currentModel
    comps = adapter._attempt(lambda: model.GetComponents(False), default=None) or []
    for comp in comps:
        name = str(_read_member(comp, "Name2"))
        if needle in name:
            return comp, name
    return None, None


def _z_rotation_deg(comp) -> float:
    array = list(_read_member(_read_member(comp, "Transform2"), "ArrayData"))
    return math.degrees(math.atan2(float(array[1]), float(array[0])))


async def _build_disc(adapter, radius: float, thickness: float, path: Path) -> None:
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
    _check(f"save_file -> {path.name}", await adapter.save_file(str(path)))


def _plane(name: str, component: str) -> MateEntityRef:
    return MateEntityRef(entity_type="PLANE", name=f"{name}@{component}")


async def build_demo(out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    shaft_path = (out_dir / "flexmotion_shaft.SLDPRT").resolve()
    spinner_path = (out_dir / "flexmotion_spinner.SLDPRT").resolve()
    sub_path = (out_dir / "flexmotion_sub.SLDASM").resolve()
    asm_path = (out_dir / "flexmotion_top.SLDASM").resolve()

    adapter = PyWin32Adapter({})
    print("Connecting to SolidWorks ...")
    await adapter.connect()
    print(f"Connected: swApp={type(adapter.swApp).__name__}")

    try:
        adapter._attempt(lambda: adapter.swApp.CloseAllDocuments(True), default=None)
        print("  OK  CloseAllDocuments (start from a clean session)")

        # --- Throwaway parts -------------------------------------------------
        print("Part: shaft")
        await _build_disc(adapter, SHAFT_RADIUS, SHAFT_THICKNESS, shaft_path)
        print("Part: spinner")
        await _build_disc(adapter, SPINNER_RADIUS, SPINNER_THICKNESS, spinner_path)

        # --- Subassembly: one spin DOF, pinned by an angle driver ------------
        print("Subassembly: shaft (fixed) + spinner, spin pinned by an angle driver")
        _check("create_assembly (sub)", await adapter.create_assembly())
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

        _check(
            "add_mate concentric spinner <-> shaft (cylinder faces)",
            await adapter.add_mate(
                AddMateParameters(
                    mate_type="concentric",
                    entities=[
                        MateEntityRef(
                            entity_type="FACE", point=[SPINNER_RADIUS, 0.0, 0.0]
                        ),
                        MateEntityRef(entity_type="FACE", point=[SHAFT_RADIUS, 0.0, 0.0]),
                    ],
                )
            ),
        )
        _check(
            "add_mate coincident spinner <-> shaft (front planes)",
            await adapter.add_mate(
                AddMateParameters(
                    mate_type="coincident",
                    entities=[
                        _plane("Front Plane", spinner_name),
                        _plane("Front Plane", shaft_name),
                    ],
                )
            ),
        )
        # The spin driver: an angle between the two Right planes (both contain
        # the common axis) pins the spin so the sub saves fully-defined. This is
        # the mate we later suppress -- inside the sub doc -- to free the DOF.
        driver = await adapter.add_mate(
            AddMateParameters(
                mate_type="angle",
                entities=[
                    _plane("Right Plane", spinner_name),
                    _plane("Right Plane", shaft_name),
                ],
                angle=30.0,
            )
        )
        _check("add_mate angle driver (pins spin)", driver)
        driver_name = driver.data["name"]
        print(f"  spin driver mate in the sub = {driver_name!r}")
        _check(f"save_file -> {sub_path.name}", await adapter.save_file(str(sub_path)))

        # --- Top assembly: insert the sub, make it flexible ------------------
        print("Top assembly: insert sub, float + ground, make FLEXIBLE")
        _check("create_assembly (top)", await adapter.create_assembly())
        sub = await adapter.insert_component(
            InsertComponentParameters(file_path=str(sub_path))
        )
        _check("insert_component sub (auto-fixed)", sub)
        sub_name = sub.data["name"]

        # A fixed sub cannot be flexible: float it, then ground its placement
        # with three plane mates (it sits at identity, so they are on-solution).
        _check(
            "float_component sub",
            await adapter.float_component(ComponentRefParameters(name=sub_name)),
        )
        for plane in ("Front Plane", "Top Plane", "Right Plane"):
            _check(
                f"ground sub {plane}",
                await adapter.add_mate(
                    AddMateParameters(
                        mate_type="coincident",
                        entities=[
                            _plane(plane, sub_name),
                            MateEntityRef(entity_type="PLANE", name=plane),
                        ],
                    )
                ),
            )
        flex = await adapter.set_component_solving(
            SetComponentSolvingParameters(name=sub_name, solving="flexible")
        )
        _check("set_component_solving flexible", flex)
        print(f"  sub solving = {flex.data['solving']}")
        _check(f"save_file -> {asm_path.name}", await adapter.save_file(str(asm_path)))

        # --- Free the spin DOF inside the sub, add the motor, solve ----------
        print("Free the spin DOF: suppress the angle driver INSIDE the sub doc")
        suppressed = await adapter.suppress_mate(
            SuppressMateParameters(
                name=driver_name, suppress=True, component=sub_name
            )
        )
        _check("suppress_mate (in sub document)", suppressed)
        adapter._attempt(lambda: adapter.currentModel.ForceRebuild3(False), default=None)

        _, spinner_path_name = _find_component(adapter, "spinner")
        print(f"  spinner in top assembly = {spinner_path_name!r}")

        print("Motion: add-in + Basic Motion study + motor on the spinner face")
        _check("ensure_motion_addin", await adapter.ensure_motion_addin())
        study = await adapter.create_motion_study(
            MotionStudyParameters(
                study_type="physical_simulation", duration=STUDY_DURATION
            )
        )
        _check("create_motion_study (physical_simulation / Basic Motion)", study)
        study_name = study.data["name"]

        _check(
            f"add_motor rotary {MOTOR_RPM} RPM on the spinner cylindrical face",
            await adapter.add_motor(
                MotionMotorParameters(
                    motor_type="rotary",
                    entity=MateEntityRef(
                        entity_type="FACE", component=spinner_path_name
                    ),
                    speed=MOTOR_RPM,
                    study_name=study_name,
                )
            ),
        )
        _check(
            "calculate_motion",
            await adapter.calculate_motion(MotionStudyRefParameters(name=study_name)),
        )

        # --- Verify the motor drives the part inside the flexible sub --------
        print("Motion: scrub the solved study; the nested spinner must move")
        spinner_comp, _ = _find_component(adapter, "spinner")
        base = _z_rotation_deg(spinner_comp)
        moved = False
        for t in SAMPLE_TIMES:
            _check(
                f"set_motion_time t={t}",
                await adapter.set_motion_time(
                    MotionTimeParameters(time=t, study_name=study_name)
                ),
            )
            spinner_comp, _ = _find_component(adapter, "spinner")  # re-fetch each frame
            raw = _z_rotation_deg(spinner_comp)
            swing = (raw - base) % 360.0
            print(f"    t={t:.2f}s  spinner pose={raw:8.2f} deg  (Δ {swing:6.2f})")
            if t > 0 and abs((swing + 180.0) % 360.0 - 180.0) > 1.0:
                moved = True
        if not moved:
            raise RuntimeError(
                "the nested spinner did not move across the solved timeline "
                "(a top-level motor did not drive the flexible sub's internals)"
            )
        print("  OK  a top-level motor drove a part INSIDE the flexible subassembly")
        return {"top_assembly": str(asm_path), "subassembly": str(sub_path)}
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
