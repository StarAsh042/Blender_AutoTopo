"""zh_CN translation catalog for AutoTopo.

Blender's translation API keys entries by the source string itself
(msgid), so every key here must stay byte-identical to the literal used
in the UI code. ``test/test_i18n_catalog.py`` enforces that parity.

Two contexts are registered for every entry:

* ``("*", msgid)`` — used by Blender when it draws RNA properties
  (``name=`` / ``description=`` / ``bl_label=``). Note that Blender's
  built-in translations take precedence over plugin entries in this
  context, so a msgid that collides with a built-in UI word (e.g.
  ``"Engine"``) will show the built-in translation. Use distinct wording
  for strings that must be exact.
* ``("AutoTopo", msgid)`` — used by :func:`ui.i18n.t` for runtime
  strings (operator reports, status lines, result summaries). This
  context is private to the addon and is not shadowed by built-ins.

Only user-visible strings belong here. Log messages, internal exception
keywords and code comments are intentionally not translated.
"""

# msgid -> zh_CN text. Registered under both contexts below.
_ENTRIES = {
    # ── Panel / runtime ──
    "AutoTopo": "自动拓扑",
    "Algorithm Engine": "算法引擎",
    "Unknown engine. Select it again.": "未知引擎，请重新选择",
    "Engine unavailable": "引擎暂不可用",
    "Face Count": "面数控制",
    "Low": "低",
    "Medium": "中",
    "High": "高",
    "Feature Preservation": "特征保留",
    "Parameters": "参数",
    "Advanced": "高级参数",
    "Progress {pct:.0f}%": "进度 {pct:.0f}%",
    "Progress [{bar}] {pct:.0f}%": "进度 [{bar}] {pct:.0f}%",
    "Step: {step}": "步骤: {step}",
    "Cancel": "取消",
    "Engine": "算法引擎",

    # ── Operators / runtime status (slice 3) ──
    "Retopologize": "执行拓扑重建",
    "Run automatic retopology on the active mesh object": "对当前活动网格对象执行自动拓扑重建",
    "Cancel Retopology": "取消拓扑重建",
    "Cancel the running retopology job": "取消正在进行的拓扑重建",
    "Set Face Count": "设置面数",
    "Quickly set the target face count": "快捷设置目标面数",
    "Select a mesh object first": "请先选择一个网格对象",
    "Unknown engine '{engine}'": "未知引擎 '{engine}'",
    "Retopology started; you can keep working in the background...":
        "拓扑重建已启动，可在后台继续操作...",
    "Starting...": "启动中...",
    "Processing...": "正在处理...",
    "Cancelling (takes effect after the current stage)...":
        "正在取消（当前阶段结束后生效）...",
    "Cancellation requested": "已请求取消拓扑重建",
    "Cancelled": "已取消",
    "Error: the engine finished but produced no output mesh":
        "错误: 引擎完成但未生成输出网格",
    "{step} (retry {n}/3)": "{step}（重试 {n}/3）",
    "Output: {verts} verts / {faces} faces": "输出: {verts} 顶点 / {faces} 面",
    "Quads: {quads} / Triangles: {ratio:.1f}%": "四边面: {quads} / 三角面: {ratio:.1f}%",
    "Time: {seconds:.2f} s": "耗时: {seconds:.2f} 秒",
    "Silhouette error: {err:.4f}": "剪影误差: {err:.4f}",
    "Patches: {patches}": "分片数: {patches}",
    "Done!": "完成!",

    # ── User-facing error messages (slice 4) ──
    "Processing failed: an unknown error occurred. See the log for details.":
        "处理失败：发生未知错误，详细信息见日志。",
    "Cancelled: the retopology job was aborted. Adjust the parameters and "
    "try again.":
        "已取消：本次拓扑重建被中止，可调整参数后重新执行。",
    "Built-in binary integrity check failed: the files may have been tampered "
    "with or the version does not match. Reinstall the addon or update "
    "bin/integrity.json and try again.":
        "内置二进制完整性校验失败：文件可能被篡改或版本不匹配。"
        "请重新安装插件，或更新 bin/integrity.json 后重试。",
    "QuadWild libraries are missing: make sure lib_quadwild.dll and "
    "lib_quadpatches.dll are in the addon's bin/quadwild directory, then "
    "restart Blender and try again.":
        "缺少 QuadWild 算法库：请确认插件 bin/quadwild 目录下已放入 "
        "lib_quadwild.dll 与 lib_quadpatches.dll，然后重启 Blender 重试。",
    "External executable not found: make sure the engine is bundled or set "
    "the correct executable path in the addon preferences, then try again.":
        "缺少外部可执行文件：请确认对应引擎已内置或已在插件偏好设置中"
        "填写正确的可执行文件路径，然后重试。",
    "Python dependency numpy is missing: install numpy for Blender's bundled "
    "Python (or use the official Blender build) and try again.":
        "缺少 Python 依赖 numpy：请为 Blender 自带 Python 安装 numpy "
        "（或改用官方 Blender 发行版）后重试。",
    "Failed to create the output mesh: check that the input mesh is valid. "
    "See the log for details.":
        "创建输出网格失败：请检查输入网格是否有效，详细信息见日志。",
    "Invalid mesh data: make sure the selected object is a valid mesh (check "
    "it in Edit Mode and remove zero-area faces), then try again.":
        "网格数据无效：请确认所选对象是有效网格（可在编辑模式下检查并"
        "移除零面积面）后重试。",
    "Unknown algorithm engine: select an engine again in the panel and retry.":
        "未知算法引擎：请在上方面板重新选择引擎后重试。",
    "The engine produced no valid output: try lowering the target face count, "
    "disabling adaptive density, or relaxing the tolerance, then retry.":
        "引擎未生成有效输出：请尝试降低目标面数、关闭自适应密度或"
        "放宽容差后重试。",
    "Processing failed: {summary} (see the log for details)":
        "处理失败：{summary}（详细信息见日志）",

    # ── Preferences (slice 3) ──
    "AutoRemesher Executable": "AutoRemesher 可执行文件",
    "Optional: absolute path to the AutoRemesher executable. The path is "
    "honored only when it lies inside the addon's bin/autoremesher/ directory "
    "and passes integrity verification; any other path is ignored and the "
    "bundled binary is used.":
        "可选：AutoRemesher 可执行文件的绝对路径。仅当该路径位于插件内置的 "
        "bin/autoremesher/ 目录内且通过完整性校验时才会被采用；其他路径"
        "一律忽略并使用内置二进制。",
    "QuadriFlow Executable": "QuadriFlow 可执行文件",
    "Optional: absolute path to the QuadriFlow executable. The path is "
    "honored only when it lies inside the addon's bin/quadriflow/ directory "
    "and passes integrity verification; any other path is ignored and the "
    "bundled binary is used.":
        "可选：QuadriFlow 可执行文件的绝对路径。仅当该路径位于插件内置的 "
        "bin/quadriflow/ 目录内且通过完整性校验时才会被采用；其他路径"
        "一律忽略并使用内置二进制。",
    "External engine paths (optional; only bin/<engine>/ is trusted)":
        "外部引擎路径（可选；仅内置目录 bin/<engine>/ 受信任）",

    # ── Shared properties ──
    "Retopology algorithm engine": "拓扑重建算法引擎",
    "AutoRemesher (fast quad)": "AutoRemesher 快速四边面",
    "AutoRemesher (MIT): isotropic remeshing + parameterization + quad "
    "extraction; very high quad ratio and fast":
        "AutoRemesher (MIT)：各向同性重网格 + 参数化 + 四边面提取，"
        "四边面比例极高、速度快",
    "QuadriFlow (field-aligned)": "QuadriFlow 场对齐",
    "QuadriFlow (MIT, SIGGRAPH 2020): direction-field alignment + global "
    "parameterization; even layout, scales to high face counts":
        "QuadriFlow (MIT, SIGGRAPH 2020)：方向场对齐 + 全局参数化，"
        "布线均匀、可扩展到高面数",
    "QuadWild (high quality)": "QuadWild 高质量",
    "QuadWild (SIGGRAPH Asia 2019): cross-field quantization + ILP final "
    "quadrangulation; clean interior quads, a few transition triangles at "
    "singularities":
        "QuadWild (SIGGRAPH Asia 2019)：交叉场量化 + ILP 最终四边面化，"
        "内部四边面干净、奇点处带少量过渡三角面",
    "Target Face Count": "目标面数",
    "Target number of faces in the output mesh": "输出网格的目标面数",
    "Sharp Edge Angle": "锐边角度",
    "Edges whose interior dihedral angle is below this value are treated as "
    "sharp (flat = 180, right angle = 90; larger values preserve more sharp "
    "edges). Unit: degrees":
        "边的内二面角小于该值时视为锐边"
        "（平坦=180，直角=90；值越大保留的锐边越多），单位：度",
    "Processing": "处理中",
    "Whether retopology is currently running": "是否正在执行拓扑重建",
    "Status": "状态",
    "Current status message": "当前状态信息",
    "Progress": "进度",
    "Current progress (read-only)": "当前处理进度（只读显示）",
    "Current Step": "当前步骤",
    "Name of the step currently running": "当前正在执行的步骤名称",
    "Last Result": "上次结果",
    "Result information from the last retopology run": "上次拓扑重建的结果信息",

    # ── Engine availability hints (shown in the panel) ──
    "AutoRemesher not found. Place autoremesher.exe in the addon's "
    "bin/autoremesher/ directory and try again.":
        "未找到 AutoRemesher。请将 autoremesher.exe 放入插件内置的 "
        "bin/autoremesher/ 目录后重试。",
    "QuadriFlow not found. Place quadriflow.exe in the addon's "
    "bin/quadriflow/ directory and try again.":
        "未找到 QuadriFlow。请将 quadriflow.exe 放入插件内置的 "
        "bin/quadriflow/ 目录后重试。",
    "QuadWild libraries not found. Place lib_quadwild.dll and "
    "lib_quadpatches.dll in the addon's bin/quadwild/ directory "
    "(the current release ships Windows binaries only), then "
    "restart Blender and try again.":
        "未找到 QuadWild 算法库：请将 lib_quadwild.dll 与 "
        "lib_quadpatches.dll 放入插件的 bin/quadwild 目录"
        "（当前发行版仅含 Windows 二进制），然后重启 Blender 重试。",

    # ── Engine settings and progress steps (slice 5) ──
    "Keep Sharp Edges": "保留锐边",
    "Detect and preserve sharp edge features during retopology (disable to treat the surface as fully smooth)": "重拓扑时检测并保留锐利边缘特征（关闭则视为纯平滑曲面）",
    "Face Count Tolerance (%)": "面数容差 (%)",
    "Allowed deviation of the output face count from the target (percent); exceeding it reruns quadrangulation": "允许输出面数相对目标的偏差（百分比），超出则重跑四边面化",
    "Adaptive Density": "自适应密度",
    "Distribute faces by detail: denser in damaged/high-curvature areas, sparser on flat regions": "按细节分布面数：破损/高曲率区域更密、平面更疏",
    "Isometry Constraint": "等距约束",
    "Preserve local isometry and reduce stretching (paper default: on)": "保持局部等距，减少拉伸变形（论文默认开启）",
    "Hard Parity Constraint": "硬奇偶性约束",
    "Enforce quad parity constraints to reduce non-quad faces (paper default: on)": "强制四边形奇偶性约束，减少非四边面（论文默认开启）",
    "Flow Solver": "流求解器",
    "Use the flow solver for integer constraints (paper default: on)": "使用流求解器求解整数约束（论文默认开启）",
    "Final Smoothing": "最终平滑",
    "Run one global smoothing pass after quadrangulation (paper default: on)": "四边面化完成后做一次整体平滑（论文默认开启）",
    "Doublet Removal": "双元移除",
    "Remove doublets (adjacent duplicate quads) to improve mesh quality (default: on)": "移除 doublet（相邻重复四边形），改善网格质量（默认开启）",
    "Split Concave Quads": "拆分凹面",
    "Split concave quads to avoid degeneration (default: off; may change the face count)": "拆分凹四边形以避免退化（默认关闭，可能改变面数）",
    "ILP Method": "ILP 方法",
    "Integer programming solver: 0 = Gaussian, 1 = least squares (default), 2/3 = others": "整数规划求解方法：0=高斯、1=最小二乘(默认)、2/3=其它",
    "Solver Time Limit (s)": "求解时间上限 (s)",
    "Time limit for the quadrangulation ILP solve (seconds)": "四边面化 ILP 求解的时间上限（秒）",
    "Alignment Weight α": "对齐权重 α",
    "Energy weight for singularity alignment (smaller = weaker)": "奇点对齐的能量权重（越小越弱）",
    "Minimum Gap": "最小间隙",
    "Minimum gap threshold for the ILP solve": "ILP 求解的最小间隙阈值",
    "Gap Limit": "间隙上限",
    "Gap stopping threshold for the ILP solve": "ILP 求解的间隙停止阈值",
    "Singularity Alignment Weight": "奇点对齐权重",
    "Weight of the singularity alignment term (works with α)": "奇点对齐项权重（与 α 协同）",
    "Regularity Weight": "规则性权重",
    "Penalty weight for non-quad regularity": "非四边形规则性惩罚权重",
    "Result Smoothing Iterations": "结果平滑迭代",
    "Number of global smoothing iterations on the final result": "最终结果整体平滑迭代次数",
    "Laplacian Smoothing Iterations": "拉普拉斯平滑迭代",
    "Number of Laplacian smoothing iterations on the final result": "最终结果拉普拉斯平滑迭代次数",
    "Chart Smoothing Iterations": "图表平滑迭代",
    "Number of chart smoothing iterations": "图表平滑迭代次数",
    "Fixed-Point Smoothing Iterations": "固定点平滑迭代",
    "Number of fixed-point smoothing iterations during quadrangulation": "四边面化固定点平滑迭代次数",
    "Non-Fixed-Point Smoothing Iterations": "非固定点平滑迭代",
    "Number of non-fixed-point smoothing iterations during quadrangulation": "四边面化非固定点平滑迭代次数",
    "Feasibility Fix": "可行性修复",
    "Enable feasibility-fix post-processing (default: off)": "启用可行性修复后处理（默认关闭）",
    "Edge Length Scale": "边长缩放",
    "Global edge length scale. Values above 1 make quads sparser (default 1.0)": "全局边长缩放系数。大于 1 使四边面更稀疏（默认 1.0）",
    "Smooth Normal Angle (°)": "平滑法线角度 (°)",
    "Smooth normals below this angle; 0 disables smoothing (default 0)": "小于该角度时法线平滑着色；0 表示不平滑（默认 0）",
    "Distribute faces by curvature: 1 = fully adaptive, 0 = uniform (default 1.0)": "按曲率分配面数：1 为完全自适应，0 为均匀（默认 1.0）",
    "Anisotropic Stretch": "各向异性拉伸",
    "Stretch quads along the curvature direction: 1 = allow stretching, 0 = keep square (default 1.0)": "沿曲率方向拉长四边面：1 为允许拉伸，0 为保持方正（默认 1.0）",
    "Write Statistics Report": "输出统计报告",
    "Ask AutoRemesher to also write a statistics file (quads/non-quads/vertices/time)": "额外让 AutoRemesher 写一份统计文件（四边面/非四边面/顶点/耗时）",
    "Preserve Sharp Edges": "保留锐边",
    "-sharp: preserve sharp feature edges from the input mesh (upstream default: off)": "-sharp：保留输入网格的锐利特征边（上游默认关闭）",
    "Preserve Boundary": "保留边界",
    "-boundary: add constraints for open boundaries (upstream default: off)": "-boundary：为开放边界添加约束（上游默认关闭）",
    "Adaptive Scale": "自适应尺度",
    "-adaptive: allow the scale to adapt to curvature (upstream default: off)": "-adaptive：允许尺度随曲率自适应（上游默认关闭）",
    "Minimum Cost Flow Mode": "最小费用流模式",
    "-mcf: use the minimum-cost-flow solver for integer constraints; the README-recommended alternative": "-mcf：改用最小费用流求解整数约束，README 推荐的替代模式",
    "Aggressive SAT": "激进 SAT 求解",
    "-sat: more aggressive SAT solving (upstream default: off)": "-sat：更激进的 SAT 求解（上游默认关闭）",
    "Random Seed": "随机种子",
    "-seed: fix the random seed for reproducible results (0 = chosen by the program)": "-seed：固定随机种子以获得可复现结果（0 表示由程序决定）",
    "Exporting mesh...": "导出网格...",
    "Running AutoRemesher...": "运行 AutoRemesher...",
    "Running QuadriFlow...": "运行 QuadriFlow...",
    "Reading result...": "读取结果...",
    "Done": "完成",
    "Detecting sharp features...": "检测锐边特征...",
    "Remeshing and computing the direction field...": "重网格化与方向场计算...",
    "Tracing streamlines...": "流线追踪...",
    "Quadrangulation...": "四边面化...",
    "Adaptive detail subdivision...": "自适应细节细分...",

}

TRANSLATIONS = {
    "zh_CN": {
        **{("*", msgid): text for msgid, text in _ENTRIES.items()},
        **{("AutoTopo", msgid): text for msgid, text in _ENTRIES.items()},
    },
}
