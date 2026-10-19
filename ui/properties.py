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
            ('quadwild', "QuadWild 高质量",
             "QuadWild (SIGGRAPH Asia 2019)：交叉场量化 + ILP 最终四边面化，"
             "内部四边面干净、奇点处带少量过渡三角面"),
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

    # NOTE: 内部状态，仅供面板只读展示（panels.py 用 layout.progress()
    # 渲染，不用 box.prop()），用户不可编辑/拖动。
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

    # === QuadWild 参数（与 engines/quadwild_engine.py 的 SettingSpec 同步） ===

    qw_keep_sharp: BoolProperty(
        name="保留锐边", default=True,
        description="重拓扑时检测并保留锐利边缘特征（关闭则视为纯平滑曲面）")
    qw_tolerance: FloatProperty(
        name="面数容差 (%)", default=10.0, min=1.0, max=20.0, precision=1,
        description="允许输出面数相对目标的偏差（百分比），超出则重跑四边面化")
    qw_adaptive_density: BoolProperty(
        name="自适应密度", default=True,
        description="按细节分布面数：破损/高曲率区域更密、平面更疏")
    qw_isometry: BoolProperty(
        name="等距约束", default=True,
        description="保持局部等距，减少拉伸变形（论文默认开启）")
    qw_hard_parity: BoolProperty(
        name="硬奇偶性约束", default=True,
        description="强制四边形奇偶性约束，减少非四边面（论文默认开启）")
    qw_use_flow_solver: BoolProperty(
        name="流求解器", default=True,
        description="使用流求解器求解整数约束（论文默认开启）")
    qw_final_smoothing: BoolProperty(
        name="最终平滑", default=True,
        description="四边面化完成后做一次整体平滑（论文默认开启）")
    qw_doublet_removal: BoolProperty(
        name="双元移除", default=True,
        description="移除 doublet（相邻重复四边形），改善网格质量（默认开启）")
    qw_split_concaves: BoolProperty(
        name="拆分凹面", default=False,
        description="拆分凹四边形以避免退化（默认关闭，可能改变面数）")

    # --- 高级参数（论文/参考实现默认值） ---
    qw_ilp_method: IntProperty(
        name="ILP 方法", default=1, min=0, max=3,
        description="整数规划求解方法：0=高斯、1=最小二乘(默认)、2/3=其它")
    qw_time_limit: FloatProperty(
        name="求解时间上限 (s)", default=60.0, min=1.0, max=600.0, precision=0,
        description="四边面化 ILP 求解的时间上限（秒）")
    qw_alpha: FloatProperty(
        name="对齐权重 α", default=0.005, min=0.0, max=1.0, precision=3,
        description="奇点对齐的能量权重（越小越弱）")
    qw_minimum_gap: FloatProperty(
        name="最小间隙", default=0.4, min=0.0, max=1.0, precision=2,
        description="ILP 求解的最小间隙阈值")
    qw_gap_limit: FloatProperty(
        name="间隙上限", default=0.0, min=0.0, max=1.0, precision=2,
        description="ILP 求解的间隙停止阈值")
    qw_align_sing_weight: FloatProperty(
        name="奇点对齐权重", default=0.1, min=0.0, max=1.0, precision=2,
        description="奇点对齐项权重（与 α 协同）")
    qw_regularity_weight: FloatProperty(
        name="规则性权重", default=0.9, min=0.0, max=1.0, precision=2,
        description="非四边形规则性惩罚权重")
    qw_result_smooth_iters: IntProperty(
        name="结果平滑迭代", default=5, min=0, max=50,
        description="最终结果整体平滑迭代次数")
    qw_result_smooth_laplacian: IntProperty(
        name="拉普拉斯平滑迭代", default=2, min=0, max=50,
        description="最终结果拉普拉斯平滑迭代次数")
    qw_chart_smooth_iters: IntProperty(
        name="图表平滑迭代", default=0, min=0, max=50,
        description="图表平滑迭代次数")
    qw_quad_smooth_fixed: IntProperty(
        name="固定点平滑迭代", default=0, min=0, max=50,
        description="四边面化固定点平滑迭代次数")
    qw_quad_smooth_nonfixed: IntProperty(
        name="非固定点平滑迭代", default=0, min=0, max=50,
        description="四边面化非固定点平滑迭代次数")
    qw_feasibility_fix: BoolProperty(
        name="可行性修复", default=False,
        description="启用可行性修复后处理（默认关闭）")

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
