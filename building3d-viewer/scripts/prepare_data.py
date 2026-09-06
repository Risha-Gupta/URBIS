import json
import shutil
import sys
from pathlib import Path

import numpy as np


PREDICTIONS = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path("scripts/phase2_outputs/predictions2")
)

MESHES = (
    Path(sys.argv[2])
    if len(sys.argv) > 2
    else Path("scripts/phase2_outputs/meshes")
)

DST = (
    Path(sys.argv[3])
    if len(sys.argv) > 3
    else Path("public/data/buildings")
)


def sort_key(p: Path):
    # p is now a building subfolder (e.g. predictions/1001), not a file
    return (0, int(p.name)) if p.name.isdigit() else (1, p.name)


def main():
    if not PREDICTIONS.exists():
        sys.exit(f"Predictions folder not found: {PREDICTIONS}")

    if not MESHES.exists():
        sys.exit(f"Meshes folder not found: {MESHES}")

    DST.mkdir(parents=True, exist_ok=True)

    index = []

    # Each building is a SUBFOLDER inside predictions/, containing prediction.npz
    prediction_files = sorted(
        PREDICTIONS.glob("*/prediction.npz"),
        key=lambda p: sort_key(p.parent)
    )

    print(f"Found {len(prediction_files)} prediction files")
    print(f"Predictions: {PREDICTIONS}")
    print(f"Meshes:      {MESHES}")
    print(f"Output:      {DST}")
    print()

    for i, npz_path in enumerate(prediction_files, start=1):
        building_id = npz_path.parent.name  # folder name, not file stem

        mesh_path = (
            MESHES /
            building_id /
            "building_mesh.obj"
        )

        print(
            f"[{i}/{len(prediction_files)}] "
            f"Processing building {building_id}..."
        )

        try:
            data = np.load(npz_path)

            print(f"  Keys: {data.files}")

            corners_raw = data["corners"].astype(float)
            corners_swapped = corners_raw[:, [0, 2, 1]]  # x, z, y — match writeobj()'s swap

            rec = {
                "id": building_id,
                "corners": corners_swapped.tolist(),
                "corner_scores": data["corner_scores"].astype(float).tolist(),
                "edges": data["edges"].astype(int).tolist(),
            }

            json_path = DST / f"{building_id}.json"

            json_path.write_text(
                json.dumps(rec),
                encoding="utf-8"
            )

            print(f"  \u2713 Prediction converted")
            print(f"    Corners: {len(rec['corners'])}")
            print(f"    Edges:   {len(rec['edges'])}")

            if mesh_path.exists():
                output_mesh = DST / f"{building_id}_mesh.obj"

                shutil.copy2(
                    mesh_path,
                    output_mesh
                )

                print(f"  \u2713 Mesh copied")
            else:
                print(f"  \u26a0 Mesh not found: {mesh_path}")

            index.append({
            "id": building_id,
            "n_corners": len(rec["corners"]),
            "n_edges": len(rec["edges"]),
            "has_mesh": mesh_path.exists(),
        })

        except Exception as e:
            print(f"  \u2717 Failed: {e}")

        print()

    index_path = DST.parent / "buildings.json"

    index_path.write_text(
        json.dumps(index),
        encoding="utf-8"
    )

    print("=" * 50)
    print("Done!")
    print(f"Buildings processed: {len(index)}")
    print(f"Index: {index_path}")
    print(f"Output directory: {DST}")
    print("=" * 50)


if __name__ == "__main__":
    main()