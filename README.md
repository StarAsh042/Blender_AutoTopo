# Blender AutoTopo

Blender 3.4+ 自动重拓扑插件：从高面数模型自动生成四边面主导的低模，并尽量保真剪影轮廓。

> **核心设计原则**：剪影保真 > 四边面纯度。

---

## 功能特性

- **多引擎架构**：AutoRemesher / QuadriFlow / QuadWild 三引擎可切换；每个引擎自行声明参数，面板自动适配。
- **剪影误差评估**、**自适应密度**、**锐边特征保留**。
- **后台线程执行**，UI 不卡顿；进度条只读展示，错误信息中文化并给出建议动作。
- **原生 C++ 加速**（锐边导出 / 轮廓误差），缺失时自动降级纯 numpy，结果一致。

---

## 系统要求

| 项 | 要求 |
|----|------|
| Blender | 3.4 或更高（开发验证于 3.4.1） |
| Python 依赖 | `numpy`（Blender 自带；缺失时插件注册会提示） |
| 操作系统 | **当前发行版仅支持 Windows**；macOS/Linux 需自行编译各引擎可执行文件与原生库 |

---

## 安装

1. 取得安装包 `dist/Blender_AutoTopo-1.0.0.zip`（或运行 `python scripts/package_addon.py` 重新打包）。
2. Blender → `Edit ▸ Preferences ▸ Add-ons ▸ Install…`，选择该 zip。
3. 启用 **AutoTopo**。
4. 打开 3D 视图右侧边栏（`N` 面板）→「**自动拓扑**」标签页。

---

## 快速上手

1. 在视口选中一个**网格对象**。
2. 选择**引擎**，设置**目标面数**。
3. 点击「**执行拓扑重建**」。完成后自动创建并选中结果对象（命名 `<原名>_retopo`）。

---

## 引擎

| 引擎 | 适用场景 | 特点 |
|------|----------|------|
| **AutoRemesher**（默认） | 快速产出干净四边面 | 各向同性重网格 + 参数化 + 四边面提取，四边面比例极高、速度快 |
| **QuadriFlow** | 布线均匀、高面数 | 方向场对齐 + 全局参数化，布线均匀、可扩展到高面数 |
| **QuadWild** | 追求高质量 | 交叉场量化 + ILP 最终四边面化，内部四边面干净，奇点处少量过渡三角面 |

- AutoRemesher / QuadriFlow 为 CLI 引擎，可执行文件默认位于 `bin/<engine>/`。
- **二进制完整性校验（fail-closed）**：插件在加载 / 执行外部引擎与原生库前，会对
  `bin/` 下**全部内置二进制**（引擎、依赖与插件 DLL）做 SHA-256 校验，清单为
  `bin/integrity.json`（随包分发）。**清单缺失或损坏时，内置二进制拒绝加载 / 执行**，
  并给出中文错误——无静默放行、无环境变量绕过。
- 出于安全考虑，**不再搜索系统 `PATH`**。偏好设置中填写的自定义可执行文件路径
  **仅当位于 `bin/<engine>/` 之内时才被采用**，否则一律忽略并回退内置二进制。
- 若你自行替换 / 新增 `bin/` 下的二进制，须运行 `python scripts/gen_integrity.py`
  重新生成清单（未登记的 DLL 会被拒绝运行）。

---

## 关键参数

| 参数 | 说明 |
|------|------|
| **目标面数** | 输出网格的目标面数（所有引擎共享）。 |
| **锐边角度** | 内二面角小于该值视为锐边；值越大保留的锐边越多（所有引擎共享）。 |

其余参数为各引擎专属，在面板「**参数** / **高级参数**」中按当前引擎动态显示；
默认值取自各引擎的推荐值，声明见 `engines/*_engine.py` 的 `SettingSpec`。

---

## 第三方许可与合规

本插件捆绑多个第三方原生组件，完整声明见 `bin/quadwild/LICENSE_THIRD_PARTY.txt`：

| 组件 | 许可 |
|------|------|
| QuadWild / QuadPatches 引擎 DLL（`bin/quadwild/`） | **GPLv3** |
| Qt5 运行时 DLL（`bin/autoremesher/`） | **LGPLv3** |
| AutoRemesher / QuadriFlow 可执行文件 | **MIT** |
| MinGW-w64 运行时 DLL（`bin/quadriflow/`） | **GPLv3 + GCC 运行时例外** |
| `autotopo_native.dll`（本项目自有） | **MIT** |

**分发许可（重要）**：由于捆绑 GPLv3 / LGPLv3 组件，并运行于 GPLv3 的 Blender 之上，
本插件**整体按 GPLv3 对待**：

- 你**不能**将本插件以闭源或专有许可再分发；
- 若你修改并再分发，须一并提供 GPLv3 组件的**对应源码**
  （QuadWild / QuadPatches 来自 [QRemeshify](https://github.com/ksami/QRemeshify)）；
- **仅在本机内部使用、不对外分发**时，不触发上述 copyleft 义务。

**Qt5 可替换性**：`bin/autoremesher/` 下的 Qt5 DLL 为 LGPLv3，可在遵守 LGPL 的前提下
替换 / 重新链接为其他 Qt 构建，并按 LGPLv3 要求提供 Qt5 库的源码或获取途径
（见 [qt.io](https://www.qt.io)）。

**MinGW 运行时**：`bin/quadriflow/` 下的 `libgcc_s_seh-1` / `libstdc++-6` /
`libwinpthread-1.dll` 适用 **GPLv3 + GCC 运行时例外（GCC Runtime Library Exception）**；
该例外允许其与非 GPL 二进制一同分发。

**许可全文与源码**：GPLv3 见根目录 `COPYING.GPLv3`，LGPLv3 见根目录 `COPYING.LGPLv3`；
上游仓库链接见 `bin/quadwild/LICENSE_THIRD_PARTY.txt`。

> 说明：QuadWild **算法源码**（[george-ye/QuadWild](https://github.com/george-ye/QuadWild)）上游标注 MIT；
> 本插件分发的是 **QRemeshify 的预编译 DLL**，适用 **GPLv3**。两者不可混同。

> 注：本节的「整体按 GPLv3」为**保守且最稳妥**的合规判断（把 ctypes 运行时链接按最严处理）；
> 最终许可定性建议由项目所有者 / 法务确认。

---

## 打包

```bash
python scripts/package_addon.py
```

生成 `dist/Blender_AutoTopo-1.0.0.zip`（含全部插件文件，排除开发/CI 产物）。

---

## 许可

本插件自有代码以 **MIT** 发布（见 `LICENSE`）。因捆绑第三方组件，
**分发**时须遵守上节「第三方许可与合规」的义务。
