# autotopo_native

Native acceleration core (Rust) for the Blender AutoTopo addon.

The DLL is loaded through `ctypes` by `utils/native.py`; the ABI contract
(symbols, error codes, buffer ownership) is documented in `src/lib.rs`
and locked by the golden-master test `test/test_native_golden.py`.

Kernels:

- `autotopo_sharp_features` — QuadWild `.sharp` edge-incidence export
- `autotopo_max_nearest_distance` — silhouette directed Hausdorff distance

## Build

```
cargo build --release
```
