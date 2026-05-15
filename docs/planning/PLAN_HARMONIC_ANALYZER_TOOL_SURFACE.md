# PLAN: MCP Tool Surface to Complete the Michelson Harmonic Analyzer

**Status:** Proposal — pending upstream review
**Author:** Pedro Paulo Vezza Campos (`pedro@vezza.com.br`)
**Date:** 2026-05-15
**Scope:** New tool implementations only; no protocol or adapter-architecture changes.

## Context

This plan proposes a concrete, phased expansion of the `solidworks_mcp`
tool surface, motivated by a real consumer project: a faithful recreation
of Albert Michelson's 20-channel mechanical harmonic analyzer
(a Fourier-synthesis machine — crank → cone-gear set → cylinder gears →
eccentric cams → rocker arms → amplitude bars → summing-lever stack →
pen/magnifier → platen). The consumer project currently drives SolidWorks
through a hand-rolled C# Interop layer; the goal is to make `solidworks_mcp`
itself capable enough that the entire build can be driven from MCP tool
calls alone.

The harmonic analyzer is useful as a forcing function because it exercises
the long tail of CAD operations a real mechanism needs: assembly mates
(including mechanical gear/cam mates), feature-level patterns for the
20-channel array, reference geometry for laying out parallel channels,
parametric variant generation (20 cone gears differing only in tooth
count), measurement, materials, and BOMs. Most of these are absent today.

### Current coverage (verified by reading the registered tools)

Strong:
- Sketching primitives (`sketching.py` — lines, arcs, circles, splines,
  centerlines, polygons, ellipses, constraints, dimensions, 2D patterns,
  mirror, offset).
- Basic part features (`modeling.py` — extrude, revolve, cut-extrude,
  fillet, dimension get/set).
- Drawings (`drawing.py` — views, sections, details, dimensions,
  annotations, technical drawing pipeline).
- Exports (`export.py` — STEP, IGES, STL, PDF, DWG, image, batch).
- Mass properties + interference (`analysis.py` —
  `calculate_mass_properties`, `get_mass_properties`, `check_interference`).
- Design tables (`automation.py` — `manage_design_table`).

Gaps the harmonic analyzer requires:
- **Assembly surface — entirely missing.** No component insertion,
  no mates of any kind, no component patterns.
- **Feature-level 3D ops — mostly missing.** No chamfer, no 3D mirror,
  no feature patterns (circular or linear), no shell/draft/rib, no
  hole wizard. `CreateSweepInput` and `CreateLoftInput` schemas exist
  in `modeling.py:213-248` but are **not registered** with `@mcp.tool`.
- **Reference geometry — entirely missing.** No planes, axes,
  reference points, or coordinate systems.
- **Parametric variant generation — partial.** Design tables exist but
  there is no `create_configuration`, no `set_global_variable`, no
  `create_equation_driven_curve`. The last is essential for involute
  gear teeth and sine-driven cam profiles.
- **Measurement — missing.** No dimensional measure tool.
- **Manufacturing prep — missing.** No `apply_material`, `add_thread`,
  or BOM generation.

### Design decisions baked into this plan

1. **Sequencing: parts-first, assembly last.** Every part type the
   mechanism uses must be modelable in isolation before assembly tools
   are introduced. This matches the natural build order and limits
   blast radius per phase.
2. **First-class `create_equation_driven_curve`.** The alternative — have
   the agent compute parametric points client-side and feed them to
   `add_spline` — works but produces a non-parametric curve in
   SolidWorks; changing tooth count would require regenerating points.
   A native equation-driven curve keeps the SW model parametric end-to-end.
3. **KCL is reference geometry only.** The harmonic analyzer repo
   contains KCL files for several parts; those are dimension references,
   not a translation target. No MCP tool reads or writes KCL.
4. **Out of scope:** motion study, FEA, simulation. Modeling + assembly +
   drawings + export only.

## Existing infrastructure to reuse

- **Registration pattern**: `register_<domain>_tools(mcp, adapter, config)`
  in `src/solidworks_mcp/tools/<domain>.py`, wired in
  `src/solidworks_mcp/tools/__init__.py:9-48`.
- **Adapter boundary**: `PyWin32Adapter` in
  `src/solidworks_mcp/adapters/pywin32_adapter.py`. All COM work is
  submitted to its `ComExecutor` — late-binding `dynamic.Dispatch` and
  `sw_type_info.flag_methods` are mandatory (see `CLAUDE.md`
  "COM threading architecture").
- **Mock parity**: `src/solidworks_mcp/adapters/mock_adapter.py` mirrors
  every real adapter method, enabling unit-test runs on Linux CI.
- **Input-schema pattern**: Pydantic `BaseModel` with `model_post_init`
  validation; see `CreateExtrusionInput`, `AddFilletInput` in
  `modeling.py`.
- **Response shape**: `{status, message, execution_time, data}` —
  preserved across every new tool.
- **Existing tools to compose, not reimplement**:
  `calculate_mass_properties`, `get_mass_properties`, `check_interference`
  (`analysis.py:127,225,246`); `manage_design_table`
  (`automation.py:505`); `add_spline` (`sketching.py:803`).

## Phase 0 — Wire existing stubs

Estimated effort: 1 day.

`CreateSweepInput` and `CreateLoftInput` are already defined in
`modeling.py:213-248` but have no corresponding `@mcp.tool` registration.
Wire them and add adapter methods.

Touches: `tools/modeling.py`, `adapters/pywin32_adapter.py`,
`adapters/mock_adapter.py`.

- [ ] Register `create_sweep` — open sketch as profile + path sketch;
  `IFeatureManager.InsertProtrusionSwept4` (twist params optional).
- [ ] Register `create_loft` — multiple profile sketches + optional
  guide curves; `IFeatureManager.InsertProtrusionBlend2`.

Verification: mock returns the standard response shape; pytest covers
a single-profile-pair loft (cone-gear-like tapered bevel).

## Phase 1 — Part-level feature primitives

Estimated effort: 1-2 weeks.

Needed before any harmonic-analyzer part beyond simple bars and discs
can be modeled.

Touches: `tools/modeling.py`, adapters.

- [ ] `add_chamfer` — counterpart to existing `add_fillet`;
  `IFeatureManager.InsertFeatureChamfer`.
- [ ] `hole_wizard` — `IFeatureManager.HoleWizard5`. Replaces the
  cut-extrude workaround for fastener and bearing bores. Inputs: hole
  type (simple, counterbore, countersink, tap), standard, size, depth,
  location face + sketch point.
- [ ] `mirror_feature` — 3D mirror across a reference plane;
  `IFeatureManager.InsertMirrorFeature2`. Distinct from existing
  sketch-level `sketch_mirror`.
- [ ] `circular_pattern_feature` — `IFeatureManager.FeatureCircularPattern5`.
  Needed for cone-gear teeth at feature level and fastener-hole rings on
  the platen.
- [ ] `linear_pattern_feature` — `IFeatureManager.FeatureLinearPattern5`.
  Needed for repeated bores along the rocker-arm support rails.
- [ ] `shell` — `IFeatureManager.InsertFeatureShell2`.
- [ ] `draft` — `IFeatureManager.InsertDraft`. Useful for the cone-gear
  blank.
- [ ] `rib` — `IFeatureManager.InsertRib`. Optional for this mechanism.

Verification: for each tool, a mock-adapter unit test plus one
live-integration test in `tests/test_live_sw_regression.py` gated by
`SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`.

## Phase 2 — Reference geometry

Estimated effort: 3-5 days.

Required to lay out the 20-channel array (datum planes per channel,
axes through gear shafts).

Touches: `tools/modeling.py` (or new `tools/reference_geometry.py` if
the file grows large), adapters.

- [ ] `create_plane` — modes: offset-from-plane, angled-to-plane,
  three-point, parallel-through-point. `IFeatureManager.InsertRefPlane`.
- [ ] `create_axis` — modes: edge, two-points, intersection-of-planes,
  cylindrical-face. `IFeatureManager.InsertAxis2`.
- [ ] `create_reference_point` — modes: vertex, midpoint, arc-center,
  on-curve, intersection. `IFeatureManager.InsertReferencePoint`.
- [ ] `create_coordinate_system` —
  `IFeatureManager.CreateCoordinateSystem`.

Verification: build a 20-axis fixture (planes offset 1" apart) in
mock and live.

## Phase 3 — Parametric variant generation

Estimated effort: 1 week.

The 20 cone gears differ only in tooth count (6, 12, 18, … 120).
Without this phase, the part must be regenerated 20 times. With it:
one part file, 20 configurations.

Touches: `tools/modeling.py` (or new `tools/parametrics.py`), adapters.

- [ ] `create_equation_driven_curve` — sketch-level parametric curve
  from `x(t), y(t)` and `t ∈ [t0, t1]`.
  `ISketchManager.CreateEquationDrivenCurve2`. Critical for involute
  gear teeth (polar form) and sine-driven harmonic cam profiles.
- [ ] `set_global_variable` — add or update a global in
  `EquationManager`. `IEquationMgr.Add3` / `SetEquation`. Drives
  gear-parameter tables (module, pressure angle, tooth count).
- [ ] `create_equation` — derived equations, e.g.
  `"D1@Sketch1" = "ToothCount" / "DiametralPitch"`.
- [ ] `create_configuration` — `IConfigurationManager.AddConfiguration2`.
- [ ] `set_active_configuration` — `IModelDoc2.ShowConfiguration2`.
- [ ] `list_configurations` — read-only helper.

Existing tool to compose: `manage_design_table` (`automation.py:505`)
for bulk variant tables. The new tools above complement it for
single-variable parametrics.

Verification: model one cone-gear part with a `ToothCount` global;
add 20 configurations programmatically; rebuild each and verify
`get_mass_properties` returns 20 monotonically increasing volumes.

## Phase 4 — Manufacturing prep

Estimated effort: 3-5 days. Can be parallelized with Phase 3.

Touches: new `tools/manufacturing.py`, adapters; register in
`tools/__init__.py`.

- [ ] `apply_material` — `IPartDoc.SetMaterialPropertyName2`. Required
  for `get_mass_properties` to return correct mass.
- [ ] `add_thread` — cosmetic or modeled;
  `IFeatureManager.InsertCosmeticThread2`.
- [ ] `create_bom` — assembly BOM table;
  `IModelDocExtension.InsertBomTable2`.
- [ ] `export_bom_csv` — read BOM rows and emit CSV. Reuse the
  export-tool plumbing in `tools/export.py`.

Verification: assign a known material to a sample part; mass-property
mass matches manual calculation within 1%.

## Phase 5 — Measurement

Estimated effort: 1-2 days.

`check_interference` and `get_mass_properties` exist; dimensional
measurement does not.

Touches: `tools/analysis.py`, adapters.

- [ ] `measure` — modes: point-to-point distance, edge length, face
  area, angle-between-edges, point-to-plane distance, dihedral angle.
  `IMeasure` interface via `IModelDocExtension.CreateMeasure`.

Verification: live test — extrude a known block, measure each edge,
confirm tolerance < 1e-6 m.

## Phase 6 — Assembly surface

Estimated effort: 2 weeks. Ships last, after every part type is
modelable.

Touches: new `tools/assembly.py`, adapters; register in
`tools/__init__.py`.

### 6A — Component management (3-5 days)

- [ ] `insert_component` — `IAssemblyDoc.AddComponent5`. Inputs:
  component file path, optional config name, target position.
- [ ] `remove_component`, `replace_component`.
- [ ] `move_component` — `IAssemblyDoc.MoveComponent`.
- [ ] `rotate_component` — `IAssemblyDoc.RotateComponent`.
- [ ] `fix_component`, `float_component` — toggle the grounded flag.
- [ ] `pattern_components_linear`, `pattern_components_circular` —
  `IAssemblyDoc.FeatureLinearPattern` / `FeatureCircularPattern`. Bulk
  instancing for the 20-channel array, the cylinder-gear row, fastener
  rings.

### 6B — Standard mates (1 week)

- [ ] `add_mate` — single tool with `mate_type` enum: coincident,
  concentric, perpendicular, parallel, tangent, distance, angle, lock,
  width. `IAssemblyDoc.AddMate3`. Inputs: two component-qualified
  entity selections, mate type, optional value, optional alignment flag.
- [ ] `delete_mate`, `list_mates`, `suppress_mate`.

### 6C — Mechanical mates (3-5 days)

- [ ] `add_gear_mate` — `IAssemblyDoc.AddMate3` with `swMateGEAR`.
  Required for the 4:1 crank reduction and every cone/cylinder gear
  pair.
- [ ] `add_cam_follower_mate` — `swMateCAMFOLLOWER`. Drives the
  rocker-arm follower against the eccentric cam.
- [ ] `add_rack_pinion_mate`, `add_screw_mate` — likely unused for this
  mechanism but cheap to include alongside.

Verification: build a 2-part assembly (shaft + cone gear), apply
concentric + coincident mates plus a gear mate to a second cone gear;
rotate the input via `move_component`; confirm the output rotates by
the inverse ratio. Add a 20-channel fixture test that inserts 20 cone
gears via `pattern_components_circular`.

## Critical files modified

- `src/solidworks_mcp/tools/modeling.py` — Phases 0, 1, 2, 3 additions.
- `src/solidworks_mcp/tools/analysis.py` — Phase 5 (`measure`).
- `src/solidworks_mcp/tools/manufacturing.py` — Phase 4 (new file).
- `src/solidworks_mcp/tools/assembly.py` — Phase 6 (new file).
- `src/solidworks_mcp/tools/__init__.py` — register new tool modules
  (currently lines 9-48).
- `src/solidworks_mcp/adapters/pywin32_adapter.py` — adapter methods
  for every new tool.
- `src/solidworks_mcp/adapters/mock_adapter.py` — mock parity for
  every new adapter method.
- `tests/test_live_sw_regression.py` — live integration coverage.
- `tests/` — new unit tests per phase against `mock_adapter`.

## End-to-end verification

Reachable only after all phases ship.

1. `.\dev-commands.ps1 dev-test` (mock-only) — every new tool has a
   green unit test, including on Linux CI.
2. `.\dev-commands.ps1 dev-test-full` on Windows with SolidWorks
   attached — every new tool has a live regression test under
   `tests/test_live_sw_regression.py`.
3. Drive a complete harmonic-analyzer build from MCP tool calls only
   (no manual SolidWorks work, no C# Interop):
   - **After Phase 1+2:** every distinct part type (amplitude bar,
     eccentric cam, summing lever, rocker-arm support, harmonic base,
     spur gear) modeled via MCP only.
   - **After Phase 3:** one cone-gear part with a `ToothCount` global
     and 20 configurations; `get_mass_properties` returns 20 distinct
     monotonically increasing masses.
   - **After Phase 4:** materials applied, BOM CSV exported.
   - **After Phase 5:** measurement-based verification gate in the
     agent loop catches dimensional drift before machining.
   - **After Phase 6:** assembly file with crank, cone-gear set,
     cylinder-gear set, and one full channel (cam → rocker arm →
     amplitude bar → summing lever); the gear mate visibly transmits
     motion when the crank is rotated; `check_interference` reports
     zero between channels.
4. KCL files referenced for geometric values only; no MCP tool reads
   or writes KCL.

## Open questions for upstream

1. **File organization.** Should reference geometry live in
   `modeling.py` or a new `reference_geometry.py`? Same question for
   parametrics (Phase 3) — in `modeling.py` or a new `parametrics.py`?
   Either works; the project's preference governs.
2. **Hole wizard standard coverage.** `HoleWizard5` supports many
   standards (ANSI, ISO, JIS, BSI, etc.). For initial scope, propose
   ANSI inch + ISO metric only; expand on request.
3. **Mock-adapter fidelity for mates.** The mock currently returns
   canned responses. For assembly mates, should the mock track
   inserted components and applied mates in an in-memory model to
   enable richer test assertions, or stay stateless? Stateless is
   simpler; stateful enables more realistic agent-loop tests.
4. **Versioning.** These additions roughly double the tool count
   (~22 tools across 6 phases). Worth a minor-version bump on first
   phase merge, or wait until Phase 6 lands? Suggest minor bump per
   phase for visibility.
