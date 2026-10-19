"""AutoTopo addon preferences.

Holds optional manual paths for the external CLI engines
(AutoRemesher). Left empty, the engines use the binary
bundled with the addon (``bin/<engine>/``). A custom path is honored
only when it lies inside ``bin/<engine>/`` and passes integrity
verification (see ``utils/integrity.py``); the system ``PATH`` is never
searched.
"""

import bpy
from bpy.types import AddonPreferences
from bpy.props import StringProperty


class AUTOTOPO_Preferences(AddonPreferences):
    bl_idname = "Blender_AutoTopo"

    autoremesher_path: StringProperty(
        name="AutoRemesher 可执行文件",
        description=(
            "可选：AutoRemesher 可执行文件的绝对路径。仅当该路径位于插件内置的 "
            "bin/autoremesher/ 目录内且通过完整性校验时才会被采用；其他路径"
            "一律忽略并使用内置二进制。"
        ),
        subtype='FILE_PATH',
        default="",
    )

    def draw(self, context):
        layout = self.layout
        layout.label(
            text="外部引擎路径（可选；仅内置目录 bin/<engine>/ 受信任）",
            icon='PREFERENCES',
        )
        layout.prop(self, "autoremesher_path")
