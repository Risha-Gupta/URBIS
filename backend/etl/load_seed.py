#!/usr/bin/env python3
"""Load the URBIS backend seed bundle (CSV + manifest.json) into PostgreSQL/PostGIS.

Idempotent: everything runs in ONE transaction that truncates and reloads all tables, so a failed
check leaves the previous data untouched.

    python load_seed.py --seed ../seed --dsn postgresql://urbis:urbis@localhost:5432/urbis
"""
import argparse
import csv
import hashlib
import io
import json
import os
import sys
from pathlib import Path

import psycopg

CITY3D_DATASET = "city3d_ahn3"
CITY3D_COLS = ["building_id", "subset", "coverage_class", "num_points", "num_predicted_corners",
               "model_confidence", "min_f1_1m", "action", "is_bad"]
CITY3D_INT_COLS = {"num_points", "num_predicted_corners", "is_bad"}

BUILDINGS_STAGE = ("building_id text, dataset_id text, split text, half text, coverage_class text, num_points int, "
                   "footprint_wkt text, footprint_area_m2 float8, z_min float8, z_max float8, "
                   "footprint_srid int, footprint_source text")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def header(path: Path) -> list[str]:
    with open(path, newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


def table_columns(cur, table: str) -> set[str]:
    """Insertable (non-generated) columns of a table."""
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = %s AND is_generated = 'NEVER'""", (table,))
    return {r[0] for r in cur.fetchall()}


def copy_stream(cur, table: str, cols: list[str], stream, force_null=()):
    opts = "FORMAT csv, HEADER true" + (f", FORCE_NULL ({', '.join(force_null)})" if force_null else "")
    with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN WITH ({opts})") as cp:
        while chunk := stream.read(1 << 20):
            cp.write(chunk)


def copy_csv(cur, table: str, path: Path, force_null=()) -> int:
    cols = header(path)
    unknown = set(cols) - table_columns(cur, table)
    if unknown:
        raise SystemExit(f"{path.name}: columns {sorted(unknown)} do not exist in table {table} (seed/schema drift)")
    with open(path, "rb") as f:
        copy_stream(cur, table, cols, f, force_null)
    return cur.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def load_city3d(cur, path: Path) -> int:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["building_id", "dataset_id"] + CITY3D_COLS[1:])
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("error"):                       # skip rows that failed to score
                continue
            vals = []
            for c in CITY3D_COLS[1:]:
                v = row.get(c, "")
                vals.append(str(int(float(v))) if (c in CITY3D_INT_COLS and v not in ("", None)) else v)
            w.writerow([row["building_id"], CITY3D_DATASET] + vals)
    buf.seek(0)
    cols = ["building_id", "dataset_id"] + CITY3D_COLS[1:]
    copy_stream(cur, "robustness_scores", cols, io.BytesIO(buf.getvalue().encode()))
    return cur.execute("SELECT count(*) FROM robustness_scores").fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", default=os.environ.get("SEED_DIR", "seed"), help="folder with manifest.json and the CSVs")
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL", "postgresql://urbis:urbis@localhost:5432/urbis"))
    ap.add_argument("--city3d", default=None, help="city3d_scores_with_actions.csv (default: <seed>/city3d_scores_with_actions.csv if present)")
    ap.add_argument("--skip-hash-check", action="store_true")
    a = ap.parse_args()

    seed = Path(a.seed)
    manifest = json.loads((seed / "manifest.json").read_text())
    tables = manifest["tables"]
    for name, info in tables.items():
        p = seed / f"{name}.csv"
        if not p.exists():
            raise SystemExit(f"missing {p}")
        if not a.skip_hash_check and sha256(p) != info["sha256"]:
            raise SystemExit(f"{p.name}: sha256 differs from manifest.json (file changed after export)")
    city3d = Path(a.city3d) if a.city3d else seed / "city3d_scores_with_actions.csv"

    with psycopg.connect(a.dsn) as conn:
        cur = conn.cursor()
        cur.execute("""TRUNCATE roof_planes, solar_buildings, evaluation, decisions, uncertainty, reconstructions,
                       buildings, robustness_scores, datasets RESTART IDENTITY CASCADE""")

        copy_csv(cur, "datasets", seed / "datasets.csv")

        # buildings: footprint arrives as WKT text
        cur.execute(f"CREATE TEMP TABLE stg_buildings ({BUILDINGS_STAGE}) ON COMMIT DROP")
        if set(header(seed / "buildings.csv")) != {c.split()[0] for c in BUILDINGS_STAGE.split(", ")}:
            raise SystemExit("buildings.csv columns changed; update BUILDINGS_STAGE in load_seed.py")
        with open(seed / "buildings.csv", "rb") as f:
            copy_stream(cur, "stg_buildings", header(seed / "buildings.csv"), f)
        cur.execute("""INSERT INTO buildings (building_id, dataset_id, split, half, coverage_class, num_points,
                         footprint, footprint_source, footprint_area_m2, z_min, z_max)
                       SELECT building_id, dataset_id, split, half, coverage_class, num_points,
                         ST_GeomFromText(footprint_wkt, footprint_srid), footprint_source, footprint_area_m2, z_min, z_max
                       FROM stg_buildings""")

        copy_csv(cur, "reconstructions", seed / "reconstructions.csv", force_null=("model_path",))

        # uncertainty + decisions are keyed by building_id in the seed; map to recon_id (version 1)
        for table, cols_sql in (("uncertainty", None), ("decisions", None)):
            cols = header(seed / f"{table}.csv")
            ok = table_columns(cur, table)
            unknown = set(cols) - ok - {"building_id"}
            if unknown:
                raise SystemExit(f"{table}.csv: unknown columns {sorted(unknown)}")
            data_cols = [c for c in cols if c != "building_id"]
            cur.execute(f"CREATE TEMP TABLE stg_{table} ON COMMIT DROP AS "
                        f"SELECT NULL::text AS building_id, t.* FROM {table} t WITH NO DATA")
            with open(seed / f"{table}.csv", "rb") as f:
                copy_stream(cur, f"stg_{table}", cols, f)
            n_stage = cur.execute(f"SELECT count(*) FROM stg_{table}").fetchone()[0]
            cur.execute(f"INSERT INTO {table} (recon_id, {', '.join(data_cols)}) "
                        f"SELECT r.recon_id, {', '.join('s.' + c for c in data_cols)} FROM stg_{table} s "
                        f"JOIN reconstructions r ON r.building_id = s.building_id AND r.version = 1")
            if cur.rowcount != n_stage:
                raise SystemExit(f"{table}: {n_stage - cur.rowcount} rows had no matching reconstruction")

        copy_csv(cur, "evaluation", seed / "evaluation.csv")
        copy_csv(cur, "solar_buildings", seed / "solar_buildings.csv")
        copy_csv(cur, "roof_planes", seed / "roof_planes.csv")

        n_city3d = 0
        if city3d.exists():
            n_city3d = load_city3d(cur, city3d)
        else:
            print(f"note: {city3d} not found - robustness_scores left empty")

        # ---- verification: counts, geometry, decisions ----
        expected = {n: i["rows"] for n, i in tables.items()}
        problems = []
        for name, want in expected.items():
            if name == "robustness_scores":
                continue
            got = cur.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            if got != want:
                problems.append(f"{name}: {got} rows, manifest says {want}")
        q = lambda sql: cur.execute(sql).fetchone()[0]
        checks = {
            "invalid footprints": q("SELECT count(*) FROM buildings WHERE NOT ST_IsValid(footprint)"),
            "footprints not SRID 3301": q("SELECT count(*) FROM buildings WHERE ST_SRID(footprint) <> 3301"),
            "null centroids": q("SELECT count(*) FROM buildings WHERE centroid IS NULL OR centroid_wgs84 IS NULL"),
            "reconstructions without a current decision": q(
                "SELECT count(*) FROM reconstructions r WHERE NOT EXISTS "
                "(SELECT 1 FROM decisions d WHERE d.recon_id = r.recon_id AND d.is_current)"),
            "buildings missing from v_building_summary": q(
                "SELECT (SELECT count(*) FROM buildings) - (SELECT count(*) FROM v_building_summary)"),
        }
        problems += [f"{k}: {v}" for k, v in checks.items() if v]
        if problems:
            conn.rollback()
            print("VERIFICATION FAILED - nothing was loaded:\n  " + "\n  ".join(problems))
            return 1
        conn.commit()
        cur.execute("ANALYZE")
        conn.commit()

        print("loaded:", {n: cur.execute(f"SELECT count(*) FROM {n}").fetchone()[0] for n in expected}, "| robustness_scores:", n_city3d)
        print("current actions:", dict(cur.execute(
            "SELECT action, count(*) FROM decisions WHERE is_current GROUP BY 1 ORDER BY 1").fetchall()))
        print("statuses:", dict(cur.execute("SELECT status, count(*) FROM reconstructions GROUP BY 1 ORDER BY 1").fetchall()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
