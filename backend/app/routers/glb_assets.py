"""Serve the exported URBIS GLB collection and its spatial manifest."""
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import settings

log = logging.getLogger("urbis.glb")
router = APIRouter(prefix="/assets/glb", tags=["3d assets"])
SAFE_BUILDING_ID = re.compile(r"^[A-Za-z0-9_-]+$")
GLB_DIR = Path(settings.model_dir).resolve() / "glb"
MANIFEST_PATH = Path(settings.model_dir).resolve() / "glb_manifest.json"


@lru_cache(maxsize=1)
def _manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        raise HTTPException(503, "GLB manifest is not installed on this server.")
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.exception("Could not read GLB manifest")
        raise HTTPException(503, "GLB manifest could not be read.")
    if data.get("format") != "URBIS_GLB_EXPORT" or not isinstance(data.get("buildings"), list):
        raise HTTPException(503, "GLB manifest has an unsupported format.")
    return data


@router.get("/manifest", summary="GLB inventory and EPSG:3301 placement metadata")
def get_glb_manifest():
    """Return the complete manifest. GLB coordinates are local offsets from each projected anchor."""
    return _manifest()


@router.get("/{building_id}.glb", summary="Fetch a building GLB by building ID")
def get_glb(building_id: str):
    if not SAFE_BUILDING_ID.fullmatch(building_id):
        raise HTTPException(400, "Invalid building ID.")
    entry = next((b for b in _manifest()["buildings"]
                  if str(b.get("building_id")) == building_id), None)
    if entry is None:
        raise HTTPException(404, f"No GLB is registered for building {building_id!r}.")
    filename = entry.get("glb_filename")
    if not filename or Path(filename).name != filename or not filename.lower().endswith(".glb"):
        raise HTTPException(503, "Invalid GLB filename in manifest.")
    path = (GLB_DIR / filename).resolve()
    if GLB_DIR not in path.parents or not path.is_file():
        raise HTTPException(404, "GLB asset is registered but missing from the server.")
    return FileResponse(path, media_type="model/gltf-binary", filename=filename,
                        headers={"Cache-Control": "public, max-age=86400"})
