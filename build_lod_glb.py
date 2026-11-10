#!/usr/bin/env python
"""URBIS visualisation-geometry builder: outline walls + plane-faceted LiDAR roof, for the whole city.

For each building: outline = OSM polygon if available, else the (trimmed) convex hull of its LiDAR roof
points; walls are extruded from that outline; the roof is piecewise-planar from the Phase 5 roof planes
(flat facets, straight ridges); the floor is closed.  If the roof does not close cleanly the building
falls back to an outline block and says why.  GLB axes match the manifest (x east, y up, z -north).
This is completed *visualisation geometry*, not the model's prediction.

Typical use (everything in one go, installs into the backend folder):
  python build_lod_glb.py --npz-dir <npz folder> --manifest backend\\models\\glb_manifest.json ^
      --planes phase5_roof_planes.csv --osm osm_subset.json --ground-from-manifest --all --install backend\\models
"""
import argparse, json, math, shutil, struct, time
from pathlib import Path
import numpy as np
import shapely
from scipy.spatial import Delaunay, cKDTree
from shapely.geometry import MultiPoint, Polygon
from shapely.geometry.polygon import orient
from shapely.affinity import translate

ROOF_RGB, WALL_RGB, FLOOR_RGB = (0.55, 0.58, 0.63), (0.82, 0.84, 0.87), (0.45, 0.47, 0.50)


def cross2(a, b):
    a, b = np.atleast_2d(a), np.atleast_2d(b)
    return a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]


def clean_polygon(coords, simplify=0.1):
    p = Polygon(coords)
    if not p.is_valid:
        p = p.buffer(0)
    if p.geom_type == "MultiPolygon":
        p = max(p.geoms, key=lambda g: g.area)
    p = Polygon(p.exterior).simplify(simplify, preserve_topology=True)
    if p.geom_type != "Polygon" or p.area < 4:
        return None
    return orient(p, 1.0)


def hull_outline(pxy):
    """Convex hull of the roof points after dropping isolated clutter points."""
    tree = cKDTree(pxy)
    n = np.array([len(x) for x in tree.query_ball_point(pxy, 1.0)])
    keep = pxy[n >= 4]
    if len(keep) < 20:
        keep = pxy
    h = MultiPoint(keep).convex_hull
    return clean_polygon(list(h.exterior.coords), 0.15) if h.geom_type == "Polygon" else None


def densify(poly, max_seg=0.6):
    ring = np.array(poly.exterior.coords)[:-1]
    out = []
    for i in range(len(ring)):
        a, b = ring[i], ring[(i + 1) % len(ring)]
        k = max(1, int(math.ceil(np.linalg.norm(b - a) / max_seg)))
        out += [a + (b - a) * j / k for j in range(k)]
    return np.array(out)


def thin(xy, cell):
    key = np.floor(xy / cell).astype(np.int64)
    _, inv = np.unique(key[:, 0] * 1_000_003 + key[:, 1], return_inverse=True)
    keep = []
    for g in range(inv.max() + 1):
        m = np.where(inv == g)[0]
        c = xy[m].mean(0)
        keep.append(m[np.argmin(((xy[m] - c) ** 2).sum(1))])
    return np.array(keep)


def plane_heights(xy, planes):
    cols = []
    for r in planes:
        az, t = math.radians(r["azimuth_deg"]), math.tan(math.radians(r["tilt_deg"]))
        cols.append(r["mean_z"] - t * ((xy[:, 0] - r["cx"]) * math.sin(az) + (xy[:, 1] - r["cy"]) * math.cos(az)))
    return np.stack(cols, 1)


class RoofField:
    """Piecewise-planar roof: plane of the nearest LiDAR points; lower plane at a ridge, higher in a valley."""

    def __init__(self, pxy, pz, planes, tol=0.5):
        H = plane_heights(pxy, planes)
        lab = np.abs(H - pz[:, None]).argmin(1)
        zs = H[np.arange(len(pz)), lab]
        ok = np.abs(zs - pz) < tol
        self.usable = ok.sum() >= 50
        if self.usable:
            self.xy, self.lab, self.zs = pxy[ok], lab[ok], zs[ok]
            self.tree = cKDTree(self.xy)
        self.planes = planes

    def __call__(self, q, k=9, kc=6, margin=0.15):
        d, i = self.tree.query(q, k=min(k, len(self.xy)))
        d, i = np.atleast_2d(d.T).T, np.atleast_2d(i.T).T
        w = 1.0 / (d + 0.15)
        n, m = len(q), len(self.planes)
        votes = np.zeros((n, m))
        for j in range(i.shape[1]):
            np.add.at(votes, (np.arange(n), self.lab[i[:, j]]), w[:, j])
        H = plane_heights(q, self.planes)
        order = np.argsort(-votes, axis=1)
        a = order[:, 0]
        z = H[np.arange(n), a]
        if m > 1:
            b = order[:, 1]
            close = votes[np.arange(n), b] >= 0.25 * votes[np.arange(n), a]
            zb = H[np.arange(n), b]
            cen = np.array([[p["cx"], p["cy"]] for p in self.planes])
            Hc = plane_heights(cen[b], self.planes)
            ridge = Hc[np.arange(n), a] > Hc[np.arange(n), b]
            z = np.where(close, np.where(ridge, np.minimum(z, zb), np.maximum(z, zb)), z)
        zn = self.zs[i[:, :kc]]
        return np.clip(z, zn.min(1) - margin, zn.max(1) + margin)


def idw(tree, zref, q, k=4):
    d, i = tree.query(q, k=min(k, len(zref)))
    d, i = np.atleast_2d(d.T).T, np.atleast_2d(i.T).T
    w = 1.0 / np.maximum(d, 0.05) ** 2
    return (w * zref[i]).sum(1) / w.sum(1)


def check(V, F):
    d = {}
    for t in F:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            d[(a, b)] = d.get((a, b), 0) + 1
    closed = all(v == 1 and (b, a) in d for (a, b), v in d.items())
    W = V - V.mean(0)
    vol = sum(np.dot(W[t[0]], np.cross(W[t[1]], W[t[2]])) for t in F) / 6.0
    return closed, vol


def assemble(top, ground, tri, nb):
    nv = len(top)
    V = np.vstack([top, np.column_stack([top[:, :2], np.full(nv, ground)])])
    F, C = [], []
    for t in tri:
        a, b, c = top[t]
        t = t if cross2(b[:2] - a[:2], c[:2] - a[:2])[0] > 0 else t[[0, 2, 1]]
        F.append(t); C.append(ROOF_RGB)
        F.append(t[[0, 2, 1]] + nv); C.append(FLOOR_RGB)
    for i in range(nb):
        a, b = i, (i + 1) % nb
        F.append([a + nv, b + nv, b]); C.append(WALL_RGB)
        F.append([a + nv, b, a]); C.append(WALL_RGB)
    return V, np.array(F), np.array(C)


def build_mesh(poly, pxy, pz, ground, cell=0.7, field=None):
    tree = cKDTree(pxy)
    ring = densify(poly)
    inner = poly.buffer(-0.4)
    if field is not None:
        minx, miny, maxx, maxy = inner.bounds if not inner.is_empty else (0, 0, -1, -1)
        gx, gy = np.meshgrid(np.arange(minx, maxx + 1e-9, cell), np.arange(miny, maxy + 1e-9, cell))
        g = np.column_stack([gx.ravel(), gy.ravel()])
        ixy = g[shapely.contains_xy(inner, g[:, 0], g[:, 1])] if len(g) else g
        iz = field(ixy) if len(ixy) else np.zeros(0)
    else:
        inside = shapely.contains_xy(inner, pxy[:, 0], pxy[:, 1]) if not inner.is_empty else np.zeros(len(pxy), bool)
        ixy, iz = pxy[inside], pz[inside]
        if len(ixy) > 3:
            k = thin(ixy, cell)
            ixy, iz = ixy[k], iz[k]
    for _ in range(8):
        nb = len(ring)
        xy = np.vstack([ring, ixy]) if len(ixy) else ring
        zring = field(ring) if field is not None else idw(tree, pz, ring)
        zr = np.maximum(np.concatenate([zring, iz]), ground + 0.5)
        tri = Delaunay(xy).simplices
        cen = xy[tri].mean(1)
        tri = tri[shapely.contains_xy(poly.buffer(1e-6), cen[:, 0], cen[:, 1])]
        p0, p1, p2 = xy[tri[:, 0]], xy[tri[:, 1]], xy[tri[:, 2]]
        tri = tri[np.abs(cross2(p1 - p0, p2 - p0)) > 1e-4]
        have = {(a, b) for t in tri for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))}
        have |= {(b, a) for a, b in have}
        miss = {i for i in range(nb) if (i, (i + 1) % nb) not in have}
        if not miss:
            break
        ring = np.array([p for i in range(nb) for p in ([ring[i]] + ([(ring[i] + ring[(i + 1) % nb]) / 2] if i in miss else []))])
    return assemble(np.column_stack([xy, zr]), ground, tri, nb)


def block_mesh(poly, pxy, pz, ground, field=None):
    ring = np.array(poly.exterior.coords)[:-1]
    zr = field(ring) if field is not None else idw(cKDTree(pxy), pz, ring)
    zr = np.maximum(zr, ground + 0.5)
    index = {tuple(np.round(p, 6)): i for i, p in enumerate(ring)}
    tri = [[index[tuple(np.round(c, 6))] for c in list(g.exterior.coords)[:3]]
           for g in shapely.constrained_delaunay_triangles(poly).geoms]
    return assemble(np.column_stack([ring, zr]), ground, np.array(tri), len(ring))


def build_safe(poly, pxy, pz, ground, cell=0.7, planes=()):
    field = None
    if len(planes):
        rf = RoofField(pxy, pz, planes)
        if rf.usable:
            field = rf
    reason = ""
    try:
        V, F, C = build_mesh(poly, pxy, pz, ground, cell, field)
        closed, vol = check(V, F)
        if closed and vol > 0:
            return V, F, C, ("surface" if field is not None else "surface_raw"), ""
        reason = f"roof mesh not closed (closed={closed}, volume={vol:.1f})"
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"
    try:
        V, F, C = block_mesh(poly, pxy, pz, ground, field)
        closed, vol = check(V, F)
        return V, F, C, ("block" if closed and vol > 0 else "failed"), reason
    except Exception as e:
        return None, None, None, "failed", reason + f" | block: {type(e).__name__}: {e}"


def write_glb(path, V, F, C, ground):
    P = np.column_stack([V[:, 0], V[:, 2] - ground, -V[:, 1]])
    T = P[F]
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    pos = T.reshape(-1, 3).astype("<f4")
    nor = np.repeat(n, 3, axis=0).astype("<f4")
    col = np.repeat(C, 3, axis=0).astype("<f4")
    blob = pos.tobytes() + nor.tobytes() + col.tobytes()
    L = pos.nbytes
    js = {
        "asset": {"version": "2.0", "generator": "URBIS outline+LiDAR builder"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "COLOR_0": 2}, "material": 0}]}],
        "materials": [{"name": "URBIS_LOD_Material", "doubleSided": True,
                       "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "roughnessFactor": 0.85, "metallicFactor": 0.0}}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [{"buffer": 0, "byteOffset": i * L, "byteLength": L, "target": 34962} for i in range(3)],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(pos), "type": "VEC3", "min": pos.min(0).tolist(), "max": pos.max(0).tolist()},
            {"bufferView": 1, "componentType": 5126, "count": len(pos), "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": len(pos), "type": "VEC3"}],
    }
    j = json.dumps(js, separators=(",", ":")).encode()
    j += b" " * (-len(j) % 4)
    blob += b"\0" * (-len(blob) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(j) + 8 + len(blob)))
        f.write(struct.pack("<II", len(j), 0x4E4F534A) + j)
        f.write(struct.pack("<II", len(blob), 0x004E4942) + blob)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npz-dir", required=True)
    ap.add_argument("--manifest", required=True, help="backend/models/glb_manifest.json")
    ap.add_argument("--planes", required=True, help="phase5_roof_planes.csv")
    ap.add_argument("--osm", help="osm_subset.json (optional; used where a building has an OSM outline)")
    ap.add_argument("--ids", nargs="+")
    ap.add_argument("--all", action="store_true", help="every building in the manifest")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ground-from-manifest", action="store_true")
    ap.add_argument("--out", default="lod_glb")
    ap.add_argument("--install", help="backend/models folder: copies GLBs to <dir>/glb and merges the manifest")
    ap.add_argument("--eave", type=float, default=3.0)
    ap.add_argument("--cell", type=float, default=0.7)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(exist_ok=True, parents=True)
    osm = json.load(open(a.osm)) if a.osm else {}
    full = json.load(open(a.manifest))
    man = {str(b["building_id"]): b for b in full["buildings"]}
    ids = [str(i) for i in a.ids] if a.ids else list(man)
    if a.limit:
        ids = ids[:a.limit]
    import pandas as pd
    pl = pd.read_csv(a.planes); pl["building_id"] = pl["building_id"].astype(str)
    pl = pl[~pl["ground_like"]]
    by_bid = {k: v.to_dict("records") for k, v in pl.groupby("building_id")}
    stats, done, t0 = {}, [], time.time()
    for n, bid in enumerate(ids, 1):
        entry = man.get(bid)
        npz = Path(a.npz_dir) / f"{bid}.npz"
        if entry is None or not npz.exists():
            stats["skipped"] = stats.get("skipped", 0) + 1
            print(bid, "skipped (no manifest entry)" if entry is None else "skipped (no npz)"); continue
        try:
            z = np.load(npz)
            pts = z["points"][:, :3] * float(z["scale"]) + z["center"]
            ax, ay = entry["anchor"]["easting"], entry["anchor"]["northing"]
            local = pts[:, :2] - [ax, ay]
            poly, used = None, "hull"
            if bid in osm:
                p = clean_polygon(osm[bid]["osm"])
                if p is not None:
                    p = translate(p, -ax, -ay)
                    if shapely.contains_xy(p.buffer(1.0), local[:, 0], local[:, 1]).mean() >= 0.9:
                        poly, used = p, "osm"
            if poly is None:
                poly = hull_outline(local)
            if poly is None:
                stats["no_outline"] = stats.get("no_outline", 0) + 1
                print(bid, "no usable outline"); continue
            ground = float(entry["anchor"]["elevation"]) if a.ground_from_manifest else float(np.percentile(pts[:, 2], 1)) - a.eave
            planes = [dict(r) for r in by_bid.get(bid, [])]
            for r in planes:
                r["cx"] -= ax; r["cy"] -= ay
            V, F, C, quality, reason = build_safe(poly, local, pts[:, 2], ground, a.cell, planes)
        except Exception as e:
            stats["error"] = stats.get("error", 0) + 1
            print(bid, "ERROR", type(e).__name__, e); continue
        stats[quality] = stats.get(quality, 0) + 1
        if quality == "failed":
            print(dict(id=bid, quality=quality, reason=reason)); continue
        closed, vol = check(V, F)
        write_glb(out / f"{bid}.glb", V, F, C, ground)
        entry.update(vertices=len(V), faces=len(F), watertight=bool(closed), winding_consistent=bool(closed),
                     has_vertex_normals=True, geometry_source="outline+lidar_roof_surface", geometry_quality=quality)
        done.append(bid)
        if quality != "surface" or len(ids) <= 40:
            print(dict(id=bid, quality=quality, outline=used, planes=len(planes), verts=len(V), tris=len(F),
                       watertight=bool(closed), **({"fallback_reason": reason} if reason else {})))
        elif n % 200 == 0:
            print(f"{n}/{len(ids)} done, {time.time() - t0:.0f}s", stats)
    json.dump(full, open(out / "glb_manifest_patched.json", "w"))
    print("RESULT", stats, f"built={len(done)} in {time.time() - t0:.0f}s")
    if a.install:
        dest = Path(a.install)
        (dest / "glb").mkdir(parents=True, exist_ok=True)
        for bid in done:
            shutil.copy2(out / f"{bid}.glb", dest / "glb" / f"{bid}.glb")
        shutil.copy2(out / "glb_manifest_patched.json", dest / "glb_manifest.json")
        print("installed", len(done), "GLBs and the manifest into", dest)


if __name__ == "__main__":
    main()
