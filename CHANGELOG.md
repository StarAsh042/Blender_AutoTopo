# Changelog

本项目所有值得记录的变更都列在此文件中。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [2.3.0] - 2026-11-26

修复 Blender 4.1+ 下拓扑重建必定失败（#8）、结果不落在原模型上，
以及引擎在真实资产上的失败与卡死。

### 修复

- **Blender 4.1+ 全部引擎不可用（#8）**：`utils/mesh_io.py` 在写入自定义顶点法线前
  无条件执行 `mesh.use_auto_smooth = True`，而该属性在 Blender 4.1 被移除（自动平滑
  改为“Smooth by Angle”修改器，自定义拆分法线本就始终生效）。三个引擎的产出都要经过
  这条路径，所以 4.1 及以上点击「执行拓扑重建」必定 `AttributeError`，引擎其实已经算完
  却拿不到任何输出对象。现在只在该属性仍存在时才赋值，4.1+ 直接跳过。
- **结果位置**：输出对象曾在世界原点以单位缩放创建，而顶点取自源对象的局部空间。
  真实扫描资产以 0.01 缩放导入后，结果比原模型大约 98 倍且未旋转、偏移 0.7 m，
  看起来像「生成失败」或「效果很差」。现在输出继承源对象的 `matrix_world`。
- **平滑着色**：输出的所有面此前都是平面着色（`use_smooth` 全为 False），
  既显棱角又覆盖了写入的自定义法线。现在建面时统一设为平滑。
- **错误信息**：可执行文件缺失分支曾按引擎名做子串匹配，导致 QuadriFlow 崩溃
  （`退出码 3221226505`）被显示成「找不到可执行文件」。该分支已收窄为真正的
  未找到措辞，崩溃进程改走独立分支并显示退出码。
- **面数统计**：UI 报的面数是引擎过滤前的数字（3562），与实际建成的几何（3446）
  不符。现在改为报告真正落到 Blender 里的面数。
- **QuadWild 卡死**：真实资产含数百个碎片岛屿时，原生求解无限期不返回，
  `is_processing` 永久为 True（连插件都无法卸载）。耗时由连通碎片数量驱动而非
  顶点数，且 DLL 无中断入口。现在先数碎片数、超出预算直接拒绝并提示合并，
  阶段之间再校验墙钟预算。797 个碎片的资产由 1700 s+ 无响应变为 6.5 s 明确报错。
- **Blender 3.4 结果出现退化面**：引擎在真实资产上会输出 774 个重复三角形
  （其中 227 个绕向相反）。`compute_vertex_normals` 按面积加权累加，正反两份恰好
  抵消，6864 个顶点里有 779 个算出 `(0, 0, 0)`。3.6 以上会自行兜底，3.4 直接
  把零长法线存进自定义拆分层，于是那些位置像破洞。现在累加前先丢弃零面积与
  重复三角形（与 trimesh 的做法一致），抵消归零的顶点由 779 降到 60。
- **3.4 仍残留的零长 loop 法线**：4.1 以前自定义拆分法线以 short2 偏移
  相对该 loop 自身参考法线存储，方向恰好相反就落在编码奇点，读回来是零向量
  （4.1+ 只在顶点法线本就是零时出现）。清掉自定义层则 23200 个 loop 全部为
  单位长度，可见几何本身没问题，是写入这一步丢了方向。现在写完自定义法线后
  回读实际存下的值，只给读回零长的 loop 换成其所在面的法线，其余 loop 完全
  保持引擎给的方向。3.4 修 15 个、4.5/5.3 各修 3 个、3.6 无需修，四版本
  `zero_length_loop_normals` 均为 0。
- **3.6 偶发破碎面**：3.6 是唯一新旧两套法线接口并存的版本。原先的回读先判断
  `calc_normals_split` 是否存在，于是 3.6 走了旧接口 `calc_normals_split()` +
  `loops.foreach_get("normal")`；实测该组合在刚写完自定义法线的网格上会间歇
  返回未初始化内存（长度 1e19~1e38 量级）或过期零值，而 `corner_normals` 与
  实际着色一致。读到垃圾时既不判零也不修，还把整份数组写回网格，于是表面出现
  破碎补丁。现在回读一律优先 `corner_normals`，并且只在对象已 link、视图层已
  更新之后才回读；无法判定时宁可不动，绝不把读不懂的数值写回。

### 验证

- Blender 3.4.1 / 3.6.23 / 4.5.16 LTS / 5.3.0 四版本全部通过：真实 53.5 万顶点
  扫描资产输出 `size_ratio=(0.9771, 0.9722, 0.9779)`、`smooth_polys=3446/3446`、
  `has_custom_normals=True`。
- 新增 `test/test_shell_count.py`（7 项）与 `test/test_output_transform.py`。
- 新增 #8 回归测试：`test/test_mesh_io_normals.py` 在 4.1+ 真实复现崩溃并验证修复后
  自定义法线生效，`test/test_mesh_io_compat.py` 用 AST 扫描守护该赋值必须带存在性判断。
- 跳过该属性不会丢自定义法线：给定一组倾斜的顶点法线，四个版本读回的 loop 法线
  都是请求的 `(0.6, 0.0, 0.8)`，而非四边形的几何法线 `(0, 0, 1)`。
- #8 按用户报障的真实资产复测：安装 2.3.0 安装包后导入 ~50–54 万顶点 / ~95–99 万面
  的扫描 FBX，点「执行拓扑重建」全程无异常。4.5.16 LTS 得 6202 面、5.3.0 得 3446 面、
  3.4.1 与 3.6.23 各得 4055 面，平滑面与自定义法线均为全量。
- Blender 自带 10 个基础体（plane / cube / circle / uv_sphere / ico_sphere /
  cylinder / cone / grid / monkey / torus）在四版本上零法线、零退化面、平滑面
  100%，结果几何在版本间一致；仅 uv_sphere 因原生重网格无随机种子，
  同一版本连跑三次会得到不同面数。
- 新增 `test/test_vertex_normals.py`（10 项）与 `test/test_loop_normal_repair.py`
  （5 项）覆盖法线计算与修复判定，均已做阴性对照（移除修复后对应断言确实失败）。
- 新增 `test/test_loop_normal_read_path.py`（7 项）：用替身网格验证 `corner_normals`
  优先于旧接口（3.6 上旧接口会被拒绝调用），并验证读回长度远超单位值或含 NaN/Inf 时
  修复函数直接放弃、不写回任何数据。已做阴性对照（把检查改成恒真后 3 项失败）。
- 3.6 连跑 4 次，`corner_normals` 均读到 `zero=0`、长度 0.1967~1.1752；
  落盘后另起进程重开 4 个文件，`corner` 与逐条读数均为 0 零值，只有
  `foreach_get` 仍报 15 条零/长度 1 —— 与"它读的是过期数据"一致。

### 已知问题

- QuadriFlow 内置二进制在复杂扫描资产上会于 `Solve index map` 后断言崩溃
  （Eigen `SparseLU` 断言，退出码 3221226505）。本版只保证错误信息如实反映原因，
  未修复上游二进制缺陷。请改用 AutoRemesher 或 QuadWild。

## [2.2.0] - 2026-11-23

修复 Blender 4.0+ 汉化完全失效，以及 3.x 下 Retopologize 按钮未翻译的问题。

### 修复

- **语言 key 兼容**：`TRANSLATIONS` 同时注册 `zh_HANS` 与 `zh_CN`，兼容 Blender 4.x 与 3.x。Blender 4.0 起改用 `zh_HANS`，原词库因 key 不匹配被静默忽略。
- **翻译 context**：补齐 `RNA` 与 `Operator` 两种 context。RNA 属性标签与 operator 按钮由这两种 context 渲染，原词库只注册 `*` 与 `AutoTopo`，导致 `Target Face Count`、`Adaptive Density`、`Parameters` 仍显示英文。
- **Retopologize 按钮**：`ui/panels.py` 中两处调用改为显式传入 `text=t("Retopologize")`，修复 Blender 3.x 下依赖 `bl_label` 自动翻译不稳定的问题。
- 新增回归测试，覆盖 locale key、context 注册与按钮显式翻译。

### 验证

- 在 Blender 3.4 / 3.6 / 4.5 三个版本 GUI 复测，确认面板标签与按钮全部正常显示中文。

### 已知问题

- Blender 4.5 下执行拓扑重建会因 `mesh.use_auto_smooth` 属性在 4.0+ 被移除而失败（#8）。该问题与汉化无关，本版未处理。

## [2.1.0] - 2026-10-21

新增英文/简体中文双语界面，跟随 Blender 的界面语言设置。

### 新增

- **双语界面**：面板、共享属性、41 个引擎参数、3 个操作符、偏好设置、
  用户错误提示与三引擎进度步骤均支持中英文切换。英文为源语言，
  中文为 zh_CN 翻译；跟随 `偏好设置 ▸ 界面 ▸ 翻译 ▸ 语言`。
- `ui/i18n.py` / `ui/i18n_catalog.py`：翻译注册与运行时 `t()` 辅助；
  注册幂等，支持启用 → 禁用 → 再启用。
- `test/test_i18n_catalog.py`：key/占位符 parity 门禁（缺失、冗余、
  占位符不一致时失败）。
- `test/test_i18n_runtime.py`：语言切换、占位符填充、注册/反注册幂等。

### 变更

- `bl_info["location"]` 改为英文；插件列表位置随界面语言显示。
- QuadWild 的“四边面化”进度步骤不再显示动态密度后缀，以支持翻译。
- 插件版本号 2.0.0 → 2.1.0（`bl_info` / `Cargo.toml` / 打包产物 / 标签一致）。

### 已知限制

- 英文译文由 AI 生成，未经人工审校。
- 日志、内部异常匹配关键词、`SettingSpec` 元数据不翻译。
- 仅在 Blender 3.4.1 验证。

## [2.0.0] - 2026-10-20

原生加速内核由 C++ 重写为 Rust。ctypes ABI、错误码与输出结果保持逐位一致
（golden master 锁定，基准取自 C++ 版）。

### 变更

- **破坏性（技术性，终端用户无感）**：`bin/autotopo_native.dll` 改由 Rust
  crate `native/autotopo_native/` 构建（cargo + MSVC，`.cargo/config.toml`
  固定 `crt-static` 保持自包含、无 VC 运行时依赖）；`native/autotopo_native.cpp`
  与 MinGW 构建链移除。四个导出符号、错误码（-1 ~ -5）与空输入行为不变。
- 插件版本号 1.0.0 → 2.0.0（`bl_info` / 打包产物 / git 标签一致）。
- 打包脚本与产物测试中的版本常量更新为 2.0.0。

### 新增

- `test/test_native_golden.py`：固定种子夹具下两个内核对 C++ 版 golden 数据
  逐位比对（覆盖边界边、逆序/重复/负索引键、退化面、错误码等分支）。
- CI 新增 Rust 门禁 job：`cargo fmt --check` / `clippy -D warnings` /
  `cargo test` / `cargo build --release`，并带新构建 DLL 的 golden 漂移检测。
- crate 文档（`native/autotopo_native/README.md`）与 MSRV（rust-version = 1.99）。

### 性能

- 锐边特征导出约 4× 于原 C++ 实现（10 万面夹具 0.163s → 0.041s）。
- 轮廓误差约 1.2×（60 万面：silhouette 0.75s → 0.50s，dihedral 0.65s → 0.63s）。

### 已知遗留

- `utils/native.py` 的实现标签仍为 `'cpp'`（被既有测试断言，本次不动加载器），
  其文档字符串中的 "C++" 表述待后续刷新。

## [1.0.0] - 2026-10-03

首个公开发行版。

### 新增

- **多引擎架构**：`engines/base.py` 提供 `RemeshEngine` 基类、`SettingSpec` 参数声明
  与引擎注册表；UI/算子按注册表驱动，新增引擎无需改动面板。
- **三引擎支持**：
  - AutoRemesher（默认）——各向同性重网格 + 参数化 + 四边面提取，四边面比例高、速度快；
  - QuadriFlow——方向场对齐 + 全局参数化，布线均匀、可扩展到高面数；
  - QuadWild——交叉场量化 + ILP 最终四边面化，质量高。
- **原生 C++ 加速层**（`bin/autotopo_native.dll`，ctypes 调用，保留 numpy 回退）：
  锐边特征导出（约 18×）、轮廓误差计算（约 54×）。
- **自适应细分**（`adaptive_density`）：按几何偏差分配面数，细节区更密、平坦区更疏。
- **剪影误差评估**与锐边特征保留。
- **发布打包脚本** `scripts/package_addon.py` → `dist/Blender_AutoTopo-1.0.0.zip`。
- **测试体系**：`test/` 下 pytest 用例（纯 Python + Blender 集成），含 `pytest.ini`、`conftest.py`。
- **偏好设置**：CLI 引擎（AutoRemesher / QuadriFlow）可执行文件路径可覆盖（仅限 `bin/<engine>/` 内，受完整性校验约束，见「安全」）。
- 第三方许可资产：根目录 `COPYING.GPLv3` / `COPYING.LGPLv3`，及组件级声明 `bin/quadwild/LICENSE_THIRD_PARTY.txt`。
- 二进制完整性清单 `bin/integrity.json`（覆盖全部内置二进制，随包分发）与生成脚本 `scripts/gen_integrity.py`。

### 变更

- 默认引擎切换为 **AutoRemesher**。
- 进度显示改为**只读**（Blender 4.0+ 用 `layout.progress()`，3.4 回退只读文本进度条）。
- 错误信息中文化，并给出可操作的建议。
- 版本号重置为 `1.0.0`。

### 修复

- **自适应细分网格塌缩**：投影由「最近源顶点」改为「源曲面」（BVHTree），
  消除零面积面与重复顶点位置，自适应密度由噪声驱动改为真正按几何偏差分配。
- 混合三角/四边面网格写入 OBJ 崩溃（`engines/obj_io.py`）。
- 轮廓误差计算在大网格下 OOM 与分钟级退化（改 kd-tree / native 实现）。
- 原生边界 `sharp_keys` 形状未校验导致的越界读（CWE-125）。
- 卸载时释放原生库句柄，确保 Blender「Remove Add-on」可用。

### 安全

- **外部二进制完整性校验（fail-closed）**：加载 / 执行外部引擎与原生库前，对 `bin/` 下
  全部内置二进制做 SHA-256 校验，清单见 `bin/integrity.json`；**清单缺失或损坏则拒绝加载 /
  执行**（无静默放行、无环境变量绕过）。
- **移除系统 `PATH` 回退**：外部引擎可执行文件仅采用内置 `bin/<engine>/`，杜绝 PATH 投毒。
- 偏好设置中的自定义可执行文件路径仅当位于 `bin/<engine>/` 之内时才被采用。
- 加固原生 DLL 输入边界校验；C++ 缺失时自动降级 numpy，结果保持一致。

### 已知限制

- 当前发行版**仅支持 Windows**；macOS/Linux 需自行编译各引擎可执行文件与原生库。
- QuadWild 预编译 DLL 源自 QRemeshify（**GPLv3**），详见第三方许可声明
  （`bin/quadwild/LICENSE_THIRD_PARTY.txt`）。
