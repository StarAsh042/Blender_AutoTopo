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
        name="引擎",
        description="拓扑重建算法引擎",
        items=[
            ('autoremesher', "AutoRemesher 快速四边面",
             "AutoRemesher (MIT)：各向同性重网格 + 参数化 + 四边面提取，"
             "四边面比例极高、速度快"),
            ('quadriflow', "QuadriFlow 场对齐",
             "QuadriFlow (MIT, SIGGRAPH 2020)：方向场对齐 + 全局参数化，"
             "布线均匀、可扩展到高面数"),
        ],
        default='autoremesher',
    )

    # === 共享基础参数（非引擎独占） ===

    target_face_count: IntProperty(
        name="目标面数",
        description="输出网格的目标面数",
        default=2000,
        min=100,
        max=100000,
        soft_min=200,
        soft_max=20000,
    )

    sharp_angle_threshold: FloatProperty(
        name="锐边角度",
        description="边的内二面角小于该值时视为锐边"
                    "（平坦=180，直角=90；值越大保留的锐边越多），单位：度",
        default=90.0,
        min=10.0,
        max=180.0,
        precision=1,
    )

    # === 内部状态（只读展示，不暴露给用户编辑） ===

    is_processing: BoolProperty(
        name="处理中",
        description="是否正在执行拓扑重建",
        default=False,
    )

    status_message: StringProperty(
        name="状态",
        description="当前状态信息",
        default="",
    )

    # NOTE: 内部状态，仅供面板只读展示，用户不可编辑/拖动。
    progress: FloatProperty(
        name="进度",
        description="当前处理进度（只读显示）",
        default=0.0,
        min=0.0,
        max=100.0,
        subtype='PERCENTAGE',
    )

    step_name: StringProperty(
        name="当前步骤",
        description="当前正在执行的步骤名称",
        default="",
    )

    last_result_info: StringProperty(
        name="上次结果",
        description="上次拓扑重建的结果信息",
        default="",
    )

    # === AutoRemesher 参数（与 engines/autoremesher_engine.py 同步） ===

    ar_edge_scaling: FloatProperty(
        name="边长缩放", default=1.0, min=1.0, max=4.0, precision=2,
        description="全局边长缩放系数。大于 1 使四边面更稀疏（默认 1.0）")
    ar_smooth_normal: FloatProperty(
        name="平滑法线角度 (°)", default=0.0, min=0.0, max=180.0, precision=1,
        description="小于该角度时法线平滑着色；0 表示不平滑（默认 0）")
    ar_adaptivity: FloatProperty(
        name="自适应密度", default=1.0, min=0.0, max=1.0, precision=2,
        description="按曲率分配面数：1 为完全自适应，0 为均匀（默认 1.0）")
    ar_anisotropy: FloatProperty(
        name="各向异性拉伸", default=1.0, min=0.0, max=1.0, precision=2,
        description="沿曲率方向拉长四边面：1 为允许拉伸，0 为保持方正（默认 1.0）")
    ar_write_report: BoolProperty(
        name="输出统计报告", default=False,
        description="额外让 AutoRemesher 写一份统计文件"
                    "（四边面/非四边面/顶点/耗时）")

    # === QuadriFlow 参数（与 engines/quadriflow_engine.py 同步） ===

    qf_preserve_sharp: BoolProperty(
        name="保留锐边", default=False,
        description="-sharp：保留输入网格的锐利特征边（上游默认关闭）")
    qf_preserve_boundary: BoolProperty(
        name="保留边界", default=False,
        description="-boundary：为开放边界添加约束（上游默认关闭）")
    qf_adaptive_scale: BoolProperty(
        name="自适应尺度", default=False,
        description="-adaptive：允许尺度随曲率自适应（上游默认关闭）")
    qf_minimum_cost_flow: BoolProperty(
        name="最小费用流模式", default=False,
        description="-mcf：改用最小费用流求解整数约束，README 推荐的替代模式")
    qf_aggressive_sat: BoolProperty(
        name="激进 SAT 求解", default=False,
        description="-sat：更激进的 SAT 求解（上游默认关闭）")
    qf_seed: IntProperty(
        name="随机种子", default=0, min=0, soft_max=100000,
        description="-seed：固定随机种子以获得可复现结果（0 表示由程序决定）")
