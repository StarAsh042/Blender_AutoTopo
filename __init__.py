"""Blender AutoTopo - Automatic Retopology Plugin.

A Blender 3.4+ addon for automatic retopology with
silhouette preservation. Generates quad-dominant meshes
from high-poly source geometry.

Core Design Principle: Silhouette fidelity > quad purity.
"""

bl_info = {
    "name": "AutoTopo",
    "author": "AutoTopo Team",
    "version": (0, 1, 0),
    "blender": (3, 4, 0),
    "location": "View3D > Sidebar > 自动拓扑",
    "description": "Automatic retopology with silhouette preservation",
    "category": "Mesh",
}

import bpy


class AUTOTOPO_PT_MainPanel(bpy.types.Panel):
    """AutoTopo 主面板 - 3D 视图侧边栏。"""

    bl_label = "自动拓扑"
    bl_idname = "AUTOTOPO_PT_MainPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "自动拓扑"

    def draw(self, context):
        self.layout.label(text="AutoTopo")


classes = (AUTOTOPO_PT_MainPanel,)


def register():
    """Register the AutoTopo plugin with Blender."""
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister the AutoTopo plugin from Blender."""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
