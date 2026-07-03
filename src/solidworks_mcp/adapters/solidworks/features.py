"""Feature-domain mixin for PyWin32 SolidWorks operations."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

from ..base import (
    AdapterResult,
    AdapterResultStatus,
    CircularPatternParameters,
    DraftParameters,
    ExtrusionParameters,
    LinearPatternParameters,
    LoftParameters,
    MirrorFeatureParameters,
    RevolveParameters,
    ShellParameters,
    SolidWorksFeature,
    SweepParameters,
)
from ..com_variant import empty_double_array, null_callout


class SolidWorksFeaturesMixin:
    """Expose SolidWorks feature methods via mixin-local implementation helpers."""

    async def create_extrusion(
        self, params: ExtrusionParameters
    ) -> AdapterResult[SolidWorksFeature]:
        return _create_extrusion_impl(self, params)

    async def create_revolve(
        self, params: RevolveParameters
    ) -> AdapterResult[SolidWorksFeature]:
        return _create_revolve_impl(self, params)

    async def create_sweep(
        self, params: SweepParameters
    ) -> AdapterResult[SolidWorksFeature]:
        return _create_sweep_impl(self, params)

    async def create_loft(
        self, params: LoftParameters
    ) -> AdapterResult[SolidWorksFeature]:
        return _create_loft_impl(self, params)

    async def create_cut_extrude(
        self, params: ExtrusionParameters
    ) -> AdapterResult[SolidWorksFeature]:
        return _create_cut_extrude_impl(self, params)

    async def add_fillet(
        self, radius: float, edge_points: list[list[float]]
    ) -> AdapterResult[SolidWorksFeature]:
        return _add_fillet_impl(self, radius, edge_points)

    async def add_chamfer(
        self,
        distance: float,
        edge_points: list[list[float]],
        face_points: list[list[float]] | None = None,
        tangent_propagation: bool = False,
    ) -> AdapterResult[SolidWorksFeature]:
        return _add_chamfer_impl(
            self, distance, edge_points, face_points, tangent_propagation
        )

    async def mirror_feature(
        self, params: MirrorFeatureParameters
    ) -> AdapterResult[SolidWorksFeature]:
        return _mirror_feature_impl(self, params)

    async def circular_pattern_feature(
        self, params: CircularPatternParameters
    ) -> AdapterResult[SolidWorksFeature]:
        return _circular_pattern_impl(self, params)

    async def linear_pattern_feature(
        self, params: LinearPatternParameters
    ) -> AdapterResult[SolidWorksFeature]:
        return _linear_pattern_impl(self, params)

    async def shell(self, params: ShellParameters) -> AdapterResult[SolidWorksFeature]:
        return _shell_impl(self, params)

    async def draft(self, params: DraftParameters) -> AdapterResult[SolidWorksFeature]:
        return _draft_impl(self, params)


def _create_extrusion_impl(
    adapter: Any, params: ExtrusionParameters
) -> AdapterResult[SolidWorksFeature]:
    """Create a boss-extrude feature from the active sketch profile.

    Attempts the modern ``FeatureExtrusion3`` COM call first; falls back to the
    legacy ``FeatureExtrusion2`` signature when the newer overload is absent.
    When ``params.thin_feature`` is truthy, the thin-wall variants
    (``FeatureExtrusionThin2`` / ``FeatureExtruThin2``) are used instead.

    All depth and thickness values are provided in millimetres and converted
    to metres internally.

    Args:
        adapter: A fully connected ``PyWin32Adapter`` instance.  Must have a
            non-``None`` ``currentModel`` and a valid ``FeatureManager``.
        params: Extrusion parameter bag.  Relevant fields:
            - ``depth`` (float): Extrude depth in mm.
            - ``draft_angle`` (float): Draft angle in degrees.  Default 0.
            - ``reverse_direction`` (bool): Flip the extrusion direction.
            - ``thin_feature`` (bool): Produce a thin-wall body.
            - ``thin_thickness`` (float | None): Wall thickness in mm when
              ``thin_feature`` is ``True``.
            - ``merge_result`` (bool): Merge with existing bodies.  Default
              ``True``.
            - ``both_directions`` (bool): Extrude symmetrically in both
              directions from the sketch plane.
            - ``auto_fillet_corners`` (bool): Round sharp thin-wall corners.
            - ``fillet_corners_radius`` (float): Corner fillet radius in mm.

    Returns:
        AdapterResult[SolidWorksFeature]: On success, ``data`` is a
        ``SolidWorksFeature`` whose ``type`` is ``"Extrusion"``.  On failure,
        ``status`` is ``ERROR`` and ``error`` contains a descriptive message.

    Raises:
        Exception: Propagated through ``_handle_com_operation`` when the COM
            call returns ``None`` for the created feature object.

    Example::

        from solidworks_mcp.adapters.base import ExtrusionParameters
        from solidworks_mcp.adapters import pywin32_feature_ops

        params = ExtrusionParameters(depth=25.0, draft_angle=2.0)
        result = pywin32_feature_ops.create_extrusion(adapter, params)
        print(result.data.name)  # e.g. "Boss-Extrude1"
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")

    def _extrusion_operation() -> SolidWorksFeature:
        """Inner COM closure that builds and returns the extrusion feature.

        Normalises ``params`` into a ``SimpleNamespace`` so every attribute
        access is guaranteed safe regardless of the dataclass version.  Picks
        the thin-wall or solid branch, then tries the modern API first before
        falling back to the legacy one.

        Returns:
            SolidWorksFeature: Populated feature descriptor on success.

        Raises:
            Exception: If both API variants return ``None``.
        """
        normalized = SimpleNamespace(
            depth=float(getattr(params, "depth", 0.0)),
            draft_angle=float(getattr(params, "draft_angle", 0.0)),
            reverse_direction=bool(getattr(params, "reverse_direction", False)),
            thin_feature=bool(getattr(params, "thin_feature", False)),
            thin_thickness=getattr(params, "thin_thickness", None),
            merge_result=bool(getattr(params, "merge_result", True)),
            both_directions=bool(getattr(params, "both_directions", False)),
            auto_fillet_corners=bool(getattr(params, "auto_fillet_corners", False)),
            fillet_corners_radius=float(getattr(params, "fillet_corners_radius", 0.0)),
        )
        feature_manager = adapter.currentModel.FeatureManager

        if normalized.thin_feature and normalized.thin_thickness:
            t0 = adapter.constants.get("swStartSketchPlane", 0)
            t1 = (
                adapter.constants["swEndCondMidPlane"]
                if normalized.both_directions
                else adapter.constants["swEndCondBlind"]
            )
            try:
                feature = feature_manager.FeatureExtrusionThin2(
                    True,
                    False,
                    normalized.reverse_direction,
                    t1,
                    adapter.constants["swEndCondBlind"],
                    normalized.depth / 1000.0,
                    0.0,
                    False,
                    False,
                    False,
                    False,
                    normalized.draft_angle * 3.14159 / 180.0,
                    0.0,
                    False,
                    False,
                    False,
                    False,
                    normalized.merge_result,
                    normalized.thin_thickness / 1000.0,
                    normalized.thin_thickness / 1000.0,
                    0.0,
                    0,
                    0,
                    normalized.auto_fillet_corners,
                    normalized.fillet_corners_radius / 1000.0,
                    False,
                    True,
                    t0,
                    0.0,
                    False,
                )
            except Exception:
                feature = feature_manager.FeatureExtruThin2(
                    normalized.depth / 1000.0,
                    0.0,
                    False,
                    normalized.draft_angle * 3.14159 / 180.0,
                    0.0,
                    False,
                    False,
                    normalized.merge_result,
                    False,
                    True,
                    normalized.thin_thickness / 1000.0,
                    normalized.thin_thickness / 1000.0,
                    False,
                    False,
                    False,
                    adapter.constants["swEndCondBlind"],
                    adapter.constants["swEndCondBlind"],
                )
        else:
            t0 = adapter.constants.get("swStartSketchPlane", 0)
            # Mid-plane extrusion: T1 carries the end condition; depth stays
            # the TOTAL depth (SolidWorks splits it across both sides).
            t1 = (
                adapter.constants["swEndCondMidPlane"]
                if normalized.both_directions
                else adapter.constants["swEndCondBlind"]
            )
            try:
                feature = feature_manager.FeatureExtrusion3(
                    True,
                    False,
                    normalized.reverse_direction,
                    t1,
                    adapter.constants["swEndCondBlind"],
                    normalized.depth / 1000.0,
                    0.0,
                    False,
                    False,
                    False,
                    False,
                    normalized.draft_angle * 3.14159 / 180.0,
                    0.0,
                    False,
                    False,
                    False,
                    False,
                    normalized.merge_result,
                    False,
                    True,
                    t0,
                    0.0,
                    False,
                )
            except Exception:
                feature = feature_manager.FeatureExtrusion2(
                    True,
                    False,
                    normalized.reverse_direction,
                    t1,
                    adapter.constants["swEndCondBlind"],
                    normalized.depth / 1000.0,
                    0.0,
                    False,
                    False,
                    False,
                    False,
                    normalized.draft_angle * 3.14159 / 180.0,
                    0.0,
                    False,
                    False,
                    False,
                    False,
                    normalized.merge_result,
                    False,
                    True,
                    t0,
                    0.0,
                    False,
                )

        if not feature:
            raise Exception("Failed to create extrusion feature")

        return SolidWorksFeature(
            name=feature.Name,
            type="Extrusion",
            id=adapter._get_feature_id(feature),
            parameters={
                "depth": normalized.depth,
                "draft_angle": normalized.draft_angle,
                "reverse_direction": normalized.reverse_direction,
                "thin_feature": normalized.thin_feature,
                "thin_thickness": normalized.thin_thickness,
            },
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation("create_extrusion", _extrusion_operation),
    )


def _create_revolve_impl(
    adapter: Any, params: RevolveParameters
) -> AdapterResult[SolidWorksFeature]:
    """Create a revolve feature from the active sketch profile around a centre axis.

    Uses ``FeatureRevolve2`` from the SolidWorks COM API.  The sketch must
    already contain a centre-line that SolidWorks will use as the rotation axis.

    Args:
        adapter: A fully connected ``PyWin32Adapter`` with a non-``None``
            ``currentModel``.
        params: Revolve parameter bag.  Relevant fields:
            - ``angle`` (float): Revolve angle in degrees.  Use 360 for a
              full revolution.
            - ``reverse_direction`` (bool): Flip the revolve direction.
            - ``both_directions`` (bool): Revolve symmetrically in both
              directions.
            - ``thin_feature`` (bool): Produce a thin-wall body.
            - ``thin_thickness`` (float | None): Wall thickness in mm.
            - ``merge_result`` (bool): Merge with existing bodies.

    Returns:
        AdapterResult[SolidWorksFeature]: On success, ``data`` is a
        ``SolidWorksFeature`` whose ``type`` is ``"Revolve"``.  On failure,
        ``status`` is ``ERROR``.

    Raises:
        Exception: Propagated through ``_handle_com_operation`` when
            ``FeatureRevolve2`` returns ``None``.

    Example::

        from solidworks_mcp.adapters.base import RevolveParameters
        from solidworks_mcp.adapters import pywin32_feature_ops

        params = RevolveParameters(angle=360.0, merge_result=True)
        result = pywin32_feature_ops.create_revolve(adapter, params)
        print(result.data.name)  # e.g. "Revolve1"
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")

    def _revolve_operation() -> SolidWorksFeature:
        """Inner COM closure that builds and returns the revolve feature.

        Converts the degree angle to radians and invokes ``FeatureRevolve2``.

        Returns:
            SolidWorksFeature: Populated feature descriptor on success.

        Raises:
            Exception: If ``FeatureRevolve2`` returns ``None``.
        """
        # Detect SW major version for FeatureRevolve2 API choice
        revolve_sw_major = 0
        if getattr(adapter, "swApp", None):
            rev = adapter._attempt(
                lambda: adapter._get_attr_or_call(adapter.swApp, "RevisionNumber"),
                default="0",
            )
            try:
                revolve_sw_major = int(str(rev).split(".")[0])
            except (ValueError, IndexError):
                revolve_sw_major = 0

        import math

        if revolve_sw_major == 33:
            # IFeatureManager.FeatureRevolve2 (20 params) per gen_py SW 2025
            # SingleDir, IsSolid, IsThin, IsCut, ReverseDir, BothDirUpToSame,
            # Dir1Type, Dir2Type, Dir1Angle(rad), Dir2Angle(rad),
            # OffsetRev1/2, OffsetDist1/2, Merge, ThinThick1/2(m), AutoSelect, Propagate
            feature_manager = adapter.currentModel.FeatureManager
            feature = feature_manager.FeatureRevolve2(
                True,  # SingleDir
                True,  # IsSolid
                False,  # IsThin
                params.is_cut,  # IsCut
                params.reverse_direction,  # ReverseDir
                params.both_directions,  # BothDirUpToSame
                0,
                0,  # Dir1Type, Dir2Type
                params.angle * math.pi / 180.0,  # Dir1Angle (rad)
                (params.angle * math.pi / 180.0)
                if params.both_directions
                else 0.0,  # Dir2Angle
                False,
                False,  # OffsetRev1/2
                0.0,
                0.0,  # OffsetDist1/2
                params.merge_result,  # Merge
                (params.thin_thickness or 0.0) / 1000.0,
                0.0,  # ThinThick1/2
                True,  # AutoSelect
                False,  # Propagate
            )
        else:
            feature_manager = adapter.currentModel.FeatureManager
            feature = feature_manager.FeatureRevolve2(
                not params.both_directions,
                True,
                params.thin_feature,
                params.is_cut,
                params.reverse_direction,
                False,
                adapter.constants["swEndCondBlind"],
                adapter.constants["swEndCondBlind"],
                params.angle * math.pi / 180.0,
                (params.angle * math.pi / 180.0) if params.both_directions else 0.0,
                False,
                False,
                0.0,
                0.0,
                0,
                (params.thin_thickness or 0.0) / 1000.0,
                0.0,
                params.merge_result,
                False,
                True,
            )

        # IModelDoc2.FeatureRevolve2 returns None (void) on SW 2025
        if not feature and revolve_sw_major != 33:
            raise Exception("Failed to create revolve feature")

        return SolidWorksFeature(
            name=feature.Name if feature else "Revolve-Auto",
            type="Revolve",
            id=adapter._get_feature_id(feature) if feature else "revolve_auto",
            parameters={
                "angle": params.angle,
                "reverse_direction": params.reverse_direction,
                "both_directions": params.both_directions,
                "thin_feature": params.thin_feature,
                "thin_thickness": params.thin_thickness,
            },
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation("create_revolve", _revolve_operation),
    )


def _select_named_feature(
    adapter: Any,
    name: str,
    mark: int,
    append: bool,
) -> bool:
    """Select a named feature under a specific selection mark via ``Select2``.

    Sweep and loft rely on selection marks to tell SolidWorks which selection
    is the profile (1), guide curve (2), or sweep path (4).  We resolve the
    feature with ``IModelDoc2::FeatureByName`` and select it with
    ``IFeature::Select2(append, mark)``.  This is preferred for *named* entities
    (sketches, planes, reference curves such as a helix) because it needs no
    entity-type string and no coordinate.  ``IModelDocExtension::SelectByID2``
    is the right tool for *geometric* entities that have no name (faces, edges
    by coordinate) — see :func:`_select_by_point`.  (Note: late-bound
    ``SelectByID2`` is not broken on this build; the ``Type mismatch`` once
    blamed on it was a bare-``None`` ``Callout`` argument — see
    :func:`solidworks_mcp.adapters.com_variant.null_callout`.)

    Args:
        adapter: A connected adapter with a valid ``currentModel``.
        name: Feature name (e.g. ``"Sketch1"`` or ``"Helix/Spiral1"``).  Any
            ``@document`` qualifier is stripped before lookup.
        mark: Selection mark — 1=profile, 2=guide curve, 4=sweep path.
        append: ``True`` to add to the current selection set, ``False`` to
            replace it.

    Returns:
        bool: ``True`` when the feature was found and selected.
    """
    bare = name.split("@", 1)[0]
    feature = adapter._attempt(
        lambda: adapter.currentModel.FeatureByName(bare), default=None
    )
    if not feature:
        return False
    return bool(adapter._attempt(lambda: feature.Select2(append, mark), default=False))


def _select_by_point(
    adapter: Any,
    entity_type: str,
    point_mm: list[float],
    mark: int,
    append: bool,
) -> bool:
    """Select a geometric entity (face/edge) by a point lying on it.

    Faces and edges have no caller-stable name, so the caller locates them with
    a point on the entity. Selection goes through ``SelectByID2`` with an empty
    name and the point in **metres** (the caller passes millimetres). The
    optional ``Callout`` argument is a typed-null VARIANT — passing bare
    ``None`` raises ``Type mismatch`` under pywin32 late binding (see
    :func:`solidworks_mcp.adapters.com_variant.null_callout`).

    .. warning:: Coordinate selection is **view-dependent**: SolidWorks picks
        at the point's screen projection, so an entity hidden behind the body
        in the current view orientation fails to select (verified live on SW
        2026: in the default trimetric view the box vertex at the far-lower
        corner and its adjacent hidden edges return ``False`` while all
        visible ones succeed). Callers should locate entities by points
        visible in the active view.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        entity_type: ``SelectByID2`` entity-type string, e.g. ``"FACE"`` or
            ``"EDGE"``.
        point_mm: ``[x, y, z]`` in millimetres on the target entity.
        mark: Selection mark.
        append: ``True`` to add to the current selection set, ``False`` to
            replace it.

    Returns:
        bool: ``True`` when SolidWorks selected an entity at that point.
    """
    if len(point_mm) != 3:
        return False
    x, y, z = (float(c) / 1000.0 for c in point_mm)
    return bool(
        adapter._attempt(
            lambda: adapter.currentModel.Extension.SelectByID2(
                "", entity_type, x, y, z, append, mark, null_callout(), 0
            ),
            default=False,
        )
    )


def _flag_feature_methods(obj: Any, interface: str) -> None:
    """Best-effort method flagging for a COM object via ``sw_type_info``.

    Flagging tells pywin32 late binding to resolve names like ``GetTypeName2``
    / ``GetNextFeature`` / ``FirstFeature`` as methods.  No-ops on plain test
    doubles (and any environment without the gen_py wrapper).

    Args:
        obj: The COM object (or test double) to flag.
        interface: SolidWorks interface name (e.g. ``"IFeature"``).
    """
    try:
        from solidworks_mcp.adapters import sw_type_info

        sw_type_info.flag_methods(obj, interface)
    except Exception:
        pass


def _read_member(obj: Any, name: str) -> Any:
    """Read a COM member that pywin32 may expose as a property *or* a method.

    Late-bound pywin32 dispatches are inconsistent: an unflagged zero-arg
    accessor may come back as a bound method (needing a call) *or* as the
    already-resolved value — and when that value is itself a COM object it is
    also callable, so a naive "call if callable" check wrongly invokes its
    default dispatch (``Member not found``).  This helper calls the member and
    falls back to the raw member if the call raises, so it yields the value in
    every case (flagged method, unflagged method, property-returning-object,
    or plain test double).

    Args:
        obj: The COM object (or test double) to read from.
        name: Member name.

    Returns:
        Any: The member's value, or ``None`` when the attribute is absent.
    """
    member = getattr(obj, name, None)
    if not callable(member):
        return member
    try:
        return member()
    except Exception:
        return member


def _profile_feature_names(adapter: Any) -> list[str]:
    """Return sketch (``ProfileFeature``) names in feature-tree order.

    Walks ``FirstFeature`` → ``GetNextFeature`` reading ``GetTypeName2`` and
    collecting features whose type is ``"ProfileFeature"`` (a 2D/3D sketch).
    Mirrors the tree walk used by :func:`_create_cut_extrude_impl`, but flags
    each feature for ``IFeature`` and reads members through
    :func:`_read_member` so it is robust to pywin32's method-vs-property
    late-binding ambiguity.

    Args:
        adapter: A connected adapter with a valid ``currentModel``.

    Returns:
        list[str]: Bare sketch names, earliest first.  Empty when the walk
        finds no sketches or the tree is inaccessible.
    """
    names: list[str] = []
    try:
        _flag_feature_methods(adapter.currentModel, "IModelDoc2")
        feat = _read_member(adapter.currentModel, "FirstFeature")
        # Bound the walk so a misbehaving GetNextFeature can't spin forever.
        for _ in range(5000):
            if not feat:
                break
            _flag_feature_methods(feat, "IFeature")
            try:
                if _read_member(feat, "GetTypeName2") == "ProfileFeature":
                    names.append(str(_read_member(feat, "Name")))
            except Exception:
                pass
            try:
                feat = _read_member(feat, "GetNextFeature")
            except Exception:
                break
    except Exception:
        pass
    return names


def _create_sweep_impl(
    adapter: Any, params: SweepParameters
) -> AdapterResult[SolidWorksFeature]:
    """Create a swept boss/protrusion from a profile sketch along a path sketch.

    Uses ``IFeatureManager::InsertProtrusionSwept4``.  Two sketches are
    required in the active part: a closed **profile** sketch and an open
    **path** sketch named by ``params.path``.  The path is selected under
    mark 4 and the profile under mark 1, per the SolidWorks selection-mark
    contract for sweeps.

    Because :class:`SweepParameters` only names the path, the profile is
    inferred as the first ``ProfileFeature`` sketch in the feature tree whose
    name is **not** the path.  In the common "draw profile, draw path, sweep"
    workflow this is unambiguous (exactly two sketches exist).

    Args:
        adapter: A fully connected ``PyWin32Adapter`` with a non-``None``
            ``currentModel``.
        params: Sweep parameter bag.  Relevant fields:
            - ``path`` (str): Name of the path sketch (e.g. ``"Sketch2"``).
            - ``twist_along_path`` (bool): Apply a constant twist along the
              path.
            - ``twist_angle`` (float): Twist angle in **degrees** (used only
              when ``twist_along_path`` is true).
            - ``merge_result`` (bool): Merge with existing bodies.

    Returns:
        AdapterResult[SolidWorksFeature]: On success, ``data`` is a
        ``SolidWorksFeature`` whose ``type`` is ``"Sweep"``.  On failure,
        ``status`` is ``ERROR`` with a descriptive message.

    Raises:
        Exception: Propagated through ``_handle_com_operation`` when the
            profile/path cannot be selected or the COM call returns ``None``.

    Example::

        from solidworks_mcp.adapters.base import SweepParameters

        params = SweepParameters(path="Sketch2", merge_result=True)
        result = await adapter.create_sweep(params)
        print(result.data.name)  # e.g. "Sweep1"
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")

    if not getattr(params, "path", None):
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Sweep requires a 'path' sketch name",
        )

    def _sweep_operation() -> SolidWorksFeature:
        """Inner COM closure that selects profile + path and runs the sweep.

        Returns:
            SolidWorksFeature: Populated feature descriptor on success.

        Raises:
            Exception: When selections fail or ``InsertProtrusionSwept4``
                returns ``None``.
        """
        import math

        feature_manager = adapter.currentModel.FeatureManager

        # Resolve the path name against the actual tree sketches so the
        # profile/path comparison is on bare names, then pick the first
        # non-path sketch as the profile.
        sketch_names = _profile_feature_names(adapter)
        path_name = params.path
        for name in sketch_names:
            if name == params.path or name.lower() == params.path.lower():
                path_name = name
                break

        # Profile = the most recently created sketch that isn't the path.
        # Preferring the latest sketch handles both a sketch path (profile is
        # drawn first, so it's the only non-path sketch) and a helix/curve
        # path (the helix's base-circle sketch precedes the profile in the
        # tree, so "first non-path" would wrongly pick the base circle).
        profile_name = None
        last = getattr(adapter, "_last_sketch_name", None)
        if last and last != path_name and last in sketch_names:
            profile_name = last
        if profile_name is None:
            profile_name = next(
                (name for name in reversed(sketch_names) if name != path_name), None
            )
        if profile_name is None:
            raise Exception(
                "Sweep needs a profile sketch distinct from the path "
                f"'{params.path}'. Sketches found: {sketch_names or 'none'}"
            )

        adapter._attempt(
            lambda: adapter.currentModel.ClearSelection2(True), default=None
        )

        if not _select_named_feature(adapter, profile_name, 1, False):
            raise Exception(f"Failed to select sweep profile sketch: {profile_name}")
        if not _select_named_feature(adapter, path_name, 4, True):
            raise Exception(f"Failed to select sweep path: {path_name}")

        twist = bool(getattr(params, "twist_along_path", False))
        twist_angle_deg = float(getattr(params, "twist_angle", 0.0))
        # swTwistControlType_e: 0 = follow path, 8 = constant twist along path.
        twist_ctrl = 8 if twist else 0
        twist_angle_rad = math.radians(twist_angle_deg) if twist else 0.0

        feature = feature_manager.InsertProtrusionSwept4(
            False,  # Propagate to next tangent edge
            False,  # Alignment (go through end faces)
            twist_ctrl,  # TwistCtrlOption (swTwistControlType_e)
            False,  # KeepTangency
            False,  # BAdvancedSmoothing
            0,  # StartMatchingType (swTangencyType_e)
            0,  # EndMatchingType
            False,  # IsThinBody
            0.0,  # Thickness1
            0.0,  # Thickness2
            0,  # ThinType (swThinWallType_e)
            0,  # PathAlign
            bool(getattr(params, "merge_result", True)),  # Merge
            True,  # UseFeatScope
            True,  # UseAutoSelect
            twist_angle_rad,  # TwistAngle (radians)
            True,  # BMergeSmoothFaces
            False,  # CircularProfile
            0.0,  # CircularProfileDiameter
            0,  # Direction
        )

        if not feature:
            raise Exception("Failed to create sweep feature")

        return SolidWorksFeature(
            name=feature.Name,
            type="Sweep",
            id=adapter._get_feature_id(feature),
            parameters={
                "profile": profile_name,
                "path": path_name,
                "twist_along_path": twist,
                "twist_angle": twist_angle_deg,
                "merge_result": bool(getattr(params, "merge_result", True)),
            },
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation("create_sweep", _sweep_operation),
    )


def _create_loft_impl(
    adapter: Any, params: LoftParameters
) -> AdapterResult[SolidWorksFeature]:
    """Create a lofted boss/protrusion between two or more profile sketches.

    Uses ``IFeatureManager::InsertProtrusionBlend2``.  Each profile named in
    ``params.profiles`` is selected under mark 1 (in order — the selection
    order determines the loft direction), and any ``params.guide_curves`` are
    selected under mark 2.  Because a solid is produced, every profile must be
    a closed contour.

    Args:
        adapter: A fully connected ``PyWin32Adapter`` with a non-``None``
            ``currentModel``.
        params: Loft parameter bag.  Relevant fields:
            - ``profiles`` (list[str]): Ordered profile sketch names; at least
              two are required.
            - ``guide_curves`` (list[str] | None): Optional guide curve names.
            - ``start_tangent`` / ``end_tangent`` (str | None): ``"normal"``
              tangency at the start/end profile, anything else / ``None`` →
              no tangency.
            - ``merge_result`` (bool): Merge with existing bodies.

    Returns:
        AdapterResult[SolidWorksFeature]: On success, ``data`` is a
        ``SolidWorksFeature`` whose ``type`` is ``"Loft"``.  On failure,
        ``status`` is ``ERROR`` with a descriptive message.

    Raises:
        Exception: Propagated through ``_handle_com_operation`` when a profile
            cannot be selected or the COM call returns ``None``.

    Example::

        from solidworks_mcp.adapters.base import LoftParameters

        params = LoftParameters(profiles=["Sketch1", "Sketch2"])
        result = await adapter.create_loft(params)
        print(result.data.name)  # e.g. "Loft1"
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")

    profiles = list(getattr(params, "profiles", None) or [])
    if len(profiles) < 2:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Loft requires at least 2 profile sketches",
        )

    def _loft_operation() -> SolidWorksFeature:
        """Inner COM closure that selects profiles/guides and runs the loft.

        Returns:
            SolidWorksFeature: Populated feature descriptor on success.

        Raises:
            Exception: When a profile selection fails or
                ``InsertProtrusionBlend2`` returns ``None``.
        """
        guide_curves = list(getattr(params, "guide_curves", None) or [])

        adapter._attempt(
            lambda: adapter.currentModel.ClearSelection2(True), default=None
        )

        # Profiles under mark 1, in order. First replaces the selection set,
        # the rest append so SW sees them as an ordered profile group.
        for index, profile in enumerate(profiles):
            if not _select_named_feature(adapter, profile, 1, append=index > 0):
                raise Exception(f"Failed to select loft profile sketch: {profile}")

        # Optional guide curves under mark 2 (a sketch or a reference curve).
        for guide in guide_curves:
            if not _select_named_feature(adapter, guide, 2, append=True):
                raise Exception(f"Failed to select loft guide curve: {guide}")

        # swTangencyType_e: 0 = none, 1 = tangent to profile normal.
        def _tangency(value: str | None) -> int:
            return 1 if str(value or "").strip().lower() == "normal" else 0

        start_match = _tangency(getattr(params, "start_tangent", None))
        end_match = _tangency(getattr(params, "end_tangent", None))

        feature_manager = adapter.currentModel.FeatureManager
        feature = feature_manager.InsertProtrusionBlend2(
            False,  # Closed loft
            True,  # KeepTangency
            False,  # ForceNonRational
            1.0,  # TessToleranceFactor
            start_match,  # StartMatchingType (swTangencyType_e)
            end_match,  # EndMatchingType
            1.0,  # StartTangentLength
            1.0,  # EndTangentLength
            True,  # StartTangentDir
            True,  # EndTangentDir
            False,  # IsThinBody
            0.0,  # Thickness1
            0.0,  # Thickness2
            0,  # ThinType
            bool(getattr(params, "merge_result", True)),  # Merge
            True,  # UseFeatScope
            True,  # UseAutoSelect
            2,  # GuideCurveInfluence (swGuideCurveInfluenceNextEdge)
        )

        if not feature:
            raise Exception("Failed to create loft feature")

        return SolidWorksFeature(
            name=feature.Name,
            type="Loft",
            id=adapter._get_feature_id(feature),
            parameters={
                "profiles": profiles,
                "guide_curves": guide_curves or None,
                "start_tangent": getattr(params, "start_tangent", None),
                "end_tangent": getattr(params, "end_tangent", None),
                "merge_result": bool(getattr(params, "merge_result", True)),
            },
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation("create_loft", _loft_operation),
    )


def _create_cut_extrude_impl(
    adapter: Any, params: ExtrusionParameters
) -> AdapterResult[SolidWorksFeature]:
    """Create a cut-extrude feature from the active sketch profile.

    The function first attempts to locate and select the sketch profile that
    should be cut.  It walks the feature tree looking for the most recent
    ``ProfileFeature``; if that fails, it falls back to the ``_last_sketch_name``
    tracker and then to an enumerated ``Sketch<N>`` name search.

    Three COM API variants are attempted in order of preference:

    1. ``FeatureCut4`` ΓÇö most modern (SolidWorks 2015+).
    2. ``FeatureCut3`` modern signature ΓÇö SolidWorks 2010ΓÇô2014.
    3. ``FeatureCut3`` legacy argument order ΓÇö older installs.

    All depth values are in millimetres and converted to metres internally.

    Args:
        adapter: A fully connected ``PyWin32Adapter`` with a non-``None``
            ``currentModel``.
        params: Extrusion parameter bag reused for cut parameters:
            - ``depth`` (float): Cut depth in mm.
            - ``draft_angle`` (float): Draft angle in degrees.
            - ``reverse_direction`` (bool): Flip the cut direction.
            - ``end_condition`` (str): ``"Blind"`` (default) or
              ``"ThroughAll"`` / ``"through_all"``.
            - ``feature_scope`` (bool): Limit cut to selected bodies.
            - ``auto_select`` (bool): Auto-select bodies in scope.

    Returns:
        AdapterResult[SolidWorksFeature]: On success, ``data`` is a
        ``SolidWorksFeature`` whose ``type`` is ``"Cut-Extrude"``.  On
        failure, ``status`` is ``ERROR`` and ``error`` lists every API
        variant that was tried.

    Raises:
        Exception: Propagated through ``_handle_com_operation`` when all
            three COM variants fail.

    Example::

        from solidworks_mcp.adapters.base import ExtrusionParameters
        from solidworks_mcp.adapters import pywin32_feature_ops

        params = ExtrusionParameters(depth=10.0, end_condition="ThroughAll")
        result = pywin32_feature_ops.create_cut_extrude(adapter, params)
        print(result.data.name)  # e.g. "Cut-Extrude1"
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")

    def _cut_operation() -> SolidWorksFeature:
        """Inner COM closure that locates the active sketch and performs the cut.

        Normalises ``params``, resolves the end-condition constant, selects the
        sketch profile, then cascades through three ``FeatureCut`` overloads.

        Returns:
            SolidWorksFeature: Populated feature descriptor on success.

        Raises:
            Exception: When all COM cut variants return ``None``.
        """
        normalized = SimpleNamespace(
            depth=float(getattr(params, "depth", 0.0)),
            draft_angle=float(getattr(params, "draft_angle", 0.0)),
            reverse_direction=bool(getattr(params, "reverse_direction", False)),
            end_condition=str(getattr(params, "end_condition", "Blind")),
            feature_scope=bool(getattr(params, "feature_scope", False)),
            auto_select=bool(getattr(params, "auto_select", True)),
            both_directions=bool(getattr(params, "both_directions", False)),
            selected_contours=getattr(params, "selected_contours", None),
            start_offset=float(getattr(params, "start_offset", 0.0)),
            flip_start_offset=bool(getattr(params, "flip_start_offset", False)),
        )
        feature_manager = adapter.currentModel.FeatureManager

        end_condition = (normalized.end_condition or "Blind").strip().lower()
        depth_m = normalized.depth / 1000.0
        # T1 carries the end condition. ThroughAll wins over both_directions
        # (combined as ThroughAllBoth where the install defines it); a blind
        # cut with both_directions becomes mid-plane, where depth stays the
        # TOTAL depth (SolidWorks splits it across both sides).
        if end_condition in {"throughall", "through all", "through_all"}:
            t1 = adapter.constants["swEndCondThroughAll"]
            if normalized.both_directions:
                t1 = adapter.constants.get("swEndCondThroughAllBoth", t1)
        elif normalized.both_directions:
            t1 = adapter.constants["swEndCondMidPlane"]
        else:
            t1 = adapter.constants["swEndCondBlind"]

        if normalized.start_offset:
            t0 = adapter.constants.get("swStartOffset", 3)
            start_offset_m = normalized.start_offset / 1000.0
        else:
            t0 = adapter.constants.get("swStartSketchPlane", 0)
            start_offset_m = 0.0
        flip_start = normalized.flip_start_offset
        adapter._attempt(
            lambda: adapter.currentModel.ClearSelection2(True), default=None
        )
        sketch_selected = False

        # Selected-contour cut: instead of consuming the whole profile, select
        # the individual SKETCHREGION contours by a model-space point inside each
        # (metres). This is how a hand-built cut takes only the triangles bounded
        # by a sketch's construction diagonals. SelectByID2 with an empty name +
        # type "SKETCHREGION" resolves the region of the most recent visible
        # sketch under that point; mark 1 tags each as a cut contour.
        if normalized.selected_contours:
            for i, (cx, cy, cz) in enumerate(normalized.selected_contours):
                ok = adapter._attempt(
                    lambda x=cx, y=cy, z=cz, ap=(i > 0): (
                        adapter.currentModel.Extension.SelectByID2(
                            "", "SKETCHREGION", x, y, z, ap, 1, null_callout(), 0
                        )
                    ),
                    default=False,
                )
                sketch_selected = sketch_selected or bool(ok)
            if not sketch_selected:
                raise Exception(
                    "selected_contours: no SKETCHREGION resolved at the given "
                    f"points {normalized.selected_contours!r}"
                )

        # Select the profile to cut: the LAST unconsumed top-level sketch
        # (``ProfileFeature``), by its CURRENT name. ``_profile_feature_names``
        # walks the tree with the method-flagging the rest of the adapter relies
        # on -- a bare ``model.FirstFeature``/``GetTypeName2`` walk fails here, the
        # active doc is a late-bound CDispatch whose feature methods don't resolve
        # by name without flagging -- and reads LIVE names. So this is rename-proof:
        # a renamed sketch is still found and selected by its live name, where the
        # cached ``_last_sketch_name`` string (fallback below) goes stale on rename.
        profile_names = _profile_feature_names(adapter)
        if profile_names and not normalized.selected_contours:
            target = profile_names[-1]
            sketch_selected = bool(
                adapter._attempt(
                    lambda t=target: adapter.currentModel.Extension.SelectByID2(
                        t, "SKETCH", 0.0, 0.0, 0.0, False, 0, null_callout(), 0
                    ),
                    default=False,
                )
            )
            if sketch_selected:
                adapter._last_sketch_name = target

        if not sketch_selected:
            for candidate in (
                [adapter._last_sketch_name] if adapter._last_sketch_name else []
            ) + [f"Sketch{n}" for n in range(adapter._sketch_count, 0, -1)]:
                sel_result = adapter._attempt(
                    lambda c=candidate: adapter.currentModel.Extension.SelectByID2(
                        c, "SKETCH", 0.0, 0.0, 0.0, False, 0, null_callout(), 0
                    ),
                    default=False,
                )
                sketch_selected = bool(sel_result)
                if sketch_selected:
                    adapter._last_sketch_name = candidate
                    break

        feature = None
        fallback_errors: list[str] = []
        is_through = end_condition in {"throughall", "through all", "through_all"}

        # Detect SW major version for FeatureCut4 parameter count
        # SW 2025 (major=33) verified with 27 params; other versions use 28.
        sw_major = 0
        if getattr(adapter, "swApp", None):
            rev = adapter._attempt(
                lambda: adapter._get_attr_or_call(adapter.swApp, "RevisionNumber"),
                default="0",
            )
            try:
                sw_major = int(str(rev).split(".")[0])
            except (ValueError, IndexError):
                sw_major = 0

        # 1. FeatureCut4 (SW 2015+)
        # Note: SW 2025 (major=33) verified with 27 params by VBA macro.
        # Other versions use 28 params (original code).
        if sw_major == 33:
            feature, cut4_error = adapter._attempt_with_error(
                lambda: feature_manager.FeatureCut4(
                    is_through,  # Sd
                    False,  # Flip
                    normalized.reverse_direction,  # Dir
                    t1,  # T1
                    adapter.constants["swEndCondBlind"],  # T2
                    depth_m,  # D1
                    0.0,  # D2
                    False,
                    False,
                    False,
                    False,  # Dchk1/2, Ddir1/2
                    normalized.draft_angle * 3.14159 / 180.0,  # Dang1
                    0.0,  # Dang2
                    False,
                    False,
                    False,
                    False,  # OffsetRev1/2, TranslateSurf1/2
                    False,  # NormalCut
                    normalized.feature_scope,  # UseFeatScope
                    normalized.auto_select,  # UseAutoSelect
                    False,  # AssemblyFeatureScope
                    False,  # AutoSelectComponents
                    False,  # PropagateFeatureToParts
                    t0,  # T0
                    start_offset_m,  # StartOffset
                    flip_start,  # FlipStartOffset
                )
            )
        else:
            feature, cut4_error = adapter._attempt_with_error(
                lambda: feature_manager.FeatureCut4(
                    True,
                    False,
                    normalized.reverse_direction,
                    t1,
                    adapter.constants["swEndCondBlind"],
                    depth_m,
                    0.0,
                    False,
                    False,
                    False,
                    False,
                    normalized.draft_angle * 3.14159 / 180.0,
                    0.0,
                    False,
                    False,
                    False,
                    False,
                    False,
                    normalized.feature_scope,
                    normalized.auto_select,
                    False,
                    False,
                    False,
                    t0,
                    start_offset_m,
                    flip_start,
                    False,
                )
            )
        if cut4_error is not None:
            fallback_errors.append(f"FeatureCut4: {cut4_error}")

        if not feature:
            # 2. FeatureCut3 modern (SW 2010+, 26 params, corrected for SW 2022)
            # Signature: Sd, Flip, Dir, T1, T2, D1, D2, Dchk1, Dchk2, Ddir1, Ddir2,
            #   Dang1, Dang2, OffsetReverse1, OffsetReverse2, TranslateSurface1,
            #   TranslateSurface2, NormalCut, UseFeatScope, UseAutoSelect,
            #   AssemblyFeatureScope, AutoSelectComponents, PropagateFeatureToParts,
            #   T0, StartOffset, FlipStartOffset
            feature, cut3_modern_error = adapter._attempt_with_error(
                lambda: feature_manager.FeatureCut3(
                    is_through,
                    normalized.reverse_direction,
                    False,
                    t1,
                    0,
                    normalized.depth / 1000.0,
                    normalized.depth / 1000.0,
                    False,
                    False,
                    False,
                    False,
                    normalized.draft_angle * 3.14159 / 180.0,
                    0.0,
                    False,
                    False,
                    False,
                    False,
                    False,
                    normalized.feature_scope,
                    normalized.auto_select,
                    False,
                    False,
                    False,
                    t0,
                    0.0,
                    False,
                )
            )
            if cut3_modern_error is not None:
                fallback_errors.append(f"FeatureCut3 modern: {cut3_modern_error}")

        if not feature:
            # 3. FeatureCut3 legacy (older installs, alternate arg order)
            feature, cut3_legacy_error = adapter._attempt_with_error(
                lambda: feature_manager.FeatureCut3(
                    True,
                    False,
                    normalized.reverse_direction,
                    t1,
                    adapter.constants["swEndCondBlind"],
                    False,
                    False,
                    False,
                    False,
                    normalized.draft_angle * 3.14159 / 180.0,
                    0.0,
                    False,
                    False,
                    False,
                    False,
                    False,
                    normalized.feature_scope,
                    normalized.auto_select,
                    normalized.depth / 1000.0,
                    0.0,
                )
            )
            if cut3_legacy_error is not None:
                fallback_errors.append(f"FeatureCut3 legacy: {cut3_legacy_error}")

        if not feature:
            if fallback_errors:
                raise Exception(
                    "Failed to create cut extrude feature. "
                    + " | ".join(fallback_errors)
                )
            raise Exception("Failed to create cut extrude feature")

        return SolidWorksFeature(
            name=feature.Name,
            type="Cut-Extrude",
            id=adapter._get_feature_id(feature),
            parameters={
                "depth": normalized.depth,
                "draft_angle": normalized.draft_angle,
                "reverse_direction": normalized.reverse_direction,
            },
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation("create_cut_extrude", _cut_operation),
    )


def _feature_objects(adapter: Any) -> list[tuple[str, Any]]:
    """Walk the feature tree, returning ``(name, COM object)`` for each feature.

    Robust to pywin32's method-vs-property ambiguity via :func:`_read_member`.
    The walk is bounded so a misbehaving ``GetNextFeature`` cannot spin forever.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.

    Returns:
        list[tuple[str, Any]]: ``(name, feature)`` pairs in tree order. Empty
        when the tree is inaccessible.
    """
    out: list[tuple[str, Any]] = []
    try:
        _flag_feature_methods(adapter.currentModel, "IModelDoc2")
        feat = _read_member(adapter.currentModel, "FirstFeature")
        for _ in range(5000):
            if not feat:
                break
            # Flag only the one method the walk calls. Full IFeature flagging
            # costs a GetIDsOfNames round-trip per method name per feature —
            # on every walk, because each GetNextFeature returns a fresh
            # CDispatch the id()-keyed cache never hits — which made tree
            # diffs quadratic in feature count (~13 s per feature creation on
            # a 30-feature tree). ``Name`` is a property and needs no flag;
            # ``_read_member`` tolerates either resolution anyway.
            try:
                feat._FlagAsMethod("GetNextFeature")
            except Exception:
                pass
            try:
                name = _read_member(feat, "Name")
            except Exception:
                name = None
            out.append((str(name) if name is not None else "", feat))
            try:
                feat = _read_member(feat, "GetNextFeature")
            except Exception:
                break
    except Exception:
        pass
    return out


def _feature_names(adapter: Any) -> set[str]:
    """Return the set of feature names currently in the tree.

    Captured before a feature-creation call so the new feature can later be
    identified by diffing (see :func:`_resolve_feature`).

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.

    Returns:
        set[str]: Feature names present now.
    """
    return {name for name, _ in _feature_objects(adapter) if name}


def _resolve_feature(adapter: Any, returned: Any, names_before: set[str]) -> Any:
    """Return a usable ``IFeature`` for a just-created feature.

    Prefers the value the COM call returned when it exposes a readable
    ``Name``.  Some calls instead return a non-feature (``FeatureFillet3``
    returns an ``int`` on this build) or ``None`` on success
    (``InsertFeatureShell``); in that case the new feature is found by diffing
    the current tree against ``names_before``.  Diffing (rather than taking the
    tree tail) is robust even when a call also appends auxiliary features.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        returned: Whatever the feature-creation COM call returned.
        names_before: Feature names captured before the call
            (:func:`_feature_names`).

    Returns:
        Any: A feature object exposing ``Name``, or ``None`` if none is found.
    """
    if returned and _read_member(returned, "Name") is not None:
        return returned
    new = [
        feat
        for name, feat in _feature_objects(adapter)
        if name and name not in names_before
    ]
    if not new:
        return None
    # The walk flags only GetNextFeature (perf); fully flag the one feature
    # handed to callers so its members dispatch correctly downstream.
    _flag_feature_methods(new[-1], "IFeature")
    return new[-1]


def _all_body_edges(adapter: Any) -> list[Any]:
    """Every edge of every solid body in the active model (flagged for late bind)."""
    model = adapter.currentModel
    bodies = adapter._attempt(lambda: model.GetBodies2(0, True), default=None) or []
    edges: list[Any] = []
    for body in bodies:
        _flag_feature_methods(body, "IBody2")
        for edge in adapter._attempt(lambda b=body: b.GetEdges(), default=None) or []:
            _flag_feature_methods(edge, "IEdge")
            edges.append(edge)
    return edges


def _select_edges_geometric(
    adapter: Any, edge_points: list[list[float]], tol_mm: float = 0.5
) -> bool:
    """Select edges by matching a point on each to the body's actual edges.

    Unlike :func:`_select_by_point` (which drives ``SelectByID2`` and is
    therefore **view-dependent** -- it picks at the screen projection, so an edge
    hidden behind the body in the active view silently fails to select), this
    resolves each target point against the geometry directly: it walks every body
    edge, asks ``IEdge.GetClosestPointOn`` for the nearest point on that edge, and
    selects (``IEntity.Select2``) the one within ``tol_mm``. View orientation is
    irrelevant, so all of a fillet's/chamfer's edges resolve in one pass even when
    half of them face away from the camera.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        edge_points: Points ``[x, y, z]`` (mm), one per edge to select.
        tol_mm: Max distance (mm) from the point to an edge to count as a hit.

    Returns:
        bool: ``True`` only when every point resolved to an edge and was
        selected; ``False`` on the first miss (caller may fall back).
    """
    edges = _all_body_edges(adapter)
    if not edges:
        return False
    tol_m = tol_mm / 1000.0
    adapter._attempt(lambda: adapter.currentModel.ClearSelection2(True), default=None)
    for point in edge_points:
        if len(point) != 3:
            return False
        px, py, pz = (float(c) / 1000.0 for c in point)
        best, best_d = None, tol_m
        for edge in edges:
            cp = adapter._attempt(
                lambda e=edge, px=px, py=py, pz=pz: list(e.GetClosestPointOn(px, py, pz)),
                default=None,
            )
            if not cp or len(cp) < 3:
                continue
            d = ((cp[0] - px) ** 2 + (cp[1] - py) ** 2 + (cp[2] - pz) ** 2) ** 0.5
            if d < best_d:
                best, best_d = edge, d
        if best is None:
            return False
        _flag_feature_methods(best, "IEntity")
        if not adapter._attempt(lambda e=best: e.Select2(True, 0), default=False):
            return False
    return True


def _all_body_faces(adapter: Any) -> list[Any]:
    """Every face of every solid body in the active model (flagged for late bind)."""
    model = adapter.currentModel
    bodies = adapter._attempt(lambda: model.GetBodies2(0, True), default=None) or []
    faces: list[Any] = []
    for body in bodies:
        _flag_feature_methods(body, "IBody2")
        for face in adapter._attempt(lambda b=body: b.GetFaces(), default=None) or []:
            _flag_feature_methods(face, "IFace2")
            faces.append(face)
    return faces


def _select_faces_geometric(
    adapter: Any, face_points: list[list[float]], append: bool, tol_mm: float = 5.0
) -> bool:
    """Select whole faces by matching a point on each to the body's actual faces.

    The geometric, view-independent analogue of :func:`_select_edges_geometric`
    for faces: it walks every body face, asks ``IFace2.GetClosestPointOn`` for the
    nearest point on that face, and selects (``IEntity.Select2``, mark 0) the one
    closest to each target point. Selecting a *face* for a chamfer/fillet breaks
    **all** of that face's edges -- the way a hand-built feature picks "this whole
    window-surround face" rather than naming each rim edge.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        face_points: Points ``[x, y, z]`` (mm), one per face to select.
        append: When ``True``, add to the current selection (so faces stack onto
            already-selected edges); when ``False``, the first face replaces it.
        tol_mm: Max distance (mm) from the point to a face to count as a hit; a
            little slack absorbs bbox-centre points that sit just off a tilted
            or curved face.

    Returns:
        bool: ``True`` only when every point resolved to a face and was selected;
        ``False`` on the first miss.
    """
    faces = _all_body_faces(adapter)
    if not faces:
        return False
    tol_m = tol_mm / 1000.0
    for i, point in enumerate(face_points):
        if len(point) != 3:
            return False
        px, py, pz = (float(c) / 1000.0 for c in point)
        best, best_d = None, tol_m
        for face in faces:
            cp = adapter._attempt(
                lambda f=face, px=px, py=py, pz=pz: list(f.GetClosestPointOn(px, py, pz)),
                default=None,
            )
            if not cp or len(cp) < 3:
                continue
            d = ((cp[0] - px) ** 2 + (cp[1] - py) ** 2 + (cp[2] - pz) ** 2) ** 0.5
            if d < best_d:
                best, best_d = face, d
        if best is None:
            return False
        _flag_feature_methods(best, "IEntity")
        keep = append or i > 0
        if not adapter._attempt(lambda f=best, k=keep: f.Select2(k, 0), default=False):
            return False
    return True


def _select_edge_points(adapter: Any, edge_points: list[list[float]]) -> None:
    """Clear the selection, then select each edge located by a point on it.

    Prefers view-independent geometric resolution
    (:func:`_select_edges_geometric`); falls back to view-dependent
    :func:`_select_by_point` picking when the geometric pass can't enumerate
    bodies (e.g. test doubles).

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        edge_points: Points ``[x, y, z]`` (mm), one per edge to select.

    Raises:
        Exception: When an edge cannot be selected at a given point.
    """
    if _select_edges_geometric(adapter, edge_points):
        return
    adapter._attempt(lambda: adapter.currentModel.ClearSelection2(True), default=None)
    for point in edge_points:
        if not _select_by_point(adapter, "EDGE", point, 0, True):
            raise Exception(f"Failed to select edge at point {point} (mm)")


def _add_fillet_impl(
    adapter: Any, radius: float, edge_points: list[list[float]]
) -> AdapterResult[SolidWorksFeature]:
    """Create a constant-radius fillet on edges located by coordinate.

    Each edge is located by a point on it (millimetres) and selected with
    ``SelectByID2`` — SolidWorks edges have no caller-stable name (the
    ``"Edge<1>"`` form is not a valid ``SelectByID2`` identifier on this build).
    After all edges are selected, ``IModelDoc2::FeatureFillet3`` (constant-size
    form) builds the round.

    Args:
        adapter: A fully connected ``PyWin32Adapter`` with a non-``None``
            ``currentModel``.
        radius: Fillet radius in **millimetres**.  Converted to metres before
            the COM call.
        edge_points: Points ``[x, y, z]`` in mm, one per edge to fillet.

    Returns:
        AdapterResult[SolidWorksFeature]: On success, ``data`` is a
        ``SolidWorksFeature`` whose ``type`` is ``"Fillet"``.  On failure,
        ``status`` is ``ERROR``.

    Raises:
        Exception: Propagated through ``_handle_com_operation`` when an edge
            cannot be selected or the fillet feature is not created.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not edge_points:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Fillet requires at least one edge point",
        )

    def _fillet_operation() -> SolidWorksFeature:
        names_before = _feature_names(adapter)
        _select_edge_points(adapter, edge_points)

        # IModelDoc2.FeatureFillet3 constant-radius form (9 args) — verified on
        # SW 2025 and 2026.  NRadii=0 applies R1 (metres) to every selected
        # edge.  (The old IFeatureManager 16-arg branch had the wrong arity and
        # the old SelectByID2-by-name path could never select an edge live.)
        feature = adapter.currentModel.FeatureFillet3(
            radius / 1000.0,  # R1 (metres)
            True,  # Propagate to tangent faces
            0,  # Ftyp (0 = constant-size round)
            False,  # VarRadTyp
            0,  # OverflowType (default)
            0,  # NRadii
            empty_double_array(),  # Radii (empty array; unused when NRadii == 0)
            False,  # UseHelpPoint
            False,  # UseTangentHoldLine
        )
        feature = _resolve_feature(adapter, feature, names_before)
        if not feature:
            raise Exception("Failed to create fillet")

        return SolidWorksFeature(
            name=str(_read_member(feature, "Name")),
            type="Fillet",
            id=adapter._get_feature_id(feature),
            parameters={"radius": radius, "edge_points": edge_points},
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation("add_fillet", _fillet_operation),
    )


def _add_chamfer_impl(
    adapter: Any,
    distance: float,
    edge_points: list[list[float]],
    face_points: list[list[float]] | None = None,
    tangent_propagation: bool = False,
) -> AdapterResult[SolidWorksFeature]:
    """Create an angle-distance (45°) chamfer on edges and/or whole faces.

    Each edge is located by a point on it (millimetres) and resolved
    view-independently (:func:`_select_edge_points`).  ``face_points`` selects
    **whole faces** (:func:`_select_faces_geometric`); a face in a chamfer breaks
    *all* of that face's edges -- the way a hand-built feature picks a
    window-surround face instead of naming every rim edge.

    ``IFeatureManager.InsertFeatureChamfer(Options, ChamferType, Width, Angle,
    ...)`` builds the feature: ``ChamferType = swChamferAngleDistance`` and a 45°
    angle yields equal legs of ``distance``.  ``tangent_propagation`` sets the
    ``swFeatureChamferTangentPropagation`` (0x4) option bit so the chamfer runs
    around tangent-connected edges, matching the GUI's default.  (The 3-arg
    ``IModelDoc2.FeatureChamfer`` form cannot take faces or propagation.)

    Args:
        adapter: A fully connected ``PyWin32Adapter`` with a non-``None``
            ``currentModel``.
        distance: Chamfer leg length in **millimetres**.  Converted to metres.
        edge_points: Points ``[x, y, z]`` in mm, one per edge to chamfer.
        face_points: Points ``[x, y, z]`` in mm, one per face whose edges are all
            chamfered.  ``None``/empty chamfers only the listed edges.
        tangent_propagation: When ``True``, propagate the chamfer along
            tangent-connected edges.

    Returns:
        AdapterResult[SolidWorksFeature]: On success, ``data`` is a
        ``SolidWorksFeature`` whose ``type`` is ``"Chamfer"``.  On failure,
        ``status`` is ``ERROR``.

    Raises:
        Exception: Propagated through ``_handle_com_operation`` when an edge or
            face cannot be selected or the chamfer feature is not created.
    """
    import math

    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not edge_points and not face_points:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Chamfer requires at least one edge or face point",
        )

    def _chamfer_operation() -> SolidWorksFeature:
        names_before = _feature_names(adapter)
        if edge_points:
            _select_edge_points(adapter, edge_points)
        else:
            adapter._attempt(
                lambda: adapter.currentModel.ClearSelection2(True), default=None
            )
        if face_points and not _select_faces_geometric(
            adapter, face_points, append=bool(edge_points)
        ):
            raise Exception(f"Failed to select chamfer faces {face_points} (mm)")

        # IFeatureManager.InsertFeatureChamfer: Options bitmask (0x4 = tangent
        # propagation), ChamferType 1 = swChamferAngleDistance, then Width
        # (metres) + Angle (radians); 45° => equal legs == Width. Remaining
        # distance args are unused for the angle-distance type.
        options = 0x4 if tangent_propagation else 0
        feature = adapter.currentModel.FeatureManager.InsertFeatureChamfer(
            options,
            1,  # swChamferAngleDistance
            distance / 1000.0,  # Width (metres)
            math.radians(45.0),  # Angle (radians)
            0.0,  # OtherDist (equal-distance only)
            0.0,
            0.0,
            0.0,  # Vertex distances (vertex chamfer only)
        )
        feature = _resolve_feature(adapter, feature, names_before)
        if not feature:
            raise Exception("Failed to create chamfer")

        return SolidWorksFeature(
            name=str(_read_member(feature, "Name")),
            type="Chamfer",
            id=adapter._get_feature_id(feature),
            parameters={
                "distance": distance,
                "edge_points": edge_points,
                "face_points": face_points or [],
                "tangent_propagation": tangent_propagation,
            },
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation("add_chamfer", _chamfer_operation),
    )


def _select_reference_point(
    adapter: Any,
    point_mm: list[float],
    mark: int,
    entity_types: tuple[str, ...] = ("EDGE", "AXIS", "FACE"),
) -> str | None:
    """Select a direction/axis reference located by a point on it.

    A pattern's direction (linear) or axis (circular) can be a linear edge, a
    reference axis, or a cylindrical/planar face.  The caller points at one;
    this tries each entity type at that point and returns the type that
    selected, or ``None``.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        point_mm: ``[x, y, z]`` in millimetres on the reference entity.
        mark: Selection mark to apply.
        entity_types: ``SelectByID2`` entity types to try, in order.

    Returns:
        str | None: The entity type that selected, or ``None`` if none matched.
    """
    for entity_type in entity_types:
        if _select_by_point(adapter, entity_type, point_mm, mark, True):
            return entity_type
    return None


def _mirror_feature_impl(
    adapter: Any, params: MirrorFeatureParameters
) -> AdapterResult[SolidWorksFeature]:
    """Mirror one or more named features about a plane via ``InsertMirrorFeature2``.

    Features to mirror are selected by name under mark 1; the mirror plane (a
    reference plane or planar face) is selected by name under mark 2.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        params: Mirror parameters (plane name, feature names, options).

    Returns:
        AdapterResult[SolidWorksFeature]: ``data.type == "Mirror"`` on success.

    Raises:
        Exception: Propagated through ``_handle_com_operation`` on selection
            failure or when the mirror feature is not created.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not params.features:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Mirror requires at least one feature to mirror",
        )
    if not params.plane:
        return AdapterResult(
            status=AdapterResultStatus.ERROR, error="Mirror requires a 'plane' name"
        )

    def _mirror_operation() -> SolidWorksFeature:
        adapter._attempt(
            lambda: adapter.currentModel.ClearSelection2(True), default=None
        )
        for name in params.features:
            if not _select_named_feature(adapter, name, 1, True):
                raise Exception(f"Failed to select feature to mirror: {name}")
        if not _select_named_feature(adapter, params.plane, 2, True):
            raise Exception(f"Failed to select mirror plane: {params.plane}")

        feature_manager = adapter.currentModel.FeatureManager
        _flag_feature_methods(feature_manager, "IFeatureManager")
        names_before = _feature_names(adapter)
        feature = feature_manager.InsertMirrorFeature2(
            False,  # BMirrorBody (mirror features, not bodies)
            bool(params.geometry_pattern),  # BGeometryPattern
            bool(params.merge),  # BMerge
            False,  # BKnit (surfaces only)
            0,  # ScopeOptions = swFeatureScope_AllBodies
        )
        feature = _resolve_feature(adapter, feature, names_before)
        if not feature:
            raise Exception("Failed to create mirror feature")

        return SolidWorksFeature(
            name=str(_read_member(feature, "Name")),
            type="Mirror",
            id=adapter._get_feature_id(feature),
            parameters={
                "plane": params.plane,
                "features": params.features,
                "merge": bool(params.merge),
                "geometry_pattern": bool(params.geometry_pattern),
            },
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation("mirror_feature", _mirror_operation),
    )


def _circular_pattern_impl(
    adapter: Any, params: CircularPatternParameters
) -> AdapterResult[SolidWorksFeature]:
    """Circular-pattern named features about an axis via ``FeatureCircularPattern5``.

    The rotation axis is selected under mark 1 — by feature name when
    ``params.axis_name`` is given (a reference axis, robust), otherwise by a
    point on the reference (a cylindrical face or a linear edge; the point
    pick projects through the view, so it fails on axes hidden inside solid
    material). The seed features are selected by name under mark 4.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        params: Circular-pattern parameters.

    Returns:
        AdapterResult[SolidWorksFeature]: ``data.type == "CircularPattern"`` on
        success.

    Raises:
        Exception: Propagated through ``_handle_com_operation`` on selection
            failure or when the pattern feature is not created.
    """
    import math

    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not params.features:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Circular pattern requires at least one feature",
        )
    if params.count < 1:
        return AdapterResult(
            status=AdapterResultStatus.ERROR, error="count must be >= 1"
        )
    if not params.axis_name and not params.axis_point:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Circular pattern requires axis_name or axis_point",
        )

    def _circular_operation() -> SolidWorksFeature:
        adapter._attempt(
            lambda: adapter.currentModel.ClearSelection2(True), default=None
        )
        if params.axis_name:
            if not _select_named_feature(adapter, params.axis_name, 1, False):
                raise Exception(
                    f"Failed to select rotation axis by name: {params.axis_name!r}"
                )
            axis_type = "AXIS"
        else:
            axis_type = _select_reference_point(
                adapter, params.axis_point, 1, ("EDGE", "AXIS", "FACE")
            )
            if axis_type is None:
                raise Exception(
                    f"Failed to select rotation axis at point {params.axis_point} "
                    "(mm); point at a cylindrical face or a linear edge"
                )
        for name in params.features:
            if not _select_named_feature(adapter, name, 4, True):
                raise Exception(f"Failed to select feature to pattern: {name}")

        spacing_rad = math.radians(float(params.angle))
        feature_manager = adapter.currentModel.FeatureManager
        _flag_feature_methods(feature_manager, "IFeatureManager")
        names_before = _feature_names(adapter)
        feature = feature_manager.FeatureCircularPattern5(
            int(params.count),  # Number (incl. seed)
            spacing_rad,  # Spacing (radians; total angle when EqualSpacing)
            False,  # FlipDirection
            "NULL",  # DName
            bool(params.geometry_pattern),  # GeometryPattern
            bool(params.equal_spacing),  # EqualSpacing
            False,  # VaryInstance
            False,  # SyncSubAssemblies
            False,  # BDir2
            False,  # BSymmetric
            0,  # Number2
            0.0,  # Spacing2
            "NULL",  # DName2
            False,  # EqualSpacing2
        )
        feature = _resolve_feature(adapter, feature, names_before)
        if not feature:
            raise Exception("Failed to create circular pattern")

        return SolidWorksFeature(
            name=str(_read_member(feature, "Name")),
            type="CircularPattern",
            id=adapter._get_feature_id(feature),
            parameters={
                "axis_point": params.axis_point,
                "axis_name": params.axis_name,
                "axis_entity": axis_type,
                "features": params.features,
                "count": int(params.count),
                "angle": float(params.angle),
                "equal_spacing": bool(params.equal_spacing),
                "geometry_pattern": bool(params.geometry_pattern),
            },
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation("circular_pattern_feature", _circular_operation),
    )


def _linear_pattern_impl(
    adapter: Any, params: LinearPatternParameters
) -> AdapterResult[SolidWorksFeature]:
    """Linear-pattern named features along a direction via ``FeatureLinearPattern5``.

    The direction reference (typically a linear edge) is selected by a point
    under mark 1; the seed features are selected by name under mark 4.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        params: Linear-pattern parameters.

    Returns:
        AdapterResult[SolidWorksFeature]: ``data.type == "LinearPattern"`` on
        success.

    Raises:
        Exception: Propagated through ``_handle_com_operation`` on selection
            failure or when the pattern feature is not created.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not params.features:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Linear pattern requires at least one feature",
        )
    if params.count < 1:
        return AdapterResult(
            status=AdapterResultStatus.ERROR, error="count must be >= 1"
        )

    def _linear_operation() -> SolidWorksFeature:
        adapter._attempt(
            lambda: adapter.currentModel.ClearSelection2(True), default=None
        )
        dir_type = _select_reference_point(
            adapter, params.direction_point, 1, ("EDGE", "AXIS", "FACE")
        )
        if dir_type is None:
            raise Exception(
                f"Failed to select direction at point {params.direction_point} "
                "(mm); point at a linear edge or axis"
            )
        for name in params.features:
            if not _select_named_feature(adapter, name, 4, True):
                raise Exception(f"Failed to select feature to pattern: {name}")

        feature_manager = adapter.currentModel.FeatureManager
        _flag_feature_methods(feature_manager, "IFeatureManager")
        names_before = _feature_names(adapter)
        feature = feature_manager.FeatureLinearPattern5(
            int(params.count),  # Num1 (incl. seed)
            float(params.spacing) / 1000.0,  # Spacing1 (metres)
            1,  # Num2 (direction 2 unused)
            0.0,  # Spacing2
            False,  # FlipDir1
            False,  # FlipDir2
            "",  # DName1
            "",  # DName2
            False,  # GeometryPattern
            False,  # VaryInstance
            False,  # HasOffset1
            False,  # HasOffset2
            True,  # CtrlByNum1
            True,  # CtrlByNum2
            False,  # FromCentroid1
            False,  # FromCentroid2
            False,  # RevOffset1
            False,  # RevOffset2
            0.0,  # Offset1
            0.0,  # Offset2
            False,  # D2PatternSeedOnly
            False,  # SyncSubAssemblies
        )
        feature = _resolve_feature(adapter, feature, names_before)
        if not feature:
            raise Exception("Failed to create linear pattern")

        return SolidWorksFeature(
            name=str(_read_member(feature, "Name")),
            type="LinearPattern",
            id=adapter._get_feature_id(feature),
            parameters={
                "direction_point": params.direction_point,
                "direction_entity": dir_type,
                "features": params.features,
                "count": int(params.count),
                "spacing": float(params.spacing),
            },
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation("linear_pattern_feature", _linear_operation),
    )


def _shell_impl(
    adapter: Any, params: ShellParameters
) -> AdapterResult[SolidWorksFeature]:
    """Hollow the solid body via ``IModelDoc2::InsertFeatureShell``.

    Faces to remove are selected by a point on each (mark 1).  An empty
    ``face_points`` shells the body closed (no opening).  ``InsertFeatureShell``
    returns ``void``, so the created feature is recovered from the tree.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        params: Shell parameters (thickness, faces to remove, direction).

    Returns:
        AdapterResult[SolidWorksFeature]: ``data.type == "Shell"`` on success.

    Raises:
        Exception: Propagated through ``_handle_com_operation`` on selection
            failure or when the shell feature is not created.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if params.thickness <= 0:
        return AdapterResult(
            status=AdapterResultStatus.ERROR, error="thickness must be positive"
        )

    def _shell_operation() -> SolidWorksFeature:
        adapter._attempt(
            lambda: adapter.currentModel.ClearSelection2(True), default=None
        )
        for point in params.face_points:
            if not _select_by_point(adapter, "FACE", point, 1, True):
                raise Exception(f"Failed to select face at point {point} (mm)")

        # InsertFeatureShell(Thickness metres, Outward) returns void.
        names_before = _feature_names(adapter)
        adapter.currentModel.InsertFeatureShell(
            float(params.thickness) / 1000.0, bool(params.outward)
        )
        feature = _resolve_feature(adapter, None, names_before)
        if not feature:
            raise Exception("Failed to create shell")

        return SolidWorksFeature(
            name=str(_read_member(feature, "Name")),
            type="Shell",
            id=adapter._get_feature_id(feature),
            parameters={
                "thickness": float(params.thickness),
                "face_points": params.face_points,
                "outward": bool(params.outward),
            },
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation("shell", _shell_operation),
    )


def _draft_impl(
    adapter: Any, params: DraftParameters
) -> AdapterResult[SolidWorksFeature]:
    """Apply a neutral-plane draft via ``IFeatureManager::InsertMultiFaceDraft``.

    The neutral plane is selected by name under mark 1; faces to draft are
    selected by a point on each under mark 2.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        params: Draft parameters (angle, neutral plane, faces, direction).

    Returns:
        AdapterResult[SolidWorksFeature]: ``data.type == "Draft"`` on success.

    Raises:
        Exception: Propagated through ``_handle_com_operation`` on selection
            failure or when the draft feature is not created.
    """
    import math

    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not params.neutral_plane:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Draft requires a 'neutral_plane' name",
        )
    if not params.face_points:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Draft requires at least one face point",
        )

    def _draft_operation() -> SolidWorksFeature:
        adapter._attempt(
            lambda: adapter.currentModel.ClearSelection2(True), default=None
        )
        if not _select_named_feature(adapter, params.neutral_plane, 1, True):
            raise Exception(f"Failed to select neutral plane: {params.neutral_plane}")
        for point in params.face_points:
            if not _select_by_point(adapter, "FACE", point, 2, True):
                raise Exception(f"Failed to select face at point {point} (mm)")

        feature_manager = adapter.currentModel.FeatureManager
        _flag_feature_methods(feature_manager, "IFeatureManager")
        names_before = _feature_names(adapter)
        feature = feature_manager.InsertMultiFaceDraft(
            math.radians(float(params.angle)),  # Angle (radians)
            bool(params.flip),  # FlipDir
            False,  # EdgeDraft (face draft)
            0,  # PropType (no propagation)
            False,  # IsStepDraft
            False,  # IsBodyDraft
        )
        feature = _resolve_feature(adapter, feature, names_before)
        if not feature:
            raise Exception("Failed to create draft")

        return SolidWorksFeature(
            name=str(_read_member(feature, "Name")),
            type="Draft",
            id=adapter._get_feature_id(feature),
            parameters={
                "angle": float(params.angle),
                "neutral_plane": params.neutral_plane,
                "face_points": params.face_points,
                "flip": bool(params.flip),
            },
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation("draft", _draft_operation),
    )
