r"""Live end-to-end demo for the Phase 7 assembly surface (issue #8).

Builds the issue-#8 acceptance fixture from scratch — three throwaway
parts (a shaft and two gear discs, each with a reference axis down the
cylinder), then a 4-component assembly exercising every Phase 7A/7B/7C
tool that the toy geometry can carry:

* ``insert_component`` x4 (the first insert is auto-fixed by SolidWorks),
  ``fix_component`` on the second shaft, ``move_component`` on a gear.
* ``replace_component`` + ``remove_component`` on a sacrificial fifth
  component.
* ``add_mate``: concentric (part axes), coincident (part front planes),
  and a mechanical **gear** mate with an explicit 2:1 ratio.
* The motion check: ``rotate_component(mode="kinematic")`` spins the big
  gear 45 deg about its axis and the small gear must counter-rotate
  90 deg (inverse ratio) via the gear-mate kinematic propagation.
* ``suppress_mate`` (gear mate off -> big gear rotates back alone ->
  unsuppress), ``list_mates``, ``delete_mate``.
* ``pattern_components_circular``: 20 instances of a dedicated small-gear
  seed about an assembly-level reference axis (the 20-cone-gear acceptance
  shape), seated on a fixed base plate the shafts also butt against, on a
  ring wide enough that the instances clear each other.
* The saved state is fully defined: the gears' remaining spin DOF is
  grounded with 0-degree angle mates and every component must report
  fixed or fully constrained (``IComponent2::GetConstrainedStatus``).

Cam-follower, rack-pinion and screw mates share the same AddMate5 +
ModifyDefinition plumbing and are covered by unit tests; their live
verification happens on the real analyzer geometry in Milestone 6.

On success the script saves the parts and assembly plus an isometric PNG
to ``out/`` and exits 0.  Run with the project virtualenv on a Windows
box that already has SolidWorks open::

    .\.venv\Scripts\python.exe scripts\demo_assembly_mates.py
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
    ComponentCircularPatternParameters,
    ComponentRefParameters,
    CreateAxisParameters,
    ExtrusionParameters,
    InsertComponentParameters,
    MateEntityRef,
    MateRefParameters,
    MoveComponentParameters,
    ReplaceComponentParameters,
    RotateComponentParameters,
    SuppressMateParameters,
)
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter  # noqa: E402
from solidworks_mcp.adapters.solidworks.features import (  # noqa: E402
    _flag_feature_methods,
)

SHAFT_RADIUS = 5.0
SHAFT_LENGTH = 40.0
BIG_GEAR_RADIUS = 30.0
SMALL_GEAR_RADIUS = 15.0
GEAR_THICKNESS = 10.0
CENTRE_DISTANCE = BIG_GEAR_RADIUS + SMALL_GEAR_RADIUS  # 45 mm
GEAR_RATIO = [BIG_GEAR_RADIUS, SMALL_GEAR_RADIUS]  # 2:1
INPUT_ANGLE = 45.0
EXPECTED_OUTPUT_ANGLE = INPUT_ANGLE * GEAR_RATIO[0] / GEAR_RATIO[1]  # 90 deg
# 20 instances of a 30 mm disc need a ring radius >= 30 / (2 sin(pi/20))
# ~= 96 mm to clear each other; at 150 mm the chord between neighbours is
# 2 * 150 * sin(9 deg) ~= 47 mm.
PATTERN_RING_RADIUS = 150.0
# Base plate the fixture is mounted on: wide enough to carry the ring
# (150 + 15 = 165 mm) and thick enough to read as a plate.
PLATE_RADIUS = 180.0
PLATE_THICKNESS = 10.0
# Components extrude symmetrically about z=0 (midplane): the shafts span
# z in [-20, 20], so the plate's front face sits at z = -20 and the ring
# discs (10 mm thick) are seated on it with their backs at z = -20.
PLATE_Z = -(SHAFT_LENGTH / 2.0) - PLATE_THICKNESS / 2.0  # -25
RING_SEED_Z = -(SHAFT_LENGTH / 2.0) + GEAR_THICKNESS / 2.0  # -15


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


# swConstrainedStatus_e
_UNDER_CONSTRAINED = 2
_FULLY_CONSTRAINED = 3


def _assert_components_fully_defined(adapter) -> None:
    """Raise when any top-level component is not fixed or fully defined.

    ``IComponent2::GetConstrainedStatus`` returns swConstrainedStatus_e:
    2 = under, 3 = fully, 4 = over constrained.
    """
    asm = adapter.currentModel
    components = adapter._attempt(lambda: asm.GetComponents(True), default=None) or []
    problems = []
    for component in components:
        # GetComponents returns unflagged dispatches: without the
        # IComponent2 method flagging, GetConstrainedStatus resolves as a
        # property and the call raises.
        _flag_feature_methods(component, "IComponent2")
        comp_name = str(_read_member(component, "Name2"))
        if bool(_read_member(component, "IsFixed")):
            continue
        status = int(
            adapter._attempt(lambda c=component: c.GetConstrainedStatus(), default=-1)
        )
        if status != _FULLY_CONSTRAINED:
            kind = "under" if status == _UNDER_CONSTRAINED else f"status={status}"
            problems.append(f"{comp_name} ({kind})")
    print(f"  checked {len(components)} components for free DOF")
    if problems:
        raise RuntimeError("components not fully defined: " + ", ".join(problems))


async def _build_disc(adapter, radius: float, thickness: float, path: Path) -> None:
    """Build a disc/shaft part with a reference axis down the cylinder."""
    _check("create_part", await adapter.create_part())
    _check("create_sketch Front", await adapter.create_sketch("Front"))
    _check(f"add_circle R{radius}", await adapter.add_circle(0.0, 0.0, radius))
    _check("exit_sketch", await adapter.exit_sketch())
    # Midplane extrude: the body spans z in [-t/2, +t/2], so a pick point
    # at z=0 always lies on the cylinder face whatever the direction.
    _check(
        f"create_extrusion depth={thickness} (midplane)",
        await adapter.create_extrusion(
            ExtrusionParameters(depth=thickness, both_directions=True)
        ),
    )
    _check(
        "create_axis (cylindrical_face)",
        await adapter.create_axis(
            CreateAxisParameters(
                mode="cylindrical_face",
                face_point=[radius, 0.0, 0.0],
            )
        ),
    )
    _check(f"save_file -> {path.name}", await adapter.save_file(str(path)))


def _axis(component: str) -> MateEntityRef:
    return MateEntityRef(entity_type="AXIS", name=f"Axis1@{component}")


def _front_plane(component: str) -> MateEntityRef:
    return MateEntityRef(entity_type="PLANE", name=f"Front Plane@{component}")


async def build_demo_assembly(out_dir: Path) -> dict[str, str]:
    """Build the mate demo assembly end-to-end and return artefact paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    shaft_path = (out_dir / "mate_demo_shaft.SLDPRT").resolve()
    big_path = (out_dir / "mate_demo_gear_big.SLDPRT").resolve()
    small_path = (out_dir / "mate_demo_gear_small.SLDPRT").resolve()
    plate_path = (out_dir / "mate_demo_plate.SLDPRT").resolve()

    adapter = PyWin32Adapter({})
    print("Connecting to SolidWorks ...")
    await adapter.connect()
    print(f"Connected: swApp={type(adapter.swApp).__name__}")

    try:
        # Make the script re-runnable: a previous run leaves its documents
        # open, and saving a fresh part over an open path fails.
        adapter._attempt(lambda: adapter.swApp.CloseAllDocuments(True), default=None)
        print("  OK  CloseAllDocuments (start from a clean session)")

        # ------------------------------------------------------------------
        # Throwaway parts.
        # ------------------------------------------------------------------
        print("Part: shaft")
        await _build_disc(adapter, SHAFT_RADIUS, SHAFT_LENGTH, shaft_path)
        print("Part: big gear disc")
        await _build_disc(adapter, BIG_GEAR_RADIUS, GEAR_THICKNESS, big_path)
        print("Part: small gear disc")
        await _build_disc(adapter, SMALL_GEAR_RADIUS, GEAR_THICKNESS, small_path)
        print("Part: base plate")
        await _build_disc(adapter, PLATE_RADIUS, PLATE_THICKNESS, plate_path)

        # ------------------------------------------------------------------
        # Phase 7A: components.
        # ------------------------------------------------------------------
        print("Assembly: components")
        _check("create_assembly", await adapter.create_assembly())

        shaft1 = await adapter.insert_component(
            InsertComponentParameters(file_path=str(shaft_path))
        )
        _check("insert_component shaft #1 (auto-fixed)", shaft1)
        if not shaft1.data["fixed"]:
            raise RuntimeError("first inserted component was not auto-fixed")

        shaft2 = await adapter.insert_component(
            InsertComponentParameters(
                file_path=str(shaft_path), position=[CENTRE_DISTANCE, 0.0, 0.0]
            )
        )
        _check("insert_component shaft #2", shaft2)
        shaft2_name = shaft2.data["name"]
        _check(
            f"fix_component {shaft2_name}",
            await adapter.fix_component(ComponentRefParameters(name=shaft2_name)),
        )

        big = await adapter.insert_component(
            InsertComponentParameters(file_path=str(big_path), position=[0, 80, 0])
        )
        _check("insert_component big gear", big)
        big_name = big.data["name"]

        small = await adapter.insert_component(
            InsertComponentParameters(
                file_path=str(small_path), position=[CENTRE_DISTANCE, -80.0, 0.0]
            )
        )
        _check("insert_component small gear", small)
        small_name = small.data["name"]

        moved = await adapter.move_component(
            MoveComponentParameters(
                name=small_name, position=[CENTRE_DISTANCE, -60.0, 0.0]
            )
        )
        _check("move_component small gear", moved)
        if abs(moved.data["position"][1] + 60.0) > 1e-6:
            raise RuntimeError(f"move_component position mismatch: {moved.data}")

        # Sacrificial component: replace it with a different model, then
        # remove it — exercises ReplaceComponents2 and DeleteSelection2.
        spare = await adapter.insert_component(
            InsertComponentParameters(file_path=str(shaft_path), position=[120, 0, 0])
        )
        _check("insert_component sacrificial shaft", spare)
        spare_name = spare.data["name"]
        _check(
            f"replace_component {spare_name} -> small gear model",
            await adapter.replace_component(
                ReplaceComponentParameters(name=spare_name, file_path=str(small_path))
            ),
        )
        # Replacement renames the instance to the new model's stem.
        spare_replaced = f"mate_demo_gear_small-{spare_name.rsplit('-', 1)[-1]}"
        removed = await adapter.remove_component(
            ComponentRefParameters(name=spare_replaced)
        )
        if not removed.is_success:
            # Some builds keep the original instance number — try instance 2.
            removed = await adapter.remove_component(
                ComponentRefParameters(name="mate_demo_gear_small-2")
            )
        _check("remove_component sacrificial component", removed)

        # ------------------------------------------------------------------
        # Phase 7B: standard mates pin each gear onto its shaft.
        # Concentric needs cylindrical geometry (axis-axis is rejected), so
        # the cylinder faces are picked by point at the known insert poses;
        # the coincident plane mates use stale-proof entity names.
        # ------------------------------------------------------------------
        print("Assembly: standard mates")
        pinnings = (
            # (gear, shaft, gear cyl-face pick, shaft cyl-face pick) — all
            # picks at z=0, the midplane every body straddles.
            (
                big_name,
                "mate_demo_shaft-1",
                [BIG_GEAR_RADIUS, 80.0, 0.0],
                [SHAFT_RADIUS, 0.0, 0.0],
            ),
            (
                small_name,
                shaft2_name,
                [CENTRE_DISTANCE + SMALL_GEAR_RADIUS, -60.0, 0.0],
                [CENTRE_DISTANCE + SHAFT_RADIUS, 0.0, 0.0],
            ),
        )
        for gear, shaft, gear_point, shaft_point in pinnings:
            _check(
                f"add_mate concentric {gear} <-> {shaft} (cylinder faces)",
                await adapter.add_mate(
                    AddMateParameters(
                        mate_type="concentric",
                        entities=[
                            MateEntityRef(entity_type="FACE", point=gear_point),
                            MateEntityRef(entity_type="FACE", point=shaft_point),
                        ],
                    )
                ),
            )
            _check(
                f"add_mate coincident {gear} <-> {shaft} (front planes)",
                await adapter.add_mate(
                    AddMateParameters(
                        mate_type="coincident",
                        entities=[_front_plane(gear), _front_plane(shaft)],
                    )
                ),
            )

        # ------------------------------------------------------------------
        # Phase 7C: gear mate with an explicit 2:1 ratio.
        # ------------------------------------------------------------------
        print("Assembly: gear mate + motion check")
        gear_mate = await adapter.add_mate(
            AddMateParameters(
                mate_type="gear",
                entities=[_axis(big_name), _axis(small_name)],
                gear_ratio=GEAR_RATIO,
            )
        )
        _check("add_mate gear ratio 30:15", gear_mate)
        gear_mate_name = gear_mate.data["name"]
        print(f"  gear mate: {gear_mate_name}")

        # Rotate the input gear; kinematic propagation must counter-rotate
        # the output gear by the inverse ratio stored on the gear mate.
        small_before = _component_z_rotation_deg(adapter, small_name)
        rotated = await adapter.rotate_component(
            RotateComponentParameters(
                name=big_name, angle=INPUT_ANGLE, mode="kinematic"
            )
        )
        _check(
            f"rotate_component {big_name} by {INPUT_ANGLE} deg (kinematic)",
            rotated,
        )
        print(f"  propagated: {rotated.data['propagated']}")
        small_after = _component_z_rotation_deg(adapter, small_name)
        # Signed world-frame swing, normalized to (-180, 180].
        output_swing = (small_after - small_before + 180.0) % 360.0 - 180.0
        print(f"  input {INPUT_ANGLE:+.1f} deg -> output {output_swing:+.2f} deg")
        # External gears counter-rotate in world space: +45 in -> -90 out.
        if abs(output_swing - (-EXPECTED_OUTPUT_ANGLE)) > 1.0:
            raise RuntimeError(
                f"gear ratio not transmitted: expected output ~ "
                f"{-EXPECTED_OUTPUT_ANGLE} deg (counter-rotation), "
                f"got {output_swing:+.2f} deg"
            )
        print("  OK  inverse-ratio counter-rotation transmitted")

        # Suppress the gear mate: the input gear must now rotate alone.
        _check(
            f"suppress_mate {gear_mate_name}",
            await adapter.suppress_mate(
                SuppressMateParameters(name=gear_mate_name, suppress=True)
            ),
        )
        small_before = _component_z_rotation_deg(adapter, small_name)
        _check(
            "rotate_component input back (gear mate suppressed, kinematic)",
            await adapter.rotate_component(
                RotateComponentParameters(
                    name=big_name, angle=-INPUT_ANGLE, mode="kinematic"
                )
            ),
        )
        small_drift = abs(_component_z_rotation_deg(adapter, small_name) - small_before)
        if min(small_drift, 360.0 - small_drift) > 0.5:
            raise RuntimeError(
                f"suppressed gear mate still moved the output ({small_drift:.2f} deg)"
            )
        print("  OK  suppressed mate transmits no motion")
        _check(
            f"unsuppress_mate {gear_mate_name}",
            await adapter.suppress_mate(
                SuppressMateParameters(name=gear_mate_name, suppress=False)
            ),
        )

        listed = await adapter.list_mates()
        _check("list_mates", listed)
        names = [mate["name"] for mate in listed.data]
        print(f"  mates: {names}")
        if len(names) != 5 or gear_mate_name not in names:
            raise RuntimeError(f"expected 5 mates incl. {gear_mate_name!r}: {names}")

        # ------------------------------------------------------------------
        # 20-instance circular component pattern about an assembly axis.
        # ------------------------------------------------------------------
        print("Assembly: 20x circular component pattern")
        _check(
            "create_axis (assembly Top ^ Right)",
            await adapter.create_axis(
                CreateAxisParameters(
                    mode="two_planes", planes=["Top Plane", "Right Plane"]
                )
            ),
        )
        # Everything mounts on a base plate so the fixture reads as a
        # physical jig: the shafts butt against the plate's front face and
        # the patterned ring discs are seated on it.
        plate = await adapter.insert_component(
            InsertComponentParameters(
                file_path=str(plate_path), position=[0.0, 0.0, PLATE_Z]
            )
        )
        _check("insert_component base plate", plate)
        _check(
            "fix_component base plate",
            await adapter.fix_component(
                ComponentRefParameters(name=plate.data["name"])
            ),
        )
        # A dedicated unmated seed sits far enough from the pattern axis
        # that the 20 instances clear each other and the gear pair
        # (pattern instances carry no mates, so the mated small gear stays
        # where it is).
        ring_seed = await adapter.insert_component(
            InsertComponentParameters(
                file_path=str(small_path),
                position=[PATTERN_RING_RADIUS, 0.0, RING_SEED_Z],
            )
        )
        _check("insert_component pattern ring seed", ring_seed)
        # The seed is a jig post, not a mated mechanism part — fix it so
        # it (and the pattern it seeds) leaves no free degrees of freedom.
        _check(
            "fix_component pattern ring seed",
            await adapter.fix_component(
                ComponentRefParameters(name=ring_seed.data["name"])
            ),
        )
        pattern = await adapter.pattern_components_circular(
            ComponentCircularPatternParameters(
                components=[ring_seed.data["name"]], count=20, axis_name="Axis1"
            )
        )
        _check("pattern_components_circular count=20", pattern)
        print(f"  pattern feature: {pattern.data.name}")

        # ------------------------------------------------------------------
        # delete_mate + persist artefacts.
        # ------------------------------------------------------------------
        _check(
            f"delete_mate {gear_mate_name}",
            await adapter.delete_mate(MateRefParameters(name=gear_mate_name)),
        )
        listed = await adapter.list_mates()
        if len(listed.data) != 4:
            raise RuntimeError(f"expected 4 mates after delete: {listed.data}")
        print("  OK  delete_mate removed the gear mate")

        # ------------------------------------------------------------------
        # Fully define the saved state. The gear mate was exercised and
        # deleted above, which leaves both gears with a free spin DOF —
        # ground each with a 0-degree angle mate to its shaft instead of
        # re-adding the gear mate, so nothing is redundant.
        # ------------------------------------------------------------------
        print("Assembly: fully define final state")
        for gear, shaft in (
            (big_name, "mate_demo_shaft-1"),
            (small_name, shaft2_name),
        ):
            _check(
                f"add_mate angle 0 deg {gear} <-> {shaft} (right planes)",
                await adapter.add_mate(
                    AddMateParameters(
                        mate_type="angle",
                        entities=[
                            MateEntityRef(
                                entity_type="PLANE", name=f"Right Plane@{gear}"
                            ),
                            MateEntityRef(
                                entity_type="PLANE", name=f"Right Plane@{shaft}"
                            ),
                        ],
                        angle=0.0,
                    )
                ),
            )
        _assert_components_fully_defined(adapter)
        print("  OK  every component is fixed or fully defined")

        asm_path = (out_dir / "mate_demo_assembly.SLDASM").resolve()
        _check(f"save_file -> {asm_path.name}", await adapter.save_file(str(asm_path)))
        img_path = (out_dir / "mate_demo_assembly_isometric.png").resolve()
        _check(
            "export_image (isometric)",
            await adapter.export_image(
                {
                    "file_path": str(img_path),
                    "format_type": "png",
                    "width": 1600,
                    "height": 1000,
                    "view_orientation": "isometric",
                }
            ),
        )
        return {"assembly": str(asm_path), "screenshot": str(img_path)}
    finally:
        try:
            await adapter.disconnect()
            print("Disconnected.")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN disconnect failed: {exc}")


def main() -> int:
    out_dir = REPO_ROOT / "out"
    try:
        artefacts = asyncio.run(build_demo_assembly(out_dir))
    except Exception:
        traceback.print_exc()
        return 1
    print("\nDemo artefacts:")
    for key, value in artefacts.items():
        print(f"  {key}: {value or '(skipped)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
