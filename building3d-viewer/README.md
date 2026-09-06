# Building3D — Phase 2 Viewer

React + Three.js viewer for your existing Phase 2 outputs. No backend, no GPU,
no `.pt` models — it reads the 100 pre-computed predictions as static files.

## Quick start

```bash
# 1. from your Phase 2 project root (where phase2_latest_outputs lives),
#    copy this viewer folder somewhere and cd into it, then:
pip install numpy          # only dependency of the prep script
python scripts/prepare_data.py \
    /path/to/phase2_latest_outputs/phase2_outputs/meshes \
    public/data/buildings

# 2. install & run
npm install
npm run dev
```

Open the printed URL (usually http://localhost:5173).

## What you should see

- Left: list of all 100 buildings, click to switch
- Center: 3D viewer (orbit with mouse)
- Bottom: **Wireframe / Final Mesh / Overlay** toggles + **Reset View**
- Bottom right: corner/edge counts and mean confidence scores

Wireframe colors encode edge confidence: red = low, green = high.
Corners are shown as yellow points.

## Data layout

```
public/data/
├── buildings.json            # index: [{id, n_corners, n_edges}, ...]
└── buildings/
    ├── 1020.json             # corners, edges, corner_scores, edge_scores
    ├── 1020_mesh.obj         # final reconstructed mesh
    └── ...
```

The `.json` files are generated from `prediction.npz` by `scripts/prepare_data.py`.
Re-run the script whenever you regenerate predictions.

## Stage B (not implemented yet)

The raw 2048-point input clouds are NOT in prediction.npz. To add the
"raw points -> corners -> wireframe -> mesh" pipeline view, locate the
Phase 2 point cache, export each building's points as JSON (same prep
script pattern), and add a Points layer to `Viewer.jsx`.
