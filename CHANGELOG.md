# Changelog

本项目所有值得记录的变更都列在此文件中。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
