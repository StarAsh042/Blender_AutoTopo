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
