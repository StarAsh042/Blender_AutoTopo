"""Mesh data conversion between Blender Mesh and NumPy arrays."""

import numpy as np
from typing import Tuple, Optional, Dict, Any
import bmesh
import bpy
from mathutils import Vector

from ..utils.logger import logger


class MeshData:
    """Container for mesh data in NumPy format."""

    def __init__(self):
        self.vertices: np.ndarray = np.zeros((0, 3), dtype=np.float64)
        self.faces: np.ndarray = np.zeros((0, 3), dtype=np.int64)
        self.normals: np.ndarray = np.zeros((0, 3), dtype=np.float64)
        self.sharp_edges: set = set()  # Set of (v0, v1) tuples with v0 < v1
        self.vertex_colors: Optional[np.ndarray] = None
        self.uvs: Optional[np.ndarray] = None
        self.edge_keys: Optional[np.ndarray] = None

    @property
    def n_verts(self) -> int:
        return len(self.vertices)

    @property
    def n_faces(self) -> int:
        return len(self.faces)

    def validate(self) -> bool:
        """Check if mesh data is valid."""
        if self.n_verts == 0:
            logger.error("Mesh has no vertices")
            return False
        if self.n_faces == 0:
            logger.error("Mesh has no faces")
            return False
        # Check face indices are in range (handles both int arrays and object arrays)
        if self.faces.dtype == object:
            max_idx = max(max(int(x) for x in face) for face in self.faces)
        else:
            max_idx = int(self.faces.max())
        if max_idx >= self.n_verts:
            logger.error("Face indices out of range")
            return False
        if self.vertices.shape[1] != 3:
            logger.error("Vertices must be (N, 3)")
            return False
        return True


def blender_to_mesh_data(obj: bpy.types.Object) -> MeshData:
    """Convert a Blender mesh object to MeshData.

    Args:
        obj: Blender mesh object (must be of type 'MESH')

    Returns:
        MeshData containing the mesh in NumPy format
    """
    if obj.type != 'MESH':
        raise TypeError(f"Object '{obj.name}' is not a mesh (type: {obj.type})")

    mesh_data = MeshData()
    mesh = obj.data

    # Ensure mesh is triangulated for processing
    # Work on a temporary bmesh copy to avoid modifying the original
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    eval_mesh = eval_obj.data

    bm = bmesh.new()
    bm.from_mesh(eval_mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])

    # Write triangulated result into a temporary mesh
    tmp_mesh = bpy.data.meshes.new("_autotopo_tmp")
    bm.to_mesh(tmp_mesh)
    bm.free()

    mesh = tmp_mesh

    # Extract vertices using foreach_get (much faster than Python loop)
    n_verts = len(mesh.vertices)
    mesh_data.vertices = np.zeros((n_verts, 3), dtype=np.float64)
    mesh.vertices.foreach_get('co', mesh_data.vertices.ravel())

    # Extract faces (triangles after triangulation)
    n_faces = len(mesh.polygons)
    # Get loop start indices and total loop counts per polygon
    loop_starts = np.zeros(n_faces, dtype=np.int64)
    loop_totals = np.zeros(n_faces, dtype=np.int64)
    mesh.polygons.foreach_get('loop_start', loop_starts)
    mesh.polygons.foreach_get('loop_total', loop_totals)

    # Get all loop vertex indices at once
    n_loops = len(mesh.loops)
    all_loop_verts = np.zeros(n_loops, dtype=np.int64)
    mesh.loops.foreach_get('vertex_index', all_loop_verts)

    # Extract triangle faces (vectorized). The input is triangulated
    # beforehand, so the common path is a plain reshape; the mixed path
    # gathers the tri faces with fancy indexing and warns on the rest.
    tri_mask = loop_totals == 3
    if bool(tri_mask.all()):
        mesh_data.faces = np.ascontiguousarray(
            all_loop_verts.reshape(-1, 3), dtype=np.int64)
    elif bool(tri_mask.any()):
        for i in np.nonzero(~tri_mask)[0]:
            logger.warning(
                f"Face {int(i)} has {int(loop_totals[i])} vertices, "
                f"expected 3")
        starts = loop_starts[tri_mask]
        mesh_data.faces = all_loop_verts[starts[:, None] + np.arange(3)]
    else:
        mesh_data.faces = np.zeros((0, 3), dtype=np.int64)

    # Extract vertex normals using foreach_get
    mesh_data.normals = np.zeros((n_verts, 3), dtype=np.float64)
    mesh.vertices.foreach_get('normal', mesh_data.normals.ravel())

    # Extract sharp edges
    mesh_data.sharp_edges = set()
    n_edges = len(mesh.edges)
    edge_verts = np.zeros((n_edges, 2), dtype=np.int64)
    mesh.edges.foreach_get('vertices', edge_verts.ravel())
    edge_sharp = np.zeros(n_edges, dtype=bool)
    mesh.edges.foreach_get('use_edge_sharp', edge_sharp)
    # Vectorized: normalize each sharp edge to (min, max) and build the
    # set in one shot instead of a per-edge Python loop.
    if bool(edge_sharp.any()):
        sel = edge_verts[edge_sharp]
        lo = np.minimum(sel[:, 0], sel[:, 1]).tolist()
        hi = np.maximum(sel[:, 0], sel[:, 1]).tolist()
        mesh_data.sharp_edges = set(zip(lo, hi))
    mesh_data.edge_keys = edge_verts

    # NOTE: per-loop UV / vertex-colour extraction was removed here. It was
    # O(n_loops) in Python and no downstream consumer ever read
    # ``mesh_data.uvs`` / ``mesh_data.vertex_colors`` (audit finding #24),
    # so it was pure cost on large meshes.

    logger.info(
        f"Imported mesh: {n_verts} vertices, {n_faces} faces, "
        f"{len(mesh_data.sharp_edges)} sharp edges"
    )

    # Clean up temporary mesh
    bpy.data.meshes.remove(tmp_mesh)

    return mesh_data


def mesh_data_to_blender(
    mesh_data: MeshData,
    name: str = "AutoTopo_Output",
    collection: Optional[bpy.types.Collection] = None
) -> bpy.types.Object:
    """Convert MeshData to a Blender mesh object using bmesh.

    Args:
        mesh_data: MeshData containing the output mesh
        name: Name for the new object
        collection: Target collection (uses active collection if None)

    Returns:
        The newly created Blender object
    """
    if not mesh_data.validate():
        raise ValueError("Invalid mesh data, cannot create Blender mesh")

    n_verts = mesh_data.n_verts
    n_faces = mesh_data.n_faces

    # Use bmesh for reliable mesh creation
    bm = bmesh.new()

    # Add vertices
    bm_verts = []
    for v in mesh_data.vertices:
        bm_verts.append(bm.verts.new(v.tolist()))

    # Add faces — support mixed tri/quad faces
    # Prefer _quad_faces/_tri_faces if available (from quad extraction pipeline)
    quad_faces = getattr(mesh_data, '_quad_faces', None)
    tri_faces = getattr(mesh_data, '_tri_faces', None)

    if quad_faces is not None and tri_faces is not None:
        # Use preserved quad/tri info from pipeline
        all_output_faces = list(quad_faces) + list(tri_faces)
    else:
        # Fallback: use mesh_data.faces (may be mixed tri/quad object array)
        all_output_faces = []
        for f in mesh_data.faces:
            all_output_faces.append(tuple(int(x) for x in f))

    for face_verts in all_output_faces:
        try:
            bm.faces.new([bm_verts[i] for i in face_verts])
        except ValueError:
            pass  # Skip degenerate faces

    # Write bmesh to a new Blender mesh
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    # Set sharp edges
    for edge in mesh.edges:
        v0, v1 = edge.vertices
        key = (min(v0, v1), max(v0, v1))
        if key in mesh_data.sharp_edges:
            edge.use_edge_sharp = True

    # Set vertex normals if available
    if mesh_data.normals is not None and len(mesh_data.normals) == n_verts:
        mesh.use_auto_smooth = True
        normals_list = [tuple(n.tolist()) for n in mesh_data.normals]
        mesh.normals_split_custom_set_from_vertices(normals_list)

    # Create object
    obj = bpy.data.objects.new(name, mesh)

    # Link to collection
    if collection is None:
        collection = bpy.context.collection
    collection.objects.link(obj)

    logger.info(
        f"Created Blender object '{name}': "
        f"{n_verts} vertices, {n_faces} faces"
    )
    return obj


def obj_to_mesh_data(filepath: str) -> MeshData:
    """Load an OBJ file into MeshData with mixed tri/quad support.

    N-gons (>4 verts) are fan-triangulated into the triangle list.
    Fills ``_quad_faces`` / ``_tri_faces`` so that
    ``mesh_data_to_blender`` outputs mixed faces correctly.

    Args:
        filepath: Path to the OBJ file

    Returns:
        MeshData with vertices, faces and quad/tri face lists
    """
    from ..engines.obj_io import read_obj
    from ..utils.math_utils import compute_vertex_normals

    vertices, faces = read_obj(filepath)

    quad_faces = []
    tri_faces = []
    for face in faces:
        if len(face) == 4:
            quad_faces.append(face)
        elif len(face) == 3:
            tri_faces.append(face)
        elif len(face) > 4:
            # Fan triangulation for n-gons
            for j in range(1, len(face) - 1):
                tri_faces.append((face[0], face[j], face[j + 1]))

    result = MeshData()
    result.vertices = vertices
    all_faces = quad_faces + tri_faces
    result.faces = (
        np.array(all_faces, dtype=object) if all_faces
        else np.array([], dtype=object)
    )
    result._quad_faces = quad_faces
    result._tri_faces = tri_faces

    # Compute vertex normals via triangulated faces
    tri_for_normals = []
    for f in quad_faces:
        tri_for_normals.append((f[0], f[1], f[2]))
        tri_for_normals.append((f[0], f[2], f[3]))
    tri_for_normals.extend(tri_faces)
    if tri_for_normals:
        tri_arr = np.array(tri_for_normals, dtype=np.int64)
        result.normals = compute_vertex_normals(vertices, tri_arr)

    return result


def mesh_data_to_bmesh(mesh_data: MeshData) -> bmesh.types.BMesh:
    """Convert MeshData to BMesh for further processing."""
    bm = bmesh.new()

    # Add vertices
    for v in mesh_data.vertices:
        bm.verts.new(v)
    bm.verts.ensure_lookup_table()

    # Add faces
    for f in mesh_data.faces:
        try:
            bm.faces.new([bm.verts[i] for i in f])
        except ValueError:
            pass  # Skip degenerate faces
    bm.faces.ensure_lookup_table()

    return bm


def bmesh_to_mesh_data(bm: bmesh.types.BMesh) -> MeshData:
    """Convert BMesh to MeshData."""
    mesh_data = MeshData()

    n_verts = len(bm.verts)
    mesh_data.vertices = np.zeros((n_verts, 3), dtype=np.float64)
    mesh_data.normals = np.zeros((n_verts, 3), dtype=np.float64)

    for i, v in enumerate(bm.verts):
        mesh_data.vertices[i] = v.co
        mesh_data.normals[i] = v.normal

    # Triangulate faces
    faces_tri = []
    for face in bm.faces:
        if len(face.verts) == 3:
            faces_tri.append([v.index for v in face.verts])
        elif len(face.verts) > 3:
            # Fan triangulation
            verts = [v.index for v in face.verts]
            for j in range(1, len(verts) - 1):
                faces_tri.append([verts[0], verts[j], verts[j + 1]])

    mesh_data.faces = np.array(faces_tri, dtype=np.int64) if faces_tri else np.zeros((0, 3), dtype=np.int64)

    # Extract sharp edges
    for edge in bm.edges:
        if not edge.smooth:
            v0, v1 = edge.verts[0].index, edge.verts[1].index
            mesh_data.sharp_edges.add((min(v0, v1), max(v0, v1)))

    return mesh_data
