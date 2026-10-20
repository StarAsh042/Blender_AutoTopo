"""Blender property definitions for AutoTopo.

The engine *parameter* declarations (``qw_*`` / ``ar_*`` / ``qf_*``) must
be spelled out literally on :class:`AutoTopoProperties` because Blender's
``PropertyGroup`` only converts ``bpy.props.*`` declarations into real RNA
properties when they appear in a genuine module-level ``class`` statement
body — runtime ``setattr`` / ``type()`` / ``exec`` all leave them as
un-converted ``_PropertyDeferred`` placeholders.

The *panel* and *operator* are still fully registry-driven: they read the
engine's :class:`SettingSpec` list and draw / read each property by its
key, so adding an engine's behaviour needs no panel changes. These literal
definitions must stay in sync with the matching ``SettingSpec`` defaults in
``engines/*_engine.py`` (the spec is the source of truth for the
recommended default and range).
"""

import bpy
from bpy.props import (
    IntProperty,
    FloatProperty,
    BoolProperty,
    EnumProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


class AutoTopoProperties(PropertyGroup):
    """Property group for AutoTopo parameters."""

    # === 引擎选择 ===

    engine: EnumProperty(
        name="Algorithm Engine",
        description="Retopology algorithm engine",
        items=[
            ('autoremesher', "AutoRemesher (fast quad)",
             "AutoRemesher (MIT): isotropic remeshing + parameterization + "
             "quad extraction; very high quad ratio and fast"),
            ('quadriflow', "QuadriFlow (field-aligned)",
             "QuadriFlow (MIT, SIGGRAPH 2020): direction-field alignment + "
             "global parameterization; even layout, scales to high face counts"),
            ('quadwild', "QuadWild (high quality)",
             "QuadWild (SIGGRAPH Asia 2019): cross-field quantization + ILP "
             "final quadrangulation; clean interior quads, a few transition "
             "triangles at singularities"),
        ],
        default='autoremesher',
    )

    # === 共享基础参数（非引擎独占） ===

    target_face_count: IntProperty(
        name="Target Face Count",
        description="Target number of faces in the output mesh",
        default=2000,
        min=100,
        max=100000,
        soft_min=200,
        soft_max=20000,
    )

    sharp_angle_threshold: FloatProperty(
        name="Sharp Edge Angle",
        description="Edges whose interior dihedral angle is below this value "
                    "are treated as sharp (flat = 180, right angle = 90; larger "
                    "values preserve more sharp edges). Unit: degrees",
        default=90.0,
        min=10.0,
        max=180.0,
        precision=1,
    )

    # === 内部状态（只读展示，不暴露给用户编辑） ===

    is_processing: BoolProperty(
        name="Processing",
        description="Whether retopology is currently running",
        default=False,
    )

    status_message: StringProperty(
        name="Status",
        description="Current status message",
        default="",
    )

    # NOTE: 内部状态，仅供面板只读展示（panels.py 用 layout.progress()
    # 渲染，不用 box.prop()），用户不可编辑/拖动。
    progress: FloatProperty(
        name="Progress",
        description="Current progress (read-only)",
        default=0.0,
        min=0.0,
        max=100.0,
        subtype='PERCENTAGE',
    )

    step_name: StringProperty(
        name="Current Step",
        description="Name of the step currently running",
        default="",
    )

    last_result_info: StringProperty(
        name="Last Result",
        description="Result information from the last retopology run",
        default="",
    )

    # === QuadWild 参数（与 engines/quadwild_engine.py 的 SettingSpec 同步） ===

    qw_keep_sharp: BoolProperty(
        name="Keep Sharp Edges", default=True,
        description="Detect and preserve sharp edge features during retopology "
                    "(disable to treat the surface as fully smooth)")
    qw_tolerance: FloatProperty(
        name="Face Count Tolerance (%)", default=10.0, min=1.0, max=20.0, precision=1,
        description="Allowed deviation of the output face count from the target "
                    "(percent); exceeding it reruns quadrangulation")
    qw_adaptive_density: BoolProperty(
        name="Adaptive Density", default=True,
        description="Distribute faces by detail: denser in damaged/high-curvature "
                    "areas, sparser on flat regions")
    qw_isometry: BoolProperty(
        name="Isometry Constraint", default=True,
        description="Preserve local isometry and reduce stretching (paper default: on)")
    qw_hard_parity: BoolProperty(
        name="Hard Parity Constraint", default=True,
        description="Enforce quad parity constraints to reduce non-quad faces "
                    "(paper default: on)")
    qw_use_flow_solver: BoolProperty(
        name="Flow Solver", default=True,
        description="Use the flow solver for integer constraints (paper default: on)")
    qw_final_smoothing: BoolProperty(
        name="Final Smoothing", default=True,
        description="Run one global smoothing pass after quadrangulation "
                    "(paper default: on)")
    qw_doublet_removal: BoolProperty(
        name="Doublet Removal", default=True,
        description="Remove doublets (adjacent duplicate quads) to improve mesh "
                    "quality (default: on)")
    qw_split_concaves: BoolProperty(
        name="Split Concave Quads", default=False,
        description="Split concave quads to avoid degeneration (default: off; may "
                    "change the face count)")

    # --- 高级参数（论文/参考实现默认值） ---
    qw_ilp_method: IntProperty(
        name="ILP Method", default=1, min=0, max=3,
        description="Integer programming solver: 0 = Gaussian, 1 = least squares "
                    "(default), 2/3 = others")
    qw_time_limit: FloatProperty(
        name="Solver Time Limit (s)", default=60.0, min=1.0, max=600.0, precision=0,
        description="Time limit for the quadrangulation ILP solve (seconds)")
    qw_alpha: FloatProperty(
        name="Alignment Weight α", default=0.005, min=0.0, max=1.0, precision=3,
        description="Energy weight for singularity alignment (smaller = weaker)")
    qw_minimum_gap: FloatProperty(
        name="Minimum Gap", default=0.4, min=0.0, max=1.0, precision=2,
        description="Minimum gap threshold for the ILP solve")
    qw_gap_limit: FloatProperty(
        name="Gap Limit", default=0.0, min=0.0, max=1.0, precision=2,
        description="Gap stopping threshold for the ILP solve")
    qw_align_sing_weight: FloatProperty(
        name="Singularity Alignment Weight", default=0.1, min=0.0, max=1.0, precision=2,
        description="Weight of the singularity alignment term (works with α)")
    qw_regularity_weight: FloatProperty(
        name="Regularity Weight", default=0.9, min=0.0, max=1.0, precision=2,
        description="Penalty weight for non-quad regularity")
    qw_result_smooth_iters: IntProperty(
        name="Result Smoothing Iterations", default=5, min=0, max=50,
        description="Number of global smoothing iterations on the final result")
    qw_result_smooth_laplacian: IntProperty(
        name="Laplacian Smoothing Iterations", default=2, min=0, max=50,
        description="Number of Laplacian smoothing iterations on the final result")
    qw_chart_smooth_iters: IntProperty(
        name="Chart Smoothing Iterations", default=0, min=0, max=50,
        description="Number of chart smoothing iterations")
    qw_quad_smooth_fixed: IntProperty(
        name="Fixed-Point Smoothing Iterations", default=0, min=0, max=50,
        description="Number of fixed-point smoothing iterations during "
                    "quadrangulation")
    qw_quad_smooth_nonfixed: IntProperty(
        name="Non-Fixed-Point Smoothing Iterations", default=0, min=0, max=50,
        description="Number of non-fixed-point smoothing iterations during "
                    "quadrangulation")
    qw_feasibility_fix: BoolProperty(
        name="Feasibility Fix", default=False,
        description="Enable feasibility-fix post-processing (default: off)")

    # === AutoRemesher 参数（与 engines/autoremesher_engine.py 同步） ===

    ar_edge_scaling: FloatProperty(
        name="Edge Length Scale", default=1.0, min=1.0, max=4.0, precision=2,
        description="Global edge length scale. Values above 1 make quads sparser "
                    "(default 1.0)")
    ar_smooth_normal: FloatProperty(
        name="Smooth Normal Angle (°)", default=0.0, min=0.0, max=180.0, precision=1,
        description="Smooth normals below this angle; 0 disables smoothing "
                    "(default 0)")
    ar_adaptivity: FloatProperty(
        name="Adaptive Density", default=1.0, min=0.0, max=1.0, precision=2,
        description="Distribute faces by curvature: 1 = fully adaptive, 0 = uniform "
                    "(default 1.0)")
    ar_anisotropy: FloatProperty(
        name="Anisotropic Stretch", default=1.0, min=0.0, max=1.0, precision=2,
        description="Stretch quads along the curvature direction: 1 = allow "
                    "stretching, 0 = keep square (default 1.0)")
    ar_write_report: BoolProperty(
        name="Write Statistics Report", default=False,
        description="Ask AutoRemesher to also write a statistics file "
                    "(quads/non-quads/vertices/time)")

    # === QuadriFlow 参数（与 engines/quadriflow_engine.py 同步） ===

    qf_preserve_sharp: BoolProperty(
        name="Preserve Sharp Edges", default=False,
        description="-sharp: preserve sharp feature edges from the input mesh "
                    "(upstream default: off)")
    qf_preserve_boundary: BoolProperty(
        name="Preserve Boundary", default=False,
        description="-boundary: add constraints for open boundaries "
                    "(upstream default: off)")
    qf_adaptive_scale: BoolProperty(
        name="Adaptive Scale", default=False,
        description="-adaptive: allow the scale to adapt to curvature "
                    "(upstream default: off)")
    qf_minimum_cost_flow: BoolProperty(
        name="Minimum Cost Flow Mode", default=False,
        description="-mcf: use the minimum-cost-flow solver for integer "
                    "constraints; the README-recommended alternative")
    qf_aggressive_sat: BoolProperty(
        name="Aggressive SAT", default=False,
        description="-sat: more aggressive SAT solving (upstream default: off)")
    qf_seed: IntProperty(
        name="Random Seed", default=0, min=0, soft_max=100000,
        description="-seed: fix the random seed for reproducible results "
                    "(0 = chosen by the program)")
