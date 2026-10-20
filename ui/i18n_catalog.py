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
}

TRANSLATIONS = {
    "zh_CN": {
        **{("*", msgid): text for msgid, text in _ENTRIES.items()},
        **{("AutoTopo", msgid): text for msgid, text in _ENTRIES.items()},
    },
}
