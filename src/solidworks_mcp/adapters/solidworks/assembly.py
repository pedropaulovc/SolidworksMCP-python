"""Assembly component mixin for PyWin32 SolidWorks operations (Phase 7A).

Implements component management on the active assembly document: insertion
(``IAssemblyDoc::AddComponent5`` after an ``ISldWorks::OpenDoc6`` preload,
followed by an exact transform — the ``AddComponent5`` coordinates are
bounding-box relative and only approximate), removal, replacement
(``IAssemblyDoc::ReplaceComponents2``), precise move/rotate
(``IComponent2::SetTransformAndSolve3`` with a client-side composed
transform matrix), fix/float (``IAssemblyDoc::FixComponent`` /
``UnfixComponent``) and local component patterns
(``IFeatureManager::FeatureLinearPattern5`` / ``FeatureCircularPattern5``
— in assemblies these take components under mark 1 and the
direction/axis reference under mark 2, the marks swapped versus part
feature patterns).

Transform convention (``IMathTransform::ArrayData``, 16 doubles): elements
0-8 are a 3x3 rotational sub-matrix whose *rows* are the images of the
component's x/y/z axes in assembly space (i.e. the transpose of the
column-vector rotation matrix), elements 9-11 the translation in metres,
element 12 the scale, 13-15 unused.
"""

from __future__ import annotations

import math
import os
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

from ..base import (
    AdapterResult,
    AdapterResultStatus,
    ComponentCircularPatternParameters,
    ComponentLinearPatternParameters,
    ComponentRefParameters,
    InsertComponentParameters,
    MoveComponentParameters,
    ReplaceComponentParameters,
    RotateComponentParameters,
    SolidWorksFeature,
)
from ..com_variant import null_callout
from .features import (
    _feature_names,
    _flag_feature_methods,
    _read_member,
    _resolve_feature,
    _select_named_feature,
    _select_reference_point,
)

try:
    import pythoncom
    import win32com.client
except ImportError:  # pragma: no cover
    pythoncom = SimpleNamespace()
    win32com = SimpleNamespace(client=SimpleNamespace())

# swReplaceComponentsConfiguration_e
_REPLACE_CONFIG_MATCH_NAME = 0
_REPLACE_CONFIG_MANUALLY_SELECT = 1

_MODEL_EXTENSION_DOC_TYPES = {".sldprt": 1, ".sldasm": 2}  # swDocumentTypes_e


class SolidWorksAssemblyMixin:
    """Expose SolidWorks assembly component methods via mixin-local helpers."""

    async def insert_component(
        self, params: InsertComponentParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _insert_component_impl(self, params)

    async def remove_component(
        self, params: ComponentRefParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _remove_component_impl(self, params)

    async def replace_component(
        self, params: ReplaceComponentParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _replace_component_impl(self, params)

    async def move_component(
        self, params: MoveComponentParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _move_component_impl(self, params)

    async def rotate_component(
        self, params: RotateComponentParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _rotate_component_impl(self, params)

    async def fix_component(
        self, params: ComponentRefParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _set_component_fixed_impl(self, params, fixed=True)

    async def float_component(
        self, params: ComponentRefParameters
    ) -> AdapterResult[dict[str, Any]]:
        return _set_component_fixed_impl(self, params, fixed=False)

    async def pattern_components_linear(
        self, params: ComponentLinearPatternParameters
    ) -> AdapterResult[SolidWorksFeature]:
        return _pattern_components_linear_impl(self, params)

    async def pattern_components_circular(
        self, params: ComponentCircularPatternParameters
    ) -> AdapterResult[SolidWorksFeature]:
        return _pattern_components_circular_impl(self, params)


# ---------------------------------------------------------------------------
# Pure matrix helpers (column-vector convention: v' = R @ v)
# ---------------------------------------------------------------------------


def _mat_mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    """Multiply two 3x3 matrices (``a @ b``)."""
    return [
        [sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)
    ]


def _mat_vec(m: list[list[float]], v: list[float]) -> list[float]:
    """Apply a 3x3 matrix to a column vector (``m @ v``)."""
    return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]


def _euler_xyz_matrix(rotation_deg: list[float]) -> list[list[float]]:
    """Rotation matrix for X-then-Y-then-Z extrinsic Euler angles in degrees.

    Column-vector convention: ``R = Rz @ Ry @ Rx`` maps component-space
    vectors to assembly space, applying the X rotation first.

    Args:
        rotation_deg: ``[rx, ry, rz]`` in degrees.

    Returns:
        list[list[float]]: 3x3 rotation matrix.
    """
    rx, ry, rz = (math.radians(float(a)) for a in rotation_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mat_x = [[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]]
    mat_y = [[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]]
    mat_z = [[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]]
    return _mat_mul(mat_z, _mat_mul(mat_y, mat_x))


def _axis_angle_matrix(axis: list[float], angle_deg: float) -> list[list[float]]:
    """Rodrigues rotation matrix about an axis (column-vector convention).

    Args:
        axis: Rotation axis direction (any length, normalized here).
        angle_deg: Rotation angle in degrees (right-hand rule).

    Returns:
        list[list[float]]: 3x3 rotation matrix.

    Raises:
        Exception: When the axis vector is (near) zero length.
    """
    norm = math.sqrt(sum(float(c) ** 2 for c in axis))
    if norm < 1e-12:
        raise Exception("axis_vector must be non-zero")
    ux, uy, uz = (float(c) / norm for c in axis)
    theta = math.radians(float(angle_deg))
    c, s = math.cos(theta), math.sin(theta)
    t = 1.0 - c
    return [
        [c + ux * ux * t, ux * uy * t - uz * s, ux * uz * t + uy * s],
        [uy * ux * t + uz * s, c + uy * uy * t, uy * uz * t - ux * s],
        [uz * ux * t - uy * s, uz * uy * t + ux * s, c + uz * uz * t],
    ]


def _transform_array(
    rotation: list[list[float]], translation_m: list[float]
) -> list[float]:
    """Build the 16-element ``ArrayData`` for a rotation plus translation.

    The SolidWorks rotational sub-matrix rows are the images of the
    component axes — the transpose of the column-vector ``rotation``.

    Args:
        rotation: 3x3 column-vector rotation matrix (component → assembly).
        translation_m: ``[x, y, z]`` translation in metres.

    Returns:
        list[float]: 16-element transform array (scale 1).
    """
    return [
        rotation[0][0],
        rotation[1][0],
        rotation[2][0],
        rotation[0][1],
        rotation[1][1],
        rotation[2][1],
        rotation[0][2],
        rotation[1][2],
        rotation[2][2],
        translation_m[0],
        translation_m[1],
        translation_m[2],
        1.0,
        0.0,
        0.0,
        0.0,
    ]


# ---------------------------------------------------------------------------
# COM helpers
# ---------------------------------------------------------------------------


def _byref_i4() -> Any:
    """Build a by-reference VT_I4 VARIANT for out-parameters (0 fallback)."""
    variant_ctor = getattr(getattr(win32com, "client", None), "VARIANT", None)
    if not callable(variant_ctor):
        return 0
    vt_byref = int(getattr(pythoncom, "VT_BYREF", 0))
    vt_i4 = int(getattr(pythoncom, "VT_I4", 0))
    return variant_ctor(vt_byref | vt_i4, 0)


def _assembly_title(adapter: Any) -> str:
    """Read the active document's title without its file extension.

    ``SelectByID2`` component names are qualified as ``name@title``, where
    the title omits the ``.SLDASM`` extension for saved documents.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.

    Returns:
        str: Document title, extension stripped.
    """
    model = adapter.currentModel
    title = adapter._attempt(lambda: model.GetTitle(), default=None)
    if not isinstance(title, str) or not title:
        title = str(getattr(model, "Title", "") or "")
    root, ext = os.path.splitext(title)
    if ext.lower() in (".sldasm", ".sldprt"):
        return root
    return title


def _qualify_component(adapter: Any, name: str) -> str:
    """Append the ``@assembly`` qualifier to a component name when missing."""
    if "@" in name:
        return name
    return f"{name}@{_assembly_title(adapter)}"


def _select_component(adapter: Any, name: str, mark: int, append: bool) -> bool:
    """Select an assembly component by name via ``SelectByID2``.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        name: Component name, qualified automatically when needed.
        mark: Selection mark.
        append: ``True`` to add to the current selection set.

    Returns:
        bool: ``True`` when the component selected.
    """
    qualified = _qualify_component(adapter, name)
    return bool(
        adapter._attempt(
            lambda: adapter.currentModel.Extension.SelectByID2(
                qualified, "COMPONENT", 0.0, 0.0, 0.0, append, mark, null_callout(), 0
            ),
            default=False,
        )
    )


def _get_component(adapter: Any, name: str) -> Any:
    """Resolve an ``IComponent2`` via ``IAssemblyDoc::GetComponentByName``.

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        name: Component name; any ``@assembly`` qualifier is stripped.

    Returns:
        Any: The component dispatch (flagged for ``IComponent2``) or ``None``.
    """
    bare = name.split("@", 1)[0]
    model = adapter.currentModel
    _flag_feature_methods(model, "IAssemblyDoc")
    component = adapter._attempt(lambda: model.GetComponentByName(bare), default=None)
    if component:
        _flag_feature_methods(component, "IComponent2")
    return component


def _component_name(adapter: Any, component: Any, fallback: str) -> str:
    """Read a component's path name (``Name2``), with a caller fallback."""
    name = _read_member(component, "Name2")
    if isinstance(name, str) and name:
        return name
    return fallback.split("@", 1)[0]


def _component_transform_array(adapter: Any, component: Any) -> list[float]:
    """Read a component's current 16-element transform array.

    Args:
        adapter: Connected adapter.
        component: ``IComponent2`` dispatch.

    Returns:
        list[float]: ``IMathTransform::ArrayData`` of ``Transform2``.

    Raises:
        Exception: When the transform cannot be read.
    """
    xform = _read_member(component, "Transform2")
    if xform is None:
        raise Exception("Failed to read the component transform")
    array = _read_member(xform, "ArrayData")
    if array is None:
        raise Exception("Failed to read the component transform array")
    values = [float(v) for v in array]
    if len(values) != 16:
        raise Exception(f"Unexpected transform array length: {len(values)}")
    return values


def _create_math_transform(adapter: Any, array16: list[float]) -> Any:
    """Create an ``IMathTransform`` from a 16-element array.

    Args:
        adapter: Connected adapter (for ``ISldWorks::GetMathUtility``).
        array16: Transform array per :func:`_transform_array`.

    Returns:
        Any: The math transform dispatch.

    Raises:
        Exception: When the math utility or transform cannot be created.
    """
    utility = adapter._attempt(lambda: adapter.swApp.GetMathUtility(), default=None)
    if utility is None:
        raise Exception("Failed to get the SolidWorks math utility")
    _flag_feature_methods(utility, "IMathUtility")
    xform = adapter._attempt(
        lambda: utility.CreateTransform([float(v) for v in array16]), default=None
    )
    if xform is None:
        raise Exception("Failed to create the math transform")
    return xform


def _apply_component_transform(
    adapter: Any, component: Any, name: str, array16: list[float]
) -> None:
    """Set a component's transform, solving mates, preserving fixed state.

    ``SetTransformAndSolve3`` refuses to move a fixed component, so a fixed
    one is floated for the move and re-fixed at the new position (the
    first component inserted into an assembly is auto-fixed).

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        component: ``IComponent2`` dispatch.
        name: Component name (for the fix/float selection).
        array16: Target transform array.

    Raises:
        Exception: When the transform cannot be applied.
    """
    model = adapter.currentModel
    _flag_feature_methods(model, "IAssemblyDoc")
    was_fixed = bool(_read_member(component, "IsFixed"))
    if was_fixed:
        if not _select_component(adapter, name, 0, False):
            raise Exception(f"Failed to select component to float: {name!r}")
        adapter._attempt(lambda: model.UnfixComponent())

    xform = _create_math_transform(adapter, array16)
    applied = adapter._attempt(
        lambda: component.SetTransformAndSolve3(xform, True), default=None
    )
    if not applied:
        applied = adapter._attempt(
            lambda: component.SetTransformAndSolve2(xform), default=None
        )

    if was_fixed and _select_component(adapter, name, 0, False):
        adapter._attempt(lambda: model.FixComponent())

    if not applied:
        raise Exception(f"Failed to set the transform of component {name!r}")
    adapter._attempt(lambda: model.EditRebuild3())


def _preload_component_file(adapter: Any, resolved_path: str) -> None:
    """Load a model into memory so ``AddComponent5`` can reference it.

    Args:
        adapter: Connected adapter.
        resolved_path: Absolute path to the ``.sldprt``/``.sldasm`` file.

    Raises:
        Exception: On unsupported extension or load failure.
    """
    doc_type = _MODEL_EXTENSION_DOC_TYPES.get(
        os.path.splitext(resolved_path)[1].lower()
    )
    if doc_type is None:
        raise Exception(
            f"Unsupported component file type: {resolved_path} "
            "(expected .sldprt or .sldasm)"
        )
    app = adapter.swApp
    loaded = adapter._attempt(
        lambda: app.OpenDoc6(resolved_path, doc_type, 1, "", _byref_i4(), _byref_i4()),
        default=None,
    )
    if not loaded:
        loaded = adapter._attempt(
            lambda: app.GetOpenDocumentByName(resolved_path), default=None
        )
    if not loaded:
        raise Exception(f"Failed to preload component file: {resolved_path}")


def _activate_assembly(adapter: Any) -> None:
    """Re-activate the assembly document (best effort).

    ``OpenDoc6`` during the preload makes the component document active in
    the UI; later view-dependent operations need the assembly back.
    """
    title = adapter._attempt(lambda: adapter.currentModel.GetTitle(), default=None)
    if not title:
        return
    adapter._attempt(
        lambda: adapter.swApp.ActivateDoc3(title, False, 2, _byref_i4()),
        default=None,
    )


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------


def _insert_component_impl(
    adapter: Any, params: InsertComponentParameters
) -> AdapterResult[dict[str, Any]]:
    """Insert a component via ``IAssemblyDoc::AddComponent5``.

    The file is preloaded with ``OpenDoc6`` (an ``AddComponent5``
    requirement), inserted at the origin, then positioned exactly with a
    composed transform — the ``AddComponent5`` X/Y/Z are bounding-box
    relative and only approximate per the API remarks.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: File, position (mm), rotation (deg XYZ), configuration.

    Returns:
        AdapterResult[dict[str, Any]]: Inserted component name, referenced
        configuration and pose, or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not params.file_path.strip():
        return AdapterResult(
            status=AdapterResultStatus.ERROR, error="file_path is required"
        )
    if len(params.position) != 3 or len(params.rotation) != 3:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="position and rotation must each be [x, y, z]",
        )

    def _insert_operation() -> dict[str, Any]:
        resolved = os.path.abspath(params.file_path)
        if not os.path.isfile(resolved):
            raise Exception(f"Component file not found: {resolved}")
        _preload_component_file(adapter, resolved)

        model = adapter.currentModel
        _flag_feature_methods(model, "IAssemblyDoc")
        component = model.AddComponent5(
            resolved,
            0,  # swAddComponentConfigOptions_CurrentSelectedConfig
            "",  # NewConfigName (unused for this option)
            bool(params.configuration),  # UseConfigForPartReferences
            params.configuration or "",
            0.0,
            0.0,
            0.0,
        )
        if not component:
            raise Exception(
                f"AddComponent5 failed for {resolved} (the file must load "
                "cleanly and the configuration must exist)"
            )
        _flag_feature_methods(component, "IComponent2")
        name = _component_name(adapter, component, os.path.basename(resolved))

        rotation = _euler_xyz_matrix(params.rotation)
        translation_m = [float(c) / 1000.0 for c in params.position]
        _apply_component_transform(
            adapter, component, name, _transform_array(rotation, translation_m)
        )
        _activate_assembly(adapter)

        return {
            "name": name,
            "file_path": resolved,
            "configuration": str(
                _read_member(component, "ReferencedConfiguration") or ""
            ),
            "position": [float(c) for c in params.position],
            "rotation": [float(c) for c in params.rotation],
            "fixed": bool(_read_member(component, "IsFixed")),
        }

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("insert_component", _insert_operation),
    )


def _remove_component_impl(
    adapter: Any, params: ComponentRefParameters
) -> AdapterResult[dict[str, Any]]:
    """Delete a component via selection plus ``DeleteSelection2``.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Component name.

    Returns:
        AdapterResult[dict[str, Any]]: Removal confirmation or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not params.name.strip():
        return AdapterResult(status=AdapterResultStatus.ERROR, error="name is required")

    def _remove_operation() -> dict[str, Any]:
        model = adapter.currentModel
        component = _get_component(adapter, params.name)
        if component is None:
            raise Exception(f"Component not found: {params.name!r}")
        name = _component_name(adapter, component, params.name)

        adapter._attempt(lambda: model.ClearSelection2(True), default=None)
        if not _select_component(adapter, name, 0, False):
            raise Exception(f"Failed to select component: {name!r}")
        deleted = adapter._attempt(
            lambda: model.Extension.DeleteSelection2(0), default=False
        )
        if not deleted:
            adapter._attempt(lambda: model.EditDelete(), default=None)
        if _get_component(adapter, name) is not None:
            raise Exception(f"Component {name!r} is still present after delete")
        return {"name": name, "removed": True}

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("remove_component", _remove_operation),
    )


def _replace_component_impl(
    adapter: Any, params: ReplaceComponentParameters
) -> AdapterResult[dict[str, Any]]:
    """Replace a component via ``IAssemblyDoc::ReplaceComponents2``.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Component, replacement file and options.

    Returns:
        AdapterResult[dict[str, Any]]: Replacement summary or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not params.name.strip():
        return AdapterResult(status=AdapterResultStatus.ERROR, error="name is required")
    if not params.file_path.strip():
        return AdapterResult(
            status=AdapterResultStatus.ERROR, error="file_path is required"
        )

    def _replace_operation() -> dict[str, Any]:
        resolved = os.path.abspath(params.file_path)
        if not os.path.isfile(resolved):
            raise Exception(f"Replacement file not found: {resolved}")
        model = adapter.currentModel
        component = _get_component(adapter, params.name)
        if component is None:
            raise Exception(f"Component not found: {params.name!r}")
        name = _component_name(adapter, component, params.name)

        adapter._attempt(lambda: model.ClearSelection2(True), default=None)
        if not _select_component(adapter, name, 0, False):
            raise Exception(f"Failed to select component: {name!r}")
        _flag_feature_methods(model, "IAssemblyDoc")
        config_choice = (
            _REPLACE_CONFIG_MANUALLY_SELECT
            if params.configuration
            else _REPLACE_CONFIG_MATCH_NAME
        )
        replaced = model.ReplaceComponents2(
            resolved,
            params.configuration,
            bool(params.replace_all),
            config_choice,
            bool(params.reattach_mates),
        )
        if not replaced:
            raise Exception(
                f"ReplaceComponents2 failed for {name!r} -> {resolved} (the "
                "component must be top-level and the replacement file name "
                "must differ from the replaced one)"
            )
        return {
            "name": name,
            "file_path": resolved,
            "configuration": params.configuration,
            "replace_all": bool(params.replace_all),
            "reattach_mates": bool(params.reattach_mates),
        }

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("replace_component", _replace_operation),
    )


def _move_component_impl(
    adapter: Any, params: MoveComponentParameters
) -> AdapterResult[dict[str, Any]]:
    """Move a component, preserving its rotation.

    Reads the current transform, rewrites the translation (absolute target
    or relative delta) and applies it with the mate solver.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Component and target position in millimetres.

    Returns:
        AdapterResult[dict[str, Any]]: Resulting position or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not params.name.strip():
        return AdapterResult(status=AdapterResultStatus.ERROR, error="name is required")
    if len(params.position) != 3:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="position must be [x, y, z] in millimetres",
        )

    def _move_operation() -> dict[str, Any]:
        component = _get_component(adapter, params.name)
        if component is None:
            raise Exception(f"Component not found: {params.name!r}")
        name = _component_name(adapter, component, params.name)

        array = _component_transform_array(adapter, component)
        position_m = [float(c) / 1000.0 for c in params.position]
        if params.relative:
            array[9:12] = [array[9 + i] + position_m[i] for i in range(3)]
        else:
            array[9:12] = position_m
        _apply_component_transform(adapter, component, name, array)
        return {
            "name": name,
            "position": [v * 1000.0 for v in array[9:12]],
            "relative": bool(params.relative),
        }

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("move_component", _move_operation),
    )


def _rotate_component_impl(
    adapter: Any, params: RotateComponentParameters
) -> AdapterResult[dict[str, Any]]:
    """Rotate a component about an axis in assembly space.

    Composes the rotation onto the current transform client-side: the
    rotational rows (axis images) and the translation are both rotated
    about ``axis_point``, then the result is applied with the mate solver.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Component, axis (point in mm, direction) and angle (deg).

    Returns:
        AdapterResult[dict[str, Any]]: Rotation summary or error.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not params.name.strip():
        return AdapterResult(status=AdapterResultStatus.ERROR, error="name is required")
    if len(params.axis_vector) != 3 or len(params.axis_point) != 3:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="axis_vector and axis_point must each be [x, y, z]",
        )

    def _rotate_operation() -> dict[str, Any]:
        component = _get_component(adapter, params.name)
        if component is None:
            raise Exception(f"Component not found: {params.name!r}")
        name = _component_name(adapter, component, params.name)

        array = _component_transform_array(adapter, component)
        rotation = _axis_angle_matrix(params.axis_vector, params.angle)
        rows = [array[0:3], array[3:6], array[6:9]]
        new_rows = [_mat_vec(rotation, row) for row in rows]
        center_m = [float(c) / 1000.0 for c in params.axis_point]
        offset = [array[9 + i] - center_m[i] for i in range(3)]
        rotated_offset = _mat_vec(rotation, offset)
        translation = [rotated_offset[i] + center_m[i] for i in range(3)]

        new_array = (
            new_rows[0]
            + new_rows[1]
            + new_rows[2]
            + translation
            + [array[12]]
            + [0.0, 0.0, 0.0]
        )
        _apply_component_transform(adapter, component, name, new_array)
        return {
            "name": name,
            "angle": float(params.angle),
            "axis_vector": [float(c) for c in params.axis_vector],
            "axis_point": [float(c) for c in params.axis_point],
            "position": [v * 1000.0 for v in translation],
        }

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation("rotate_component", _rotate_operation),
    )


def _set_component_fixed_impl(
    adapter: Any, params: ComponentRefParameters, fixed: bool
) -> AdapterResult[dict[str, Any]]:
    """Fix or float a component via ``FixComponent``/``UnfixComponent``.

    Both APIs act on the current selection and return nothing, so the
    resulting state is verified by reading ``IComponent2::IsFixed`` back.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Component name.
        fixed: ``True`` to fix, ``False`` to float.

    Returns:
        AdapterResult[dict[str, Any]]: Resulting fixed state or error.
    """
    operation = "fix_component" if fixed else "float_component"
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not params.name.strip():
        return AdapterResult(status=AdapterResultStatus.ERROR, error="name is required")

    def _fixed_operation() -> dict[str, Any]:
        model = adapter.currentModel
        component = _get_component(adapter, params.name)
        if component is None:
            raise Exception(f"Component not found: {params.name!r}")
        name = _component_name(adapter, component, params.name)

        adapter._attempt(lambda: model.ClearSelection2(True), default=None)
        if not _select_component(adapter, name, 0, False):
            raise Exception(f"Failed to select component: {name!r}")
        _flag_feature_methods(model, "IAssemblyDoc")
        if fixed:
            adapter._attempt(lambda: model.FixComponent(), default=None)
        else:
            adapter._attempt(lambda: model.UnfixComponent(), default=None)

        resulting = bool(_read_member(component, "IsFixed"))
        if resulting != fixed:
            state = "fixed" if fixed else "floating"
            raise Exception(f"Component {name!r} did not become {state}")
        return {"name": name, "fixed": resulting}

    return cast(
        AdapterResult[dict[str, Any]],
        adapter._handle_com_operation(operation, _fixed_operation),
    )


def _select_pattern_components(adapter: Any, components: list[str]) -> None:
    """Select pattern seed components under mark 1 (cleared selection).

    Args:
        adapter: Connected adapter with a non-``None`` ``currentModel``.
        components: Component names.

    Raises:
        Exception: When any component fails to select.
    """
    adapter._attempt(lambda: adapter.currentModel.ClearSelection2(True), default=None)
    for name in components:
        if not _select_component(adapter, name, 1, True):
            raise Exception(f"Failed to select component to pattern: {name!r}")


def _pattern_components_linear_impl(
    adapter: Any, params: ComponentLinearPatternParameters
) -> AdapterResult[SolidWorksFeature]:
    """Local linear component pattern via ``FeatureLinearPattern5``.

    In assemblies the selection marks are swapped versus part feature
    patterns: components under mark 1, the direction reference under
    mark 2.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Seeds, count, spacing and direction reference.

    Returns:
        AdapterResult[SolidWorksFeature]: ``data.type == "LocalLinearPattern"``
        on success.
    """
    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not params.components:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Component pattern requires at least one component",
        )
    if params.count < 1:
        return AdapterResult(
            status=AdapterResultStatus.ERROR, error="count must be >= 1"
        )
    if not params.direction_name and not params.direction_point:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Component pattern requires direction_name or direction_point",
        )

    def _linear_operation() -> SolidWorksFeature:
        _select_pattern_components(adapter, params.components)
        if params.direction_name:
            if not _select_named_feature(adapter, params.direction_name, 2, True):
                raise Exception(
                    f"Failed to select direction by name: {params.direction_name!r}"
                )
            direction_type = "FEATURE"
        else:
            direction_type = _select_reference_point(
                adapter, params.direction_point, 2, ("EDGE", "AXIS", "FACE")
            )
            if direction_type is None:
                raise Exception(
                    f"Failed to select direction at point {params.direction_point} "
                    "(mm); point at a linear edge or axis"
                )

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
            raise Exception("Failed to create linear component pattern")

        return SolidWorksFeature(
            name=str(_read_member(feature, "Name")),
            type="LocalLinearPattern",
            id=adapter._get_feature_id(feature),
            parameters={
                "components": params.components,
                "count": int(params.count),
                "spacing": float(params.spacing),
                "direction_name": params.direction_name,
                "direction_point": params.direction_point,
                "direction_entity": direction_type,
            },
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation("pattern_components_linear", _linear_operation),
    )


def _pattern_components_circular_impl(
    adapter: Any, params: ComponentCircularPatternParameters
) -> AdapterResult[SolidWorksFeature]:
    """Local circular component pattern via ``FeatureCircularPattern5``.

    In assemblies the selection marks are swapped versus part feature
    patterns: components under mark 1, the axis reference under mark 2.

    Args:
        adapter: A fully connected ``PyWin32Adapter``.
        params: Seeds, count, angle and axis reference.

    Returns:
        AdapterResult[SolidWorksFeature]: ``data.type ==
        "LocalCircularPattern"`` on success.
    """
    import math as _math

    if not adapter.currentModel:
        return AdapterResult(status=AdapterResultStatus.ERROR, error="No active model")
    if not params.components:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Component pattern requires at least one component",
        )
    if params.count < 1:
        return AdapterResult(
            status=AdapterResultStatus.ERROR, error="count must be >= 1"
        )
    if not params.axis_name and not params.axis_point:
        return AdapterResult(
            status=AdapterResultStatus.ERROR,
            error="Component pattern requires axis_name or axis_point",
        )

    def _circular_operation() -> SolidWorksFeature:
        _select_pattern_components(adapter, params.components)
        if params.axis_name:
            if not _select_named_feature(adapter, params.axis_name, 2, True):
                raise Exception(
                    f"Failed to select rotation axis by name: {params.axis_name!r}"
                )
            axis_type = "AXIS"
        else:
            axis_type = _select_reference_point(
                adapter, params.axis_point, 2, ("EDGE", "AXIS", "FACE")
            )
            if axis_type is None:
                raise Exception(
                    f"Failed to select rotation axis at point {params.axis_point} "
                    "(mm); point at a cylindrical face or a linear edge"
                )

        spacing_rad = _math.radians(float(params.angle))
        feature_manager = adapter.currentModel.FeatureManager
        _flag_feature_methods(feature_manager, "IFeatureManager")
        names_before = _feature_names(adapter)
        feature = feature_manager.FeatureCircularPattern5(
            int(params.count),  # Number (incl. seed)
            spacing_rad,  # Spacing (radians; total angle when EqualSpacing)
            False,  # FlipDirection
            "NULL",  # DName
            False,  # GeometryPattern (component patterns copy bodies anyway)
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
            raise Exception("Failed to create circular component pattern")

        return SolidWorksFeature(
            name=str(_read_member(feature, "Name")),
            type="LocalCircularPattern",
            id=adapter._get_feature_id(feature),
            parameters={
                "components": params.components,
                "count": int(params.count),
                "angle": float(params.angle),
                "equal_spacing": bool(params.equal_spacing),
                "axis_name": params.axis_name,
                "axis_point": params.axis_point,
                "axis_entity": axis_type,
            },
            properties={"created": datetime.now().isoformat()},
        )

    return cast(
        AdapterResult[SolidWorksFeature],
        adapter._handle_com_operation(
            "pattern_components_circular", _circular_operation
        ),
    )
