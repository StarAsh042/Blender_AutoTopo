"""Minimal OBJ file read/write utilities.

Pure Python, no bpy dependency — safe to use from background threads.
Supports arbitrary polygon faces (triangles, quads, n-gons).
"""

import numpy as np
from typing import List, Tuple

# Rows formatted per batch when building the OBJ text. Large enough to
# amortize the join, small enough to bound peak memory for 1M+ meshes.
_CHUNK = 1 << 16


def write_obj(filepath: str, vertices: np.ndarray, faces) -> None:
    """Write a mesh to an OBJ file.

    Vectorized for large meshes (hundreds of thousands of faces): the
    vertex and uniform-arity face blocks are formatted in chunked Python
    string batches and streamed to the file, instead of routing every
    coordinate through ``np.char.mod`` (which materialised several
    full-length numpy string arrays and took ~6.5s at 600k faces).

    The emitted bytes are identical to the previous implementation.

    Args:
        filepath: Output file path (.obj)
        vertices: (N, 3) vertex position array
        faces: List of face tuples or (M, k) index array (0-based)
    """
    verts = np.asarray(vertices, dtype=np.float64)
    with open(filepath, 'w') as f:
        f.write("# AutoTopo export\n")

        # Vertex block
        _write_vertex_block(f, verts)

        if len(faces) == 0:
            return

        try:
            arr = np.asarray(faces)
        except ValueError:
            # numpy >= 1.24 refuses to build an array from inhomogeneous
            # face lists (mixed tri/quad is a normal output here), so fall
            # back to a 1-D object array to reach the mixed-arity path below.
            arr = np.asarray(faces, dtype=object)
        if arr.dtype == object:
            # Mixed-arity fallback (tri/quad mixed meshes)
            for face in faces:
                idx = ' '.join(str(int(i) + 1) for i in face)
                f.write(f"f {idx}\n")
            return

        # OBJ indices are 1-based
        idx = arr.astype(np.int64) + 1
        _write_face_block(f, idx)


def _write_vertex_block(f, verts: np.ndarray) -> None:
    """Write the ``v`` lines (``%.7f``), byte-identical to np.char.mod.

    Lines are emitted one chunk at a time so peak memory stays bounded
    for 1M+ vertex meshes.
    """
    n = len(verts)
    if n == 0:
        f.write("\n")
        return
    xs = verts[:, 0].tolist()
    ys = verts[:, 1].tolist()
    zs = verts[:, 2].tolist()
    for s in range(0, n, _CHUNK):
        e = s + _CHUNK
        f.write('\n'.join(
            'v %.7f %.7f %.7f' % (x, y, z)
            for x, y, z in zip(xs[s:e], ys[s:e], zs[s:e])
        ))
        f.write('\n')


def _write_face_block(f, idx: np.ndarray) -> None:
    """Write the ``f`` lines (``%d``), byte-identical to np.char.mod."""
    n = len(idx)
    if n == 0:
        f.write("\n")
        return
    for s in range(0, n, _CHUNK):
        rows = idx[s:s + _CHUNK].tolist()
        f.write('\n'.join('f ' + ' '.join(map(str, row)) for row in rows))
        f.write('\n')


def read_obj(filepath: str) -> Tuple[np.ndarray, List[tuple]]:
    """Read a mesh from an OBJ file.

    Only vertex positions and faces are parsed (normals/UVs ignored).
    Faces with v/vt/vn style indices are handled by taking the first
    component. Negative indices (relative to end) are resolved.

    Args:
        filepath: Input file path (.obj)

    Returns:
        Tuple of (vertices as (N,3) float64 array, list of face tuples
        with 0-based indices)
    """
    vertices = []
    faces = []

    with open(filepath, 'r') as f:
        for line in f:
            # ``split()`` already trims all whitespace (incl. the trailing
            # newline / CR), so the former per-line ``strip()`` is dropped.
            parts = line.split()
            if not parts:
                continue
            tag = parts[0]
            if tag == 'v' and len(parts) >= 4:
                vertices.append((
                    float(parts[1]),
                    float(parts[2]),
                    float(parts[3]),
                ))
            elif tag == 'f' and len(parts) >= 4:
                n_verts = len(vertices)
                face = []
                for token in parts[1:]:
                    # Handle v, v/vt, v/vt/vn, v//vn formats without
                    # building an intermediate list per token.
                    slash = token.find('/')
                    idx = int(token if slash < 0 else token[:slash])
                    if idx < 0:
                        idx += n_verts  # Resolve negative index
                    else:
                        idx -= 1  # Convert to 0-based
                    face.append(idx)
                if len(face) >= 3:
                    faces.append(tuple(face))

    if vertices:
        vert_arr = np.array(vertices, dtype=np.float64)
    else:
        vert_arr = np.zeros((0, 3), dtype=np.float64)

    return vert_arr, faces
