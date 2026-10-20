"""AutoTopo addon preferences.

Holds optional manual paths for the external CLI engines
(AutoRemesher, QuadriFlow). Left empty, the engines use the binary
bundled with the addon (``bin/<engine>/``). A custom path is honored
only when it lies inside ``bin/<engine>/`` and passes integrity
verification (see ``utils/integrity.py``); the system ``PATH`` is never
searched.
"""

import bpy
from bpy.types import AddonPreferences
from bpy.props import StringProperty

from .i18n import t


class AUTOTOPO_Preferences(AddonPreferences):
    bl_idname = "Blender_AutoTopo"

    autoremesher_path: StringProperty(
        name="AutoRemesher Executable",
        description=(
            "Optional: absolute path to the AutoRemesher executable. The path "
            "is honored only when it lies inside the addon's bin/autoremesher/ "
            "directory and passes integrity verification; any other path is "
            "ignored and the bundled binary is used."
        ),
        subtype='FILE_PATH',
        default="",
    )

    quadriflow_path: StringProperty(
        name="QuadriFlow Executable",
        description=(
            "Optional: absolute path to the QuadriFlow executable. The path "
            "is honored only when it lies inside the addon's bin/quadriflow/ "
            "directory and passes integrity verification; any other path is "
            "ignored and the bundled binary is used."
        ),
        subtype='FILE_PATH',
        default="",
    )

    def draw(self, context):
        layout = self.layout
        layout.label(
            text=t("External engine paths (optional; only bin/<engine>/ is trusted)"),
            icon='PREFERENCES',
        )
        layout.prop(self, "autoremesher_path")
        layout.prop(self, "quadriflow_path")
