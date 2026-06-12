r"""Live end-to-end demo for sketch-point anchoring (point refs + point dims).

Exercises the semantic-anchoring surface that replaces ``fix`` relations,
through the public adapter API only:

* ``add_sketch_constraint`` point refs (``"Circle_1.center"``,
  ``"Line_2.start"``/``.end``) and the reserved ``"origin"``, with the
  point relations ``coincident``, ``merge``, and ``vertical_points``.
* ``add_sketch_dimension`` point-distance types ``horizontal_distance``,
  ``vertical_distance``, and ``distance`` (driving dims between two points).
* ``get_over_defining_relations`` on a deliberately over-defined sketch.

Each stage asserts ``check_sketch_fully_defined`` so a silent COM no-op
cannot pass. Exits 0 when every check passes. Run with the project
virtualenv on a Windows box that already has SolidWorks open::

    .\.venv\Scripts\python.exe scripts\demo_point_anchoring.py
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter  # noqa: E402


def _ok(label: str, result) -> None:
    assert result.is_success, f"{label}: {result.error}"
    print(f"PASS {label}")


async def _assert_state(adapter: PyWin32Adapter, expected: str, label: str) -> None:
    state = await adapter.check_sketch_fully_defined()
    assert state.is_success, f"{label}: {state.error}"
    actual = (state.data or {}).get("definition_state")
    assert actual == expected, f"{label}: expected {expected}, got {actual}"
    print(f"PASS {label}: {actual}")


async def main() -> int:
    adapter = PyWin32Adapter({})
    await adapter.connect()
    adapter._attempt(lambda: adapter.swApp.CloseAllDocuments(True), default=None)
    try:
        _ok("create part", await adapter.create_part())
        _ok("create sketch (Front)", await adapter.create_sketch("Front"))

        # 1. Circle at the origin: coincident centre->origin + driving diameter.
        circle = await adapter.add_circle(0.0, 0.0, 8.0)
        _ok("add origin circle", circle)
        _ok(
            "coincident centre->origin",
            await adapter.add_sketch_constraint(
                f"{circle.data}.center", "origin", "coincident"
            ),
        )
        _ok(
            "driving diameter 16",
            await adapter.add_sketch_dimension(circle.data, None, "diameter", 16.0),
        )
        await _assert_state(adapter, "fully_defined", "origin circle anchored")

        # 2. Off-origin circle in the negative quadrant: H+V distance dims
        #    from the origin (the general define_circle scheme).
        circle2 = await adapter.add_circle(-20.0, -15.0, 5.0)
        _ok("add (-20,-15) circle", circle2)
        _ok(
            "horizontal_distance 20 centre->origin",
            await adapter.add_sketch_dimension(
                f"{circle2.data}.center", "origin", "horizontal_distance", 20.0
            ),
        )
        _ok(
            "vertical_distance 15 centre->origin",
            await adapter.add_sketch_dimension(
                f"{circle2.data}.center", "origin", "vertical_distance", 15.0
            ),
        )
        _ok(
            "driving diameter 10",
            await adapter.add_sketch_dimension(circle2.data, None, "diameter", 10.0),
        )
        await _assert_state(
            adapter, "fully_defined", "negative-quadrant circle anchored"
        )

        # 3. Line chain anchored without fix: merged joint, segment
        #    relations, point dims to the origin, and an aligned "distance"
        #    plus angular dim defining the inclined segment. The second line
        #    starts OFF the first line's endpoint — coincident creation
        #    coordinates make inference merge the points at creation time and
        #    SolidWorks then rejects the redundant merge relation.
        line1 = await adapter.add_line(0.0, -40.0, 20.0, -40.0)
        line2 = await adapter.add_line(20.0, -35.0, 35.0, -25.0)
        _ok("add chain lines", line2)
        _ok(
            "merge chain joint",
            await adapter.add_sketch_constraint(
                f"{line1.data}.end", f"{line2.data}.start", "merge"
            ),
        )
        _ok(
            "horizontal first segment",
            await adapter.add_sketch_constraint(line1.data, None, "horizontal"),
        )
        _ok(
            "vertical_distance 40 chain start->origin",
            await adapter.add_sketch_dimension(
                f"{line1.data}.start", "origin", "vertical_distance", 40.0
            ),
        )
        _ok(
            "vertical_points chain start->origin",
            await adapter.add_sketch_constraint(
                f"{line1.data}.start", "origin", "vertical_points"
            ),
        )
        _ok(
            "horizontal_distance 20 along first segment",
            await adapter.add_sketch_dimension(
                f"{line1.data}.start", f"{line1.data}.end", "horizontal_distance", 20.0
            ),
        )
        _ok(
            "aligned distance on second segment",
            await adapter.add_sketch_dimension(
                f"{line2.data}.start",
                f"{line2.data}.end",
                "distance",
                21.213,  # 15*sqrt(2)
            ),
        )
        _ok(
            "vertical_distance 25 chain end->origin",
            await adapter.add_sketch_dimension(
                f"{line2.data}.end", "origin", "vertical_distance", 25.0
            ),
        )
        await _assert_state(adapter, "fully_defined", "line chain anchored")

        # 4. Diagnostic: a conflicting relation over-defines the sketch and
        #    get_over_defining_relations names it.
        clean = await adapter.get_over_defining_relations()
        _ok("diagnostic on healthy sketch", clean)
        assert clean.data == {"count": 0, "relations": []}, clean.data

        conflict = await adapter.add_sketch_constraint(
            f"{circle2.data}.center", "origin", "vertical_points"
        )
        # SolidWorks may accept the relation (sketch turns over-defined) or
        # reject it outright; both are valid solver behaviours.
        if conflict.is_success:
            over = await adapter.get_over_defining_relations()
            _ok("diagnostic on over-defined sketch", over)
            count = (over.data or {}).get("count", 0)
            assert count >= 1, f"expected over-defining relations, got {over.data}"
            names = [r.get("relation_name") for r in over.data["relations"]]
            print(f"PASS over-defining relations listed: {count} ({names})")
        else:
            print(f"PASS conflicting relation rejected up front: {conflict.error}")

        _ok("exit sketch", await adapter.exit_sketch())
        adapter._attempt(lambda: adapter.swApp.CloseAllDocuments(True), default=None)
        print("ALL LIVE CHECKS PASS")
        return 0
    except AssertionError:
        traceback.print_exc()
        return 1
    finally:
        await adapter.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
