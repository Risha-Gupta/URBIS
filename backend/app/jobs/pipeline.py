import json, os, time, hashlib
from pathlib import Path
import numpy as np

RESULTS = Path(os.getenv("RESULTS_DIR", "data/results"))
T_LOW, T_ACC = 0.7165, 0.7393
STEP_DELAY = float(os.getenv("STEP_DELAY", "0.8"))   # set 0 in tests
DEFAULT_PARAMS = {"score_thr": 0.7, "passes": 8, "seed": 0, "fail_at": None}

class StageError(Exception): ...

def load_points(path: str) -> np.ndarray:
    p = Path(path)
    pts = np.load(p) if p.suffix == ".npy" else np.loadtxt(p)
    pts = np.asarray(pts, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] < 3: raise StageError("expected an (N,3+) array")
    pts = pts[:, :3]
    if len(pts) < 100: raise StageError(f"only {len(pts)} points; need >= 100")
    if not np.isfinite(pts).all(): raise StageError("NaN/inf in point cloud")
    return pts

class StubPipeline:
    """Replace each method body with Phase 2-4 inference; keep signatures and the ctx dict."""
    def preprocessing(self, ctx):
        pts = load_points(ctx["input_path"])
        idx = np.random.default_rng(ctx["params"]["seed"]).choice(len(pts), 2048, replace=len(pts) < 2048)
        c = pts.mean(0); s = np.abs(pts - c).max() or 1.0
        ctx["pts"] = (pts[idx] - c) / s; ctx["center"], ctx["scale"] = c, s
    def corner_detection(self, ctx):
        k = min(8, len(ctx["pts"])); idx = np.argsort(-ctx["pts"][:, 2])[:k]
        ctx["corners"] = ctx["pts"][idx]
    def edge_prediction(self, ctx):
        n = len(ctx["corners"]); ctx["edges"] = [(i, (i + 1) % n) for i in range(n)]
    def mesh_generation(self, ctx):
        d = RESULTS / ctx["job_id"]; d.mkdir(parents=True, exist_ok=True)
        path = d / f"v{ctx['version_no']}.obj"
        real = ctx["corners"] * ctx["scale"] + ctx["center"]
        with open(path, "w") as f:
            for v in real: f.write(f"v {v[0]} {v[1]} {v[2]}\n")
            for a, b in ctx["edges"]: f.write(f"l {a+1} {b+1}\n")
        ctx["mesh_path"] = str(path)
    def uncertainty_analysis(self, ctx):
        h = hashlib.sha256(f"{ctx['input_path']}{ctx['params']['seed']}{ctx['params']['passes']}".encode()).digest()
        ctx["confidence"] = round(0.45 + 0.5 * (h[0] / 255), 4)
        if ctx["params"]["passes"] >= 16: ctx["confidence"] = min(1.0, ctx["confidence"] + 0.04)
    def correction(self, ctx):
        c = ctx["confidence"]
        ctx["action"] = "ACCEPT" if c >= T_ACC else ("ESCALATE" if c < T_LOW else "ACCEPT_FLAG")