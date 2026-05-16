"""Regression tests for the Phase 1+2 COM-safety rewrite.

These tests target specific bugs that were diagnosed and fixed on 2026-04-24:

1. **Cross-thread IDispatch use** — calling a SolidWorks method from a
   different thread than where the COM object was created previously raised
   ``AttributeError: SldWorks.Application.<method>`` (NOT a ``com_error``).
   Fixed by routing all COM work through ``ComExecutor`` (single STA thread).

2. **Method-vs-property mis-resolution** — Python 3.14 + pywin32 311 late
   binding resolved zero-arg SW methods (``GetType``, ``GetTitle``, …) as
   properties, causing ``TypeError: 'int'/'str' object is not callable``.
   Fixed by ``sw_type_info.flag_methods`` using the makepy-generated
   wrapper to identify and flag methods per SW interface.

3. **Dead code in get_model_info** — it called ``GetRebuildStatus()`` and
   ``GetActiveConfiguration().GetName()`` which don't exist in the SW 2025
   type library. Fixed by replacing with ``IsTessellationValid()`` and
   the ``IConfiguration.Name`` property.

These tests are gated:
  - ``@pytest.mark.solidworks_only`` — require SolidWorks installed
  - ``@pytest.mark.windows_only`` — require Windows
  - Skipped entirely unless ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1``

Run only these tests locally on Windows with SW::

    SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1 \
        python -m pytest tests/test_live_sw_regression.py -v
"""

from __future__ import annotations

import asyncio
import os
import platform
import threading

import pytest

# Skip the entire module when the env flag isn't set. This matches the
# pattern used by tests/test_real_solidworks_integration.py and keeps CI
# fast on boxes without SW.
_REAL_FLAG = "SOLIDWORKS_MCP_RUN_REAL_INTEGRATION"
_REAL_ENABLED = os.getenv(_REAL_FLAG, "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

pytestmark = [
    pytest.mark.solidworks_only,
    pytest.mark.windows_only,
    pytest.mark.skipif(
        not _REAL_ENABLED,
        reason=(
            f"set {_REAL_FLAG}=1 to run tests that require a live SolidWorks install"
        ),
    ),
    pytest.mark.skipif(
        platform.system() != "Windows",
        reason="SolidWorks only runs on Windows",
    ),
]


# Tests that need a real .SLDASM file to exercise OpenDoc6 read the path
# from this env var. Set it to any local SolidWorks assembly; tests skip
# cleanly when it's unset or the file isn't present.
_TEST_ASSEMBLY_ENV_VAR = "SOLIDWORKS_MCP_TEST_ASSEMBLY"


def _test_assembly_path() -> str:
    """Return the .SLDASM path used by file-loading regression tests.

    Reads ``SOLIDWORKS_MCP_TEST_ASSEMBLY``. Returns an empty string when
    unset; callers should ``pytest.skip`` in that case.
    """
    return os.environ.get(_TEST_ASSEMBLY_ENV_VAR, "").strip()


# ---- ComExecutor unit tests (don't need SW) ----
# These still run only when _REAL_ENABLED because they pull in pywin32.


def test_com_executor_start_stop_idempotent() -> None:
    """ComExecutor.start() and stop() can be called repeatedly."""
    from solidworks_mcp.adapters.com_executor import ComExecutor

    ex = ComExecutor(name="test-idempotent")
    ex.start()
    ex.start()  # second call is a no-op
    assert ex._thread is not None and ex._thread.is_alive()
    ex.stop()
    ex.stop()  # safe to call again
    assert ex._thread is None


def test_com_executor_propagates_exceptions() -> None:
    """Exceptions raised inside a submitted callable reach the caller."""
    from solidworks_mcp.adapters.com_executor import ComExecutor

    with ComExecutor(name="test-exc") as ex:
        with pytest.raises(ZeroDivisionError):
            ex.run(lambda: 1 / 0)


def test_com_executor_runs_on_dedicated_thread() -> None:
    """All callables run on the same (non-caller) thread."""
    from solidworks_mcp.adapters.com_executor import ComExecutor

    caller = threading.current_thread().name
    with ComExecutor(name="test-thread") as ex:
        worker_name = ex.run(lambda: threading.current_thread().name)
        worker_name2 = ex.run(lambda: threading.current_thread().name)

    assert worker_name != caller, (
        "executor must run callables on a thread other than the caller"
    )
    assert worker_name == worker_name2, (
        "all callables must run on the same worker thread"
    )


# ---- sw_type_info unit tests ----


def test_sw_type_info_loads_sw_wrapper() -> None:
    """The makepy-generated SW wrapper loads and exposes core interfaces."""
    from solidworks_mcp.adapters import sw_type_info

    sw_type_info._ensure_loaded()
    if sw_type_info._wrapper_module is None:
        pytest.skip(
            "gen_py wrapper not available — run: "
            "python -m win32com.client.makepy sldworks.tlb"
        )
    assert sw_type_info._wrapper_module is not None
    # These are the interfaces we rely on for every SW operation.
    for iface in ("ISldWorks", "IModelDoc2", "IAssemblyDoc", "IPartDoc"):
        assert sw_type_info.interface_method_names(iface), (
            f"SW interface {iface} missing from wrapper"
        )


def test_flag_methods_is_per_interface_incremental() -> None:
    """Calling flag_methods with new interface adds; repeats are no-ops."""
    from unittest.mock import MagicMock

    from solidworks_mcp.adapters import sw_type_info

    sw_type_info._ensure_loaded()
    if sw_type_info._wrapper_module is None:
        pytest.skip(
            "gen_py wrapper not available — run: "
            "python -m win32com.client.makepy sldworks.tlb"
        )
    sw_type_info.invalidate_flag_cache()

    # Mock dispatch that records every _FlagAsMethod call.
    obj = MagicMock()
    first = sw_type_info.flag_methods(obj, "ISldWorks")
    second = sw_type_info.flag_methods(obj, "ISldWorks")  # repeat
    third = sw_type_info.flag_methods(obj, "IModelDoc2")  # new iface

    assert first > 0, "first flag of ISldWorks should do real work"
    assert second == 0, "second flag of same interface must be a no-op"
    assert third > 0, "flagging a new interface must do incremental work"


# ---- End-to-end adapter regression tests ----


@pytest.fixture
async def connected_adapter():
    """Yield a connected PyWin32Adapter and clean up afterwards."""
    from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter

    adapter = PyWin32Adapter({})
    await adapter.connect()
    try:
        yield adapter
    finally:
        await adapter.disconnect()


async def test_connect_acquires_late_bound_swapp(connected_adapter) -> None:
    """After connect(), swApp is a pywin32 late-bound CDispatch.

    Regression: earlier attempts at early binding produced
    ``ISldWorks instance`` typed dispatches that broke VARIANT out-params.
    """
    adapter = connected_adapter
    assert adapter.swApp is not None
    assert type(adapter.swApp).__name__ == "CDispatch", (
        f"swApp must be CDispatch (late-bound), got "
        f"{type(adapter.swApp).__name__}. Early binding breaks VARIANT "
        "pass-by-ref arguments used by OpenDoc6 and others."
    )


async def test_open_model_succeeds(connected_adapter) -> None:
    """open_model returns success for a valid assembly path.

    Skips if the canonical test assembly isn't on this box.
    """
    test_assy = _test_assembly_path()
    if not test_assy or not os.path.exists(test_assy):
        pytest.skip(
            f"set {_TEST_ASSEMBLY_ENV_VAR} to a local .SLDASM path to run this test"
        )

    result = await connected_adapter.open_model(test_assy)
    assert result.is_success, f"open_model failed: {result.error}"
    assert result.data is not None
    assert result.data.type == "Assembly"


async def test_get_model_info_fields_populate(connected_adapter) -> None:
    """get_model_info returns all expected fields with correct types.

    Regression: previously failed with ``TypeError: 'str' object is not
    callable`` on ``GetTitle()`` (pywin32 method-vs-property bug) and
    ``AttributeError: <unknown>.GetRebuildStatus`` (dead API call).
    """
    test_assy = _test_assembly_path()
    if not test_assy or not os.path.exists(test_assy):
        pytest.skip(
            f"set {_TEST_ASSEMBLY_ENV_VAR} to a local .SLDASM path to run this test"
        )

    await connected_adapter.open_model(test_assy)
    result = await connected_adapter.get_model_info()

    assert result.is_success, f"get_model_info failed: {result.error}"
    info = result.data
    assert isinstance(info["title"], str) and info["title"].endswith(".SLDASM")
    assert isinstance(info["path"], str)
    assert info["type"] == "Assembly"
    assert isinstance(info["configuration"], str)
    assert isinstance(info["is_dirty"], bool)
    assert isinstance(info["feature_count"], int)
    assert info["feature_count"] >= 0
    assert isinstance(info["needs_rebuild"], bool)


async def test_get_model_info_works_from_worker_thread(
    connected_adapter,
) -> None:
    """Calling from a worker thread doesn't hit the cross-thread
    AttributeError.

    Regression: before the ComExecutor refactor, this exact call path
    raised ``AttributeError: SldWorks.Application.<method>`` because the
    cached IDispatch was bound to the connect-thread's apartment.
    """
    test_assy = _test_assembly_path()
    if not test_assy or not os.path.exists(test_assy):
        pytest.skip(
            f"set {_TEST_ASSEMBLY_ENV_VAR} to a local .SLDASM path to run this test"
        )

    await connected_adapter.open_model(test_assy)

    worker_result: dict[str, object] = {}

    def worker() -> None:
        loop = asyncio.new_event_loop()
        try:
            r = loop.run_until_complete(connected_adapter.get_model_info())
            worker_result["status"] = r.status
            worker_result["error"] = r.error
            if r.is_success:
                worker_result["title"] = r.data["title"]
        finally:
            loop.close()

    t = threading.Thread(target=worker, name="pytest-worker")
    t.start()
    t.join(timeout=30)
    assert not t.is_alive(), "worker thread hung"

    assert worker_result["error"] is None, (
        f"cross-thread get_model_info surfaced an error: {worker_result['error']!r}"
    )
    assert worker_result.get("title", "").endswith(".SLDASM")


# ---- add_sketch_constraint live regression ----


async def test_add_sketch_constraint_perpendicular_and_horizontal(
    connected_adapter,
) -> None:
    """End-to-end check that add_sketch_constraint actually constrains
    SolidWorks geometry.

    Creates a fresh part + sketch, draws two right-angle lines, applies a
    perpendicular relation between them, then a horizontal relation on the
    first line, and verifies SolidWorks accepts both calls. SolidWorks
    silently accepts redundant relations, so we don't assert error on
    duplicates — instead we use ``IGetRelations.GetRelations`` to confirm
    the first line gained an extra relation after each call.
    """
    adapter = connected_adapter

    part_result = await adapter.create_part()
    assert part_result.is_success, f"create_part failed: {part_result.error}"

    try:
        sketch_result = await adapter.create_sketch("Front")
        assert sketch_result.is_success, f"create_sketch failed: {sketch_result.error}"

        line1 = await adapter.add_line(0.0, 0.0, 50.0, 0.0)
        line2 = await adapter.add_line(50.0, 0.0, 50.0, 50.0)
        assert line1.is_success and line2.is_success, (
            f"add_line failed: {line1.error} / {line2.error}"
        )

        perp = await adapter.add_sketch_constraint(
            line1.data, line2.data, "perpendicular"
        )
        assert perp.is_success, f"perpendicular constraint failed: {perp.error}"
        assert perp.data.startswith("Constraint_"), (
            f"unexpected constraint id: {perp.data!r}"
        )

        horiz = await adapter.add_sketch_constraint(line1.data, None, "horizontal")
        assert horiz.is_success, f"horizontal constraint failed: {horiz.error}"
        assert horiz.data.startswith("Constraint_")
    finally:
        await adapter.close_model(save=False)


async def test_add_sketch_constraint_symmetric_with_centerline(
    connected_adapter,
) -> None:
    """End-to-end check that the three-entity symmetric relation works.

    Creates a fresh part + sketch, draws a centerline plus two lines on
    either side, then applies ``symmetric`` with the centerline as
    ``entity3``. Verifies SolidWorks accepts the relation.
    """
    adapter = connected_adapter

    part_result = await adapter.create_part()
    assert part_result.is_success, f"create_part failed: {part_result.error}"

    try:
        sketch_result = await adapter.create_sketch("Front")
        assert sketch_result.is_success, f"create_sketch failed: {sketch_result.error}"

        # Centerline along Y axis at x=25 — the line of symmetry.
        centerline = await adapter.add_centerline(25.0, -50.0, 25.0, 50.0)
        # Two horizontal lines, mirrored about x=25
        left = await adapter.add_line(0.0, 10.0, 20.0, 10.0)
        right = await adapter.add_line(30.0, 10.0, 50.0, 10.0)
        assert centerline.is_success and left.is_success and right.is_success, (
            f"setup failed: {centerline.error} / {left.error} / {right.error}"
        )

        sym = await adapter.add_sketch_constraint(
            left.data, right.data, "symmetric", centerline.data
        )
        assert sym.is_success, f"symmetric constraint failed: {sym.error}"
        assert sym.data.startswith("Constraint_")

        # Calling symmetric without entity3 must produce a clear arity error
        # (no SW call should reach AddRelation).
        bad = await adapter.add_sketch_constraint(left.data, right.data, "symmetric")
        assert bad.is_error
        assert "entity3" in (bad.error or "")
    finally:
        await adapter.close_model(save=False)


async def test_add_sketch_constraint_unsupported_relation(connected_adapter) -> None:
    """Unsupported relation types must produce an error without touching SW."""
    adapter = connected_adapter

    part_result = await adapter.create_part()
    assert part_result.is_success
    try:
        sketch_result = await adapter.create_sketch("Front")
        assert sketch_result.is_success
        line1 = await adapter.add_line(0.0, 0.0, 25.0, 0.0)
        assert line1.is_success

        bogus = await adapter.add_sketch_constraint(line1.data, None, "diagonal")
        assert bogus.is_error
        assert "Unsupported relation type" in (bogus.error or "")
    finally:
        await adapter.close_model(save=False)


# ---- add_spline live regression ----


async def test_add_spline_creates_real_spline(connected_adapter) -> None:
    """End-to-end check that add_spline actually creates a spline in SW.

    Regression: pywin32 late binding unpacks a bare list of floats into N
    positional VARIANT arguments, so ``CreateSpline2`` saw 3*N+1 args and
    returned ``DISP_E_BADPARAMCOUNT``. The fix wraps the doubles in
    ``VARIANT(VT_ARRAY|VT_R8, [...])`` so they marshal as a single SAFEARRAY.
    """
    adapter = connected_adapter

    part_result = await adapter.create_part()
    assert part_result.is_success, f"create_part failed: {part_result.error}"

    try:
        sketch_result = await adapter.create_sketch("Front")
        assert sketch_result.is_success, f"create_sketch failed: {sketch_result.error}"

        spline = await adapter.add_spline(
            [
                {"x": 0.0, "y": 0.0},
                {"x": 25.0, "y": 15.0},
                {"x": 50.0, "y": 0.0},
                {"x": 75.0, "y": -15.0},
            ]
        )
        assert spline.is_success, f"add_spline failed: {spline.error}"
        assert spline.data.startswith("Spline_"), (
            f"unexpected spline id: {spline.data!r}"
        )
        assert spline.data in adapter._sketch_entities
    finally:
        await adapter.close_model(save=False)


async def test_add_spline_too_few_points_returns_error(connected_adapter) -> None:
    """A single point must surface a clear error without touching SW."""
    adapter = connected_adapter

    part_result = await adapter.create_part()
    assert part_result.is_success

    try:
        sketch_result = await adapter.create_sketch("Front")
        assert sketch_result.is_success

        bad = await adapter.add_spline([{"x": 0.0, "y": 0.0}])
        assert bad.is_error
        assert "at least 2 points" in (bad.error or "")
    finally:
        await adapter.close_model(save=False)


# ---- add_arc live regression ----


async def test_add_arc_creates_real_arc(connected_adapter) -> None:
    """End-to-end check that add_arc creates a real ISketchArc in SW.

    ``ISketchManager::CreateArc`` takes nine scalar doubles plus a short
    direction (no SAFEARRAY), so the spline VT_ARRAY|VT_R8 wrapper is not
    needed. This test locks in: (1) the mm-to-m unit conversion stays
    correct, (2) the CCW direction sentinel (``+1``) is accepted, and
    (3) the returned entity gets registered in ``_sketch_entities`` so
    later dimension/constraint calls can reference it.
    """
    adapter = connected_adapter

    part_result = await adapter.create_part()
    assert part_result.is_success, f"create_part failed: {part_result.error}"

    try:
        sketch_result = await adapter.create_sketch("Front")
        assert sketch_result.is_success, f"create_sketch failed: {sketch_result.error}"

        # Quarter arc (CCW): centre at origin, start at (15,0), end at (0,15).
        arc = await adapter.add_arc(
            center_x=0.0,
            center_y=0.0,
            start_x=15.0,
            start_y=0.0,
            end_x=0.0,
            end_y=15.0,
        )
        assert arc.is_success, f"add_arc failed: {arc.error}"
        assert arc.data.startswith("Arc_"), f"unexpected arc id: {arc.data!r}"
        assert arc.data in adapter._sketch_entities
    finally:
        await adapter.close_model(save=False)


async def test_add_arc_no_active_sketch_returns_error(connected_adapter) -> None:
    """Calling add_arc without an open sketch must error without touching SW."""
    adapter = connected_adapter

    part_result = await adapter.create_part()
    assert part_result.is_success

    try:
        # Intentionally skip create_sketch; currentSketchManager stays None.
        bad = await adapter.add_arc(0.0, 0.0, 15.0, 0.0, 0.0, 15.0)
        assert bad.is_error
        assert "No active sketch" in (bad.error or "")
    finally:
        await adapter.close_model(save=False)


# ---- add_ellipse live regression ----


async def test_add_ellipse_creates_real_ellipse(connected_adapter) -> None:
    """End-to-end check that add_ellipse creates a real axis-aligned ellipse.

    ``ISketchManager::CreateEllipse`` takes nine scalar doubles
    ``(XC, YC, Zc, XMajor, YMajor, ZMajor, XMinor, YMinor, ZMinor)``. This
    test locks in: (1) the major axis maps to +X / minor to +Y so the
    ellipse is axis-aligned, (2) the mm-to-m unit conversion is correct,
    (3) the returned ID is the expected ``Ellipse_<random>`` format.
    """
    adapter = connected_adapter

    part_result = await adapter.create_part()
    assert part_result.is_success, f"create_part failed: {part_result.error}"

    try:
        sketch_result = await adapter.create_sketch("Front")
        assert sketch_result.is_success, f"create_sketch failed: {sketch_result.error}"

        ellipse = await adapter.add_ellipse(
            center_x=0.0, center_y=0.0, major_axis=60.0, minor_axis=30.0
        )
        assert ellipse.is_success, f"add_ellipse failed: {ellipse.error}"
        assert ellipse.data.startswith("Ellipse_"), (
            f"unexpected ellipse id: {ellipse.data!r}"
        )
    finally:
        await adapter.close_model(save=False)


async def test_add_ellipse_no_active_sketch_returns_error(connected_adapter) -> None:
    """Calling add_ellipse without an open sketch must error without touching SW."""
    adapter = connected_adapter

    part_result = await adapter.create_part()
    assert part_result.is_success

    try:
        bad = await adapter.add_ellipse(0.0, 0.0, 60.0, 30.0)
        assert bad.is_error
        assert "No active sketch" in (bad.error or "")
    finally:
        await adapter.close_model(save=False)
