"""Benchmark + byte-equivalence check for engines/obj_io.py.

Compares the new vectorized write_obj/read_obj against the previous
``np.char.mod`` / per-line implementations (inlined here as *_old) on a
600k-face and a 1M-face mesh, and asserts the emitted bytes are
identical. Run::

    python scripts/bench_obj_io.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OBJ_IO = os.path.join(_ROOT, "engines", "obj_io.py")


def _load_new():
    spec = importlib.util.spec_from_file_location("_obj_io_new", _OBJ_IO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── previous implementations (verbatim) ──
def write_obj_old(filepath, vertices, faces):
    verts = np.asarray(vertices, dtype=np.float64)
    with open(filepath, 'w') as f:
        f.write("# AutoTopo export\n")
        cols = [np.char.mod('%.7f', verts[:, j]) for j in range(3)]
        vlines = np.char.add(np.char.add(cols[0], ' '),
                             np.char.add(cols[1], np.char.add(' ', cols[2])))
        f.write('\n'.join('v ' + s for s in vlines.tolist()))
        f.write('\n')
        if len(faces) == 0:
            return
        try:
            arr = np.asarray(faces)
        except ValueError:
            arr = np.asarray(faces, dtype=object)
        if arr.dtype == object:
            for face in faces:
                idx = ' '.join(str(int(i) + 1) for i in face)
                f.write(f"f {idx}\n")
            return
        idx = arr.astype(np.int64) + 1
        cols = [np.char.mod('%d', idx[:, j]) for j in range(idx.shape[1])]
        flines = cols[0]
        for c in cols[1:]:
            flines = np.char.add(np.char.add(flines, ' '), c)
        f.write('\n'.join('f ' + s for s in flines.tolist()))
        f.write('\n')


def read_obj_old(filepath):
    vertices = []
    faces = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            tag = parts[0]
            if tag == 'v' and len(parts) >= 4:
                vertices.append((float(parts[1]), float(parts[2]),
                                 float(parts[3])))
            elif tag == 'f' and len(parts) >= 4:
                face = []
                n_verts = len(vertices)
                for token in parts[1:]:
                    idx_str = token.split('/')[0]
                    idx = int(idx_str)
                    if idx < 0:
                        idx = n_verts + idx
                    else:
                        idx = idx - 1
                    face.append(idx)
                if len(face) >= 3:
                    faces.append(tuple(face))
    if vertices:
        vert_arr = np.array(vertices, dtype=np.float64)
    else:
        vert_arr = np.zeros((0, 3), dtype=np.float64)
    return vert_arr, faces


def _read_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


def make_mesh(n_faces, seed=0):
    rng = np.random.default_rng(seed)
    n_verts = n_faces + 2
    verts = rng.standard_normal((n_verts, 3)) * 123.456
    # inject edge-ish values
    verts[0] = [0.0, -0.0, 1e-9]
    verts[1] = [1e18, -1e18, 123456789.1234567]
    idx = rng.integers(0, n_verts, size=(n_faces, 4))
    return verts, idx


def check_bytes(name, verts, faces):
    d = tempfile.mkdtemp(prefix="bench_obj_")
    p_old = os.path.join(d, "old.obj")
    p_new = os.path.join(d, "new.obj")
    write_obj_old(p_old, verts, faces)
    NEW.write_obj(p_new, verts, faces)
    b_old, b_new = _read_bytes(p_old), _read_bytes(p_new)
    ok = b_old == b_new
    print(f"  [bytes] {name}: {'IDENTICAL' if ok else '*** DIFFER ***'} "
          f"({len(b_new)} bytes)")
    if not ok:
        for i, (a, b) in enumerate(zip(b_old, b_new)):
            if a != b:
                print(f"    first diff at {i}: old={b_old[i:i+40]!r} "
                      f"new={b_new[i:i+40]!r}")
                break
        raise SystemExit("BYTE MISMATCH")
    return d, p_new


def bench(n_faces):
    print(f"\n=== {n_faces:,} faces ===")
    verts, faces = make_mesh(n_faces)

    d, p_new = check_bytes(f"{n_faces} uniform quads", verts, faces)

    # write timing
    t = time.perf_counter(); write_obj_old(p_new + ".o", verts, faces)
    t_old = time.perf_counter() - t
    t = time.perf_counter(); NEW.write_obj(p_new + ".n", verts, faces)
    t_new = time.perf_counter() - t
    print(f"  [write] old={t_old:.3f}s  new={t_new:.3f}s  "
          f"speedup={t_old / max(t_new, 1e-9):.1f}x")

    # read timing
    t = time.perf_counter(); rv, rf = read_obj_old(p_new)
    tr_old = time.perf_counter() - t
    t = time.perf_counter(); rv2, rf2 = NEW.read_obj(p_new)
    tr_new = time.perf_counter() - t
    assert rv.shape == rv2.shape and np.allclose(rv, rv2), "read vertex mismatch"
    assert rf == rf2, "read face mismatch"
    print(f"  [read ] old={tr_old:.3f}s  new={tr_new:.3f}s  "
          f"speedup={tr_old / max(tr_new, 1e-9):.1f}x  (faces={len(rf)})")

    for p in (p_new, p_new + ".o", p_new + ".n"):
        try:
            os.remove(p)
        except OSError:
            pass
    shutil.rmtree(d, ignore_errors=True)


def check_mixed():
    print("\n=== mixed tri/quad/n-gon byte-equivalence ===")
    verts = np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                      [0, 0, 1], [1, 1, 1]], dtype=np.float64)
    faces = [(0, 1, 2, 3), (0, 1, 4), (0, 1, 2, 3, 4, 5)]
    d, _ = check_bytes("mixed", verts, faces)
    shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    NEW = _load_new()
    print("numpy", np.__version__)
    check_mixed()
    bench(600_000)
    bench(1_000_000)
    print("\nALL BYTE-EQUIVALENCE CHECKS PASSED")
