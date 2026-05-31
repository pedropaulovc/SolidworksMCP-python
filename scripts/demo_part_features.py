r"""Live end-to-end demo for the Phase 2 part-level feature primitives.

Exercises every capability delivered under fork issue #3 / upstream phase 2
(PR #26):

    add_fillet, add_chamfer, shell, mirror_feature,
    circular_pattern_feature, linear_pattern_feature, draft

Rather than stack all seven features on one body — where each feature changes
the geometry and invalidates the coordinate-based selections the next one
relies on — the demo builds one small part per capability using the exact
recipes proven in ``tests/test_live_sw_regression.py``. Each part is saved and
captured as an isometric PNG so the result of every operation is visible.

Parts (all dimensions in mm; boxes are 50x50x100 centred on the Front plane,
z in [0, 100]):

* **fillet_chamfer** — a box with one vertical edge chamfered (4 mm) and the
  opposite vertical edge filleted (R4). Edges located by a point on each.
* **shell** — the same box hollowed to a 3 mm wall, opened on the far (z=100)
  face.
* **mirror** — an off-centre through-cut mirrored across the Right Plane,
  giving a symmetric pair of holes.
* **circular_pattern** — a cylinder (R25) with a through-hole patterned 6x
  about the cylindrical-face axis.
* **linear_pattern** — a box with a through-hole patterned 4x at 10 mm spacing
  along a bottom edge.
* **draft** — a box with its +X face tapered 10 deg about the Top plane.

On success the script saves six ``.SLDPRT`` files and six PNG screenshots to
``out/`` and exits 0. Run with the project virtualenv on a Windows box that
already has SolidWorks open::

    .\.venv\Scripts\python.exe scripts\demo_part_features.py
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from solidworks_mcp.adapters.base import (  # noqa: E402
    CircularPatternParameters,
    DraftParameters,
    ExtrusionParameters,
    LinearPatternParameters,
    MirrorFeatureParameters,
    ShellParameters,
)
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter  # noqa: E402


def _check(label: str, result) -> None:
    """Raise with the COM error attached when an adapter result is not success."""
    if not result.is_success:
        raise RuntimeError(f"{label} failed: {result.error}")
    print(f"  OK  {label}")


async def _build_box(adapter, half: float = 25.0, depth: float = 100.0) -> None:
    """Build a centred box: x,y in [-half, half] mm, z in [0, depth] mm."""
    _check("create_part", await adapter.create_part())
    _check("create_sketch Front", await adapter.create_sketch("Front"))
    _check("add_rectangle", await adapter.add_rectangle(-half, -half, half, half))
    _check("exit_sketch", await adapter.exit_sketch())
    _check(
        "create_extrusion",
        await adapter.create_extrusion(ExtrusionParameters(depth=depth)),
    )


async def _build_cylinder(adapter, radius: float = 25.0, depth: float = 100.0) -> None:
    """Build a cylinder along +Z: radius mm, z in [0, depth] mm."""
    _check("create_part", await adapter.create_part())
    _check("create_sketch Front", await adapter.create_sketch("Front"))
    _check("add_circle", await adapter.add_circle(0.0, 0.0, radius))
    _check("exit_sketch", await adapter.exit_sketch())
    _check(
        "create_extrusion",
        await adapter.create_extrusion(ExtrusionParameters(depth=depth)),
    )


async def _through_cut(
    adapter, x: float, y: float, r: float, depth: float = 100.0
) -> str:
    """Add a circular through-cut and return the created feature's name."""
    _check("create_sketch Front (cut)", await adapter.create_sketch("Front"))
    _check("add_circle (cut profile)", await adapter.add_circle(x, y, r))
    _check("exit_sketch (cut)", await adapter.exit_sketch())
    cut = await adapter.create_cut_extrude(ExtrusionParameters(depth=depth))
    _check("create_cut_extrude", cut)
    return cut.data.name


async def _save_and_shot(adapter, out_dir: Path, stem: str) -> dict[str, str]:
    """Save the active part and capture an isometric PNG; return artefact paths."""
    part_path = (out_dir / f"{stem}.SLDPRT").resolve()
    _check(f"save_file -> {part_path}", await adapter.save_file(str(part_path)))
    img_path = (out_dir / f"{stem}.png").resolve()
    _check(
        f"export_image -> {img_path}",
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
    return {f"{stem}_part": str(part_path), f"{stem}_png": str(img_path)}


async def build_demo_parts(out_dir: Path) -> dict[str, str]:
    """Build one part per Phase 2 capability and return all artefact paths."""
    out_dir.mkdir(parents=True, exist_ok=True)

    adapter = PyWin32Adapter({})
    print("Connecting to SolidWorks ...")
    await adapter.connect()
    print(f"Connected: swApp={type(adapter.swApp).__name__}")

    artefacts: dict[str, str] = {}
    try:
        # --- fillet + chamfer (two vertical edges of one box) ----------------
        print("\n[1/6] fillet + chamfer")
        await _build_box(adapter)
        _check(
            "add_chamfer (edge @ +x,+y)",
            await adapter.add_chamfer(4.0, [[25.0, 25.0, 50.0]]),
        )
        _check(
            "add_fillet  (edge @ -x,+y)",
            await adapter.add_fillet(4.0, [[-25.0, 25.0, 50.0]]),
        )
        artefacts |= await _save_and_shot(
            adapter, out_dir, "part_features_fillet_chamfer"
        )
        _check("close_model", await adapter.close_model(save=False))

        # --- shell (hollow, open far face) -----------------------------------
        print("\n[2/6] shell")
        await _build_box(adapter)
        _check(
            "shell (3 mm wall, open z=100 face)",
            await adapter.shell(
                ShellParameters(thickness=3.0, face_points=[[0.0, 0.0, 100.0]])
            ),
        )
        artefacts |= await _save_and_shot(adapter, out_dir, "part_features_shell")
        _check("close_model", await adapter.close_model(save=False))

        # --- mirror feature (off-centre cut across Right Plane) --------------
        print("\n[3/6] mirror_feature")
        await _build_box(adapter)
        cut = await _through_cut(adapter, 15.0, 10.0, 4.0)
        _check(
            "mirror_feature (across Right Plane)",
            await adapter.mirror_feature(
                MirrorFeatureParameters(plane="Right Plane", features=[cut])
            ),
        )
        artefacts |= await _save_and_shot(adapter, out_dir, "part_features_mirror")
        _check("close_model", await adapter.close_model(save=False))

        # --- circular pattern (hole patterned about cylinder axis) -----------
        print("\n[4/6] circular_pattern_feature")
        await _build_cylinder(adapter, radius=25.0, depth=100.0)
        cut = await _through_cut(adapter, 15.0, 0.0, 3.0)
        _check(
            "circular_pattern_feature (6x about axis)",
            await adapter.circular_pattern_feature(
                CircularPatternParameters(
                    axis_point=[25.0, 0.0, 50.0], features=[cut], count=6
                )
            ),
        )
        artefacts |= await _save_and_shot(
            adapter, out_dir, "part_features_circular_pattern"
        )
        _check("close_model", await adapter.close_model(save=False))

        # --- linear pattern (hole patterned along a bottom edge) -------------
        print("\n[5/6] linear_pattern_feature")
        await _build_box(adapter)
        cut = await _through_cut(adapter, -15.0, 0.0, 3.0)
        _check(
            "linear_pattern_feature (4x @ 10 mm)",
            await adapter.linear_pattern_feature(
                LinearPatternParameters(
                    direction_point=[0.0, -25.0, 0.0],
                    features=[cut],
                    count=4,
                    spacing=10.0,
                )
            ),
        )
        artefacts |= await _save_and_shot(
            adapter, out_dir, "part_features_linear_pattern"
        )
        _check("close_model", await adapter.close_model(save=False))

        # --- draft (+X face tapered about Top plane) -------------------------
        print("\n[6/6] draft")
        await _build_box(adapter)
        _check(
            "draft (+X face, 10 deg about Top Plane)",
            await adapter.draft(
                DraftParameters(
                    angle=10.0,
                    neutral_plane="Top Plane",
                    face_points=[[25.0, 0.0, 50.0]],
                )
            ),
        )
        artefacts |= await _save_and_shot(adapter, out_dir, "part_features_draft")
        _check("close_model", await adapter.close_model(save=False))

        return artefacts
    finally:
        try:
            await adapter.disconnect()
            print("Disconnected.")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN disconnect failed: {exc}")


def main() -> int:
    out_dir = REPO_ROOT / "out"
    try:
        artefacts = asyncio.run(build_demo_parts(out_dir))
    except Exception:
        traceback.print_exc()
        return 1
    print("\nDemo artefacts:")
    for key, value in artefacts.items():
        print(f"  {key}: {value or '(skipped)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
