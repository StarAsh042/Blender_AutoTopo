"""Mesh data conversion between Blender Mesh and NumPy arrays."""

import numpy as np
from typing import Tuple, Optional, Dict, Any
import bmesh
import bpy
from mathutils import Matrix, Vector

from ..utils.logger import logger
from ..utils.math_utils import loop_normals_are_trustworthy, plan_loop_normal_repair


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


def _read_loop_normals(mesh) -> np.ndarray:
    """Return the normals Blender will actually shade with, one per loop.

    Prefers ``corner_normals``, which is the only read path that agrees with the
    shaded result on every build. 3.6 ships both the legacy and the modern API,
    and its legacy pair, ``calc_normals_split()`` plus
    ``loops.foreach_get("normal")``, intermittently reports uninitialised memory
    or stale zeros on a mesh that was just written. Reading through it made the
    repair below see garbage and write that garbage back into the mesh, which is
    the broken surface reported on 3.6. See issue #8.

    Call this only once the object is linked and the view layer updated: before
    that even ``corner_normals`` is empty.
    """
    corners = getattr(mesh, "corner_normals", None)
    if corners is not None and len(corners) == len(mesh.loops):
        return np.array([tuple(c.vector) for c in corners], dtype=np.float64)

    if hasattr(mesh, "calc_normals_split"):
        # 2.9-3.4: no corner normal cache, but the split cache must exist first.
        mesh.calc_normals_split()
        return np.array([tuple(loop.normal) for loop in mesh.loops], dtype=np.float64)

    out = np.zeros((len(mesh.loops), 3), dtype=np.float64)
    mesh.loops.foreach_get("normal", out.ravel())
    return out


def _repair_unrepresentable_loop_normals(mesh) -> int:
    """Give loops whose stored normal came back zero their face normal instead.

    Blender before 4.1 stores a custom split normal as a short2 offset from the
    loop's own reference normal, so a normal exactly opposite that reference is
    the singularity of the encoding and decodes as a zero vector. On 4.1+ the
    same thing happens when the vertex normal we were handed is zero because the
    vertex only touches faces the build dropped. Either way the loop has no
    direction and shades as a hole, which is the "degenerate" look reported on
    3.4 (issue #8).

    Runs after the custom normals are written and reads back what Blender
    actually stored, so it touches only loops that lost their normal. Every
    other loop keeps exactly the normal the engine produced.

    Returns the number of loops repaired.
    """
    stored = _read_loop_normals(mesh)
    if not loop_normals_are_trustworthy(stored):
        # Nothing trustworthy to repair against: leave the mesh exactly as it is
        # rather than writing a value we could not read.
        return 0
    face_normals = np.zeros((len(mesh.polygons), 3), dtype=np.float64)
    mesh.polygons.foreach_get("normal", face_normals.ravel())
    face_areas = np.zeros(len(mesh.polygons), dtype=np.float64)
    mesh.polygons.foreach_get("area", face_areas)

    face_of_loop = np.zeros(len(mesh.loops), dtype=np.int64)
    for p in mesh.polygons:
        face_of_loop[p.loop_start:p.loop_start + p.loop_total] = p.index

    repaired, count = plan_loop_normal_repair(
        stored, face_of_loop, face_normals, face_areas
    )
    if count == 0:
        return 0  # the broken loops all sit on faces with no direction either

    mesh.normals_split_custom_set([tuple(v) for v in repaired.tolist()])
    logger.warning(
        "Repaired %d loop normal(s) Blender could not store on '%s'",
        count, mesh.name,
    )
    return count


def _is_zero_area(vertices: np.ndarray, face: Tuple[int, ...]) -> bool:
    """True when a polygon encloses no area, so it has no normal direction.

    Uses Newell's method, which sums the cross products of consecutive edges.
    For a quad that is folded flat the two fan triangles cancel exactly, and a
    plain fan cross product would report area that the polygon does not have.
    """
    acc = np.zeros(3, dtype=np.float64)
    count = len(face)
    for i in range(count):
        x0, y0, z0 = vertices[face[i]]
        x1, y1, z1 = vertices[face[(i + 1) % count]]
        acc[0] += (y0 - y1) * (z0 + z1)
        acc[1] += (z0 - z1) * (x0 + x1)
        acc[2] += (x0 - x1) * (y0 + y1)
    return float(acc[0] ** 2 + acc[1] ** 2 + acc[2] ** 2) == 0.0


def mesh_data_to_blender(
    mesh_data: MeshData,
    name: str = "AutoTopo_Output",
    collection: Optional[bpy.types.Collection] = None,
    matrix_world: Optional["Matrix"] = None,
) -> bpy.types.Object:
    """Convert MeshData to a Blender mesh object using bmesh.

    ``mesh_data.vertices`` is in the source object's *local* space, because
    ``blender_to_mesh_data`` extracts local coordinates. Pass the source
    object's ``matrix_world`` as ``matrix_world`` so the result lands on top
    of the input instead of at the world origin at unit scale.

    Args:
        mesh_data: MeshData containing the output mesh
        name: Name for the new object
        collection: Target collection (uses active collection if None)
        matrix_world: Transform to give the new object; identity if None

    Returns:
        The newly created Blender object
    """
    if not mesh_data.validate():
        raise ValueError("Invalid mesh data, cannot create Blender mesh")

    n_verts = mesh_data.n_verts

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

    skipped_faces = 0
    for face_verts in all_output_faces:
        if _is_zero_area(mesh_data.vertices, face_verts):
            # bmesh accepts a sliver whose corners are collinear, but it has no
            # direction to shade with. On 4.1+ that leaves a zero-length custom
            # normal that even the repair below cannot fix, because the face has
            # no normal to lend it. It covers no pixels, so drop it.
            skipped_faces += 1
            continue
        try:
            bm.faces.new([bm_verts[i] for i in face_verts])
        except ValueError:
            # Degenerate or duplicate face: skip it, but count it so the
            # reported face count matches the geometry we actually built.
            skipped_faces += 1

    if skipped_faces:
        logger.warning(
            "Skipped %d degenerate/duplicate faces out of %d while building '%s'",
            skipped_faces, len(all_output_faces), name,
        )

    # Smooth shading: a retopologized surface is meant to read as one smooth
    # shell. Without this every polygon is flat-shaded, which both looks
    # faceted and overrides the custom normals we write below.
    for face in bm.faces:
        face.smooth = True

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
        # Blender 4.1 removed Mesh.use_auto_smooth. From 4.1+ custom split
        # normals are always in effect, so only set the legacy flag when it
        # still exists (Blender 3.x compatibility). See issue #8.
        if hasattr(mesh, "use_auto_smooth"):
            mesh.use_auto_smooth = True
        normals_list = [tuple(n.tolist()) for n in mesh_data.normals]
        mesh.normals_split_custom_set_from_vertices(normals_list)

    # Create object
    obj = bpy.data.objects.new(name, mesh)

    # Vertices are in the source object's local space, so the result needs the
    # source transform or it lands at the origin at unit scale.
    if matrix_world is not None:
        obj.matrix_world = matrix_world

    # Link to collection
    if collection is None:
        collection = bpy.context.collection
    collection.objects.link(obj)

    if mesh_data.normals is not None and len(mesh_data.normals) == n_verts:
        # Only now can the stored normals be read back. Before the object is
        # linked and evaluated, Blender reports either uninitialised memory or an
        # empty cache -- on 3.6 that made this repair read garbage and write it
        # into the mesh. See issue #8.
        bpy.context.view_layer.update()
        _repair_unrepresentable_loop_normals(mesh)

    logger.info(
        f"Created Blender object '{name}': "
        f"{n_verts} vertices, {len(mesh.polygons)} faces"
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
