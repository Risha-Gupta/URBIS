import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Cartesian3,
  Color,
  HeadingPitchRange,
  Math as CesiumMath,
  Matrix4,
  Model,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  Transforms,
  UrlTemplateImageryProvider,
  Viewer,
  CameraEventType,
} from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import {
  Activity,
  AlertCircle,
  Building2,
  ChevronDown,
  ChevronUp,
  Crosshair,
  Download,
  Layers3,
  LoaderCircle,
  MapPin,
  Minus,
  Plus,
  RotateCcw,
  RotateCw,
  Search,
  X,
} from 'lucide-react';
import { getBuildings, type Building } from '../services/api/urbisApi';
import { api } from '../services/api/axios';

type ManifestBuilding = {
  building_id: string;
  glb_filename: string;
  anchor: {
    easting: number;
    northing: number;
    elevation: number;
    lon?: number;
    lat?: number;
  };
  vertices: number;
  faces: number;
  watertight: boolean;
};

type Manifest = {
  glb_count: number;
  source_crs: string;
  buildings: ManifestBuilding[];
};

type ColorMode = 'confidence' | 'decision';

const API_ROOT = (api.defaults.baseURL || 'http://localhost:8000').replace(/\/$/, '');

const PAGE_SIZE = 1000; // backend caps limit at 1000
const MAX_PAGES = 20;
const LOW_DETAIL_VERTICES = 30;

const CONFIDENCE_LEGEND = [
  { color: '#65c79a', label: 'High (85%+)' },
  { color: '#e5a14b', label: 'Moderate (60-85%)' },
  { color: '#e5605b', label: 'Low (<60%)' },
  { color: '#64748b', label: 'No score' },
];

const DECISION_LEGEND = [
  { color: '#65c79a', label: 'Accepted' },
  { color: '#65a9c8', label: 'Accepted with flag' },
  { color: '#e5a14b', label: 'Escalate' },
];

function confidenceOf(building: Building): number | null {
  if (typeof building.combined_confidence === 'number') return building.combined_confidence;
  if (typeof building.model_confidence === 'number') return building.model_confidence;
  return null;
}

function markerColor(building: Building, mode: ColorMode): string {
  if (mode === 'confidence') {
    const c = confidenceOf(building);
    if (c === null) return '#64748b';
    if (c >= 0.85) return '#65c79a';
    if (c >= 0.6) return '#e5a14b';
    return '#e5605b';
  }
  const action = String(building.action || '').toUpperCase();
  if (action === 'ESCALATE') return '#e5a14b';
  if (action === 'ACCEPT_FLAG') return '#65a9c8';
  return '#65c79a';
}

// The backend caps `limit` at 1000, so page through the whole inventory.
async function getAllBuildings(): Promise<Building[]> {
  const seen = new Set<string>();
  const all: Building[] = [];

  for (let page = 0; page < MAX_PAGES; page += 1) {
    const rows = await getBuildings({ limit: PAGE_SIZE, offset: page * PAGE_SIZE });
    let added = 0;

    rows.forEach((row) => {
      const id = String(row.building_id);
      if (!seen.has(id)) {
        seen.add(id);
        all.push(row);
        added += 1;
      }
    });

    // Stop on a short page, or if the server ignored `offset` and repeated rows.
    if (rows.length < PAGE_SIZE || added === 0) break;
  }

  return all;
}

export default function Explorer() {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const modelRef = useRef<Model | null>(null);
  const buildingsRef = useRef<Building[]>([]);
  const cameraTargetRef = useRef<Cartesian3 | null>(null);
  const cameraOrbitRef = useRef({
    heading: CesiumMath.toRadians(25),
    pitch: CesiumMath.toRadians(-38),
    range: 115,
  });

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [selected, setSelected] = useState<Building | null>(null);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [modelLoading, setModelLoading] = useState(false);
  const [showInventory, setShowInventory] = useState(true);
  const [showModels, setShowModels] = useState(true);
  const [colorMode, setColorMode] = useState<ColorMode>('confidence');
  const [actionFilter, setActionFilter] = useState('ALL');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [only3d, setOnly3d] = useState(false);
  const [error, setError] = useState('');
  const [modelError, setModelError] = useState('');

  // Load building inventory (all pages) and GLB manifest.
  useEffect(() => {
    let active = true;

    Promise.all([
      getAllBuildings(),
      api.get<Manifest>('/assets/glb/manifest').then((response) => response.data),
    ])
      .then(([rows, data]) => {
        if (!active) return;

        const normalized: Manifest = {
          ...data,
          glb_count: data.glb_count ?? data.buildings.length,
        };

        setBuildings(rows);
        buildingsRef.current = rows;
        setManifest(normalized);
        setError('');

        console.log('Buildings loaded:', rows.length);
        console.log('GLB models available:', normalized.glb_count);
      })
      .catch((err: unknown) => {
        if (!active) return;

        setError(
          err instanceof Error
            ? err.message
            : 'Could not load city inventory. Check the backend.'
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  // Initialize Cesium viewer.
  useEffect(() => {
    if (!hostRef.current || viewerRef.current) return;

    const viewer = new Viewer(hostRef.current, {
      animation: false,
      timeline: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      baseLayerPicker: false,
      fullscreenButton: false,
      infoBox: false,
      selectionIndicator: false,
      terrainProvider: undefined,
    });
    const controller = viewer.scene.screenSpaceCameraController;

    controller.enableRotate = false;
    controller.enableTilt = false;
    controller.enableLook = false;
    controller.enableTranslate = true;

    controller.enableZoom = true;

    controller.translateEventTypes = [CameraEventType.LEFT_DRAG];

    // Disable right-drag camera movement.
    controller.rotateEventTypes = [];
    controller.tiltEventTypes = [];
    controller.lookEventTypes = [];
    viewer.imageryLayers.removeAll();

    viewer.imageryLayers.addImageryProvider(
      new UrlTemplateImageryProvider({
        url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        credit: '© OpenStreetMap contributors',
        maximumLevel: 19,
      })
    );

    viewer.scene.globe.depthTestAgainstTerrain = false;
    viewer.scene.backgroundColor = Color.fromCssColorString('#101a24');

    viewer.camera.setView({
      destination: Cartesian3.fromDegrees(25.0, 58.8, 90000),
    });

    viewerRef.current = viewer;

    const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);

    handler.setInputAction(
      (movement: { position: Cartesian3 }) => {
        const picked = viewer.scene.pick(movement.position) as
          | {
              id?: {
                properties?: {
                  building_id?: {
                    getValue: (time: unknown) => unknown;
                  };
                };
              };
            }
          | undefined;

        const id = picked?.id?.properties?.building_id?.getValue(
          viewer.clock.currentTime
        );

        if (id === undefined || id === null) return;

        const record = buildingsRef.current.find(
          (building) => String(building.building_id) === String(id)
        );

        if (record) setSelected(record);
      },
      ScreenSpaceEventType.LEFT_CLICK
    );

    return () => {
      handler.destroy();
      viewer.destroy();
      viewerRef.current = null;
    };
  }, []);

  const glbIds = useMemo(
    () =>
      new Set(
        manifest?.buildings.map((building) => String(building.building_id)) || []
      ),
    [manifest]
  );

  const manifestById = useMemo(() => {
    const map = new Map<string, ManifestBuilding>();
    manifest?.buildings.forEach((building) =>
      map.set(String(building.building_id), building)
    );
    return map;
  }, [manifest]);

  const statusOptions = useMemo(
    () =>
      Array.from(
        new Set(
          buildings
            .map((building) => String(building.status || '').trim())
            .filter(Boolean)
        )
      ).sort(),
    [buildings]
  );

  // Apply decision / processing-status / 3D-only filters.
  const filteredBuildings = useMemo(
    () =>
      buildings.filter((building) => {
        if (
          actionFilter !== 'ALL' &&
          String(building.action || '').toUpperCase() !== actionFilter
        ) {
          return false;
        }
        if (statusFilter !== 'ALL' && String(building.status || '') !== statusFilter) {
          return false;
        }
        if (only3d && !glbIds.has(String(building.building_id))) return false;
        return true;
      }),
    [buildings, actionFilter, statusFilter, only3d, glbIds]
  );

  // Render building inventory markers.
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !buildings.length) return;

    viewer.entities.removeAll();

    if (!showInventory) return;

    const validBuildings = filteredBuildings.filter(
      (building) =>
        typeof building.lon === 'number' &&
        typeof building.lat === 'number'
    );

    validBuildings.forEach((building) => {
      viewer.entities.add({
        id: `building-${building.building_id}`,
        position: Cartesian3.fromDegrees(building.lon!, building.lat!, 3),
        point: {
          pixelSize:
            String(selected?.building_id) === String(building.building_id)
              ? 11
              : 5,
          color: Color.fromCssColorString(markerColor(building, colorMode)),
          outlineColor: Color.fromCssColorString('#10202b'),
          outlineWidth: 1,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        properties: {
          building_id: String(building.building_id),
        },
        description: `Building ${building.building_id}`,
      });
    });

    viewer.scene.requestRender();
  }, [buildings, filteredBuildings, showInventory, colorMode, selected?.building_id]);

  // Load the selected building's GLB model.
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;

    let cancelled = false;
    let currentModel: Model | null = null;
    let removeReadyListener: (() => void) | undefined;
    let removeErrorListener: (() => void) | undefined;

    const cleanupModel = () => {
      removeReadyListener?.();
      removeErrorListener?.();

      if (currentModel) {
        if (viewer.scene.primitives.contains(currentModel)) {
          viewer.scene.primitives.remove(currentModel);
        } else if (!currentModel.isDestroyed()) {
          currentModel.destroy();
        }
      }

      if (modelRef.current === currentModel) {
        modelRef.current = null;
      }
    };

    if (modelRef.current) {
      viewer.scene.primitives.remove(modelRef.current);
      modelRef.current = null;
    }

    cameraTargetRef.current = null;

    if (!selected || !manifest || !showModels) {
      setModelLoading(false);
      setModelError('');
      return;
    }

    const entry = manifest.buildings.find(
      (building) =>
        String(building.building_id) === String(selected.building_id)
    );

    if (!entry) {
      setModelLoading(false);
      setModelError('No GLB reconstruction is available for this building.');

      // Still fly to the building so the selection is visible on the map.
      if (typeof selected.lon === 'number' && typeof selected.lat === 'number') {
        viewer.camera.lookAtTransform(Matrix4.IDENTITY);
        viewer.camera.flyTo({
          destination: Cartesian3.fromDegrees(selected.lon, selected.lat, 400),
          duration: 1.2,
        });
      }
      return;
    }

    setModelLoading(true);
    setModelError('');

    const loadModel = async () => {
      try {
        const lon = entry.anchor.lon;
        const lat = entry.anchor.lat;

        if (
          typeof lon !== 'number' ||
          typeof lat !== 'number' ||
          !Number.isFinite(lon) ||
          !Number.isFinite(lat)
        ) {
          throw new Error(
            `Manifest coordinates are missing for building ${entry.building_id}. Regenerate the manifest with lon and lat inside anchor.`
          );
        }

        // GLB axes are local east / up / -north, so a plain ENU frame is correct.
        const position = Cartesian3.fromDegrees(lon, lat, 0);
        const modelMatrix = Transforms.eastNorthUpToFixedFrame(position);

        const modelUrl = `${API_ROOT}/assets/glb/${encodeURIComponent(
          entry.glb_filename
        )}?v=${entry.vertices}-${entry.faces}`;

        console.log('Starting GLB load:', {
          buildingId: entry.building_id,
          modelUrl,
          longitude: lon,
          latitude: lat,
          vertices: entry.vertices,
          faces: entry.faces,
        });

        currentModel = await Model.fromGltfAsync({
          url: modelUrl,
          modelMatrix,
          minimumPixelSize: 0,
          maximumScale: 200,
          // Outline the mesh so low-vertex, folded shapes stay readable.
          silhouetteColor: Color.WHITE.withAlpha(0.9),
          silhouetteSize: (entry.vertices ?? 0) < 100 ? 1.5 : 0,
        });

        if (cancelled) {
          currentModel.destroy();
          return;
        }

        const readiness = new Promise<void>((resolve, reject) => {
          if (currentModel!.ready) {
            resolve();
            return;
          }

          removeReadyListener = currentModel!.readyEvent.addEventListener(() => {
            removeReadyListener?.();
            removeErrorListener?.();
            resolve();
          });

          removeErrorListener = currentModel!.errorEvent.addEventListener(
            (modelError) => {
              removeReadyListener?.();
              removeErrorListener?.();
              reject(modelError);
            }
          );
        });

        viewer.scene.primitives.add(currentModel);
        modelRef.current = currentModel;
        viewer.scene.requestRender();

        await readiness;

        if (cancelled) return;

        // Fly in towards the selected building from an angled view.
        const boundingSphere = currentModel.boundingSphere;
        const radius = Math.max(boundingSphere.radius, 5);

        cameraTargetRef.current = boundingSphere.center;
        cameraOrbitRef.current = {
          heading: CesiumMath.toRadians(25),
          pitch: CesiumMath.toRadians(-35),
          range: radius * 3.5,
        };

        viewer.camera.lookAtTransform(Matrix4.IDENTITY);
        viewer.camera.flyToBoundingSphere(boundingSphere, {
          duration: 1.5,
          offset: new HeadingPitchRange(
            cameraOrbitRef.current.heading,
            cameraOrbitRef.current.pitch,
            cameraOrbitRef.current.range
          ),
        });
      } catch (err) {
        console.error('GLB loading failed:', err);

        if (!cancelled) {
          setModelError(
            err instanceof Error
              ? err.message
              : 'Failed to load the GLB model.'
          );
        }
      } finally {
        if (!cancelled) setModelLoading(false);
      }
    };

    loadModel();

    return () => {
      cancelled = true;
      cleanupModel();
    };
  }, [selected, manifest, showModels]);

  // Search buildings by ID (within the active filters).
  const results = useMemo(
    () =>
      filteredBuildings
        .filter((building) =>
          String(building.building_id)
            .toLowerCase()
            .includes(query.trim().toLowerCase())
        )
        .slice(0, 40),
    [filteredBuildings, query]
  );

  const selectBuilding = useCallback((building: Building) => {
    setSelected(building);
  }, []);

  // Apply a camera orbit, then release the camera lock so map panning keeps working.
  const applyOrbit = () => {
    const viewer = viewerRef.current;
    const target = cameraTargetRef.current;

    if (!viewer || !target) return;

    const orbit = cameraOrbitRef.current;

    viewer.camera.lookAt(
      target,
      new HeadingPitchRange(orbit.heading, orbit.pitch, orbit.range)
    );
    viewer.camera.lookAtTransform(Matrix4.IDENTITY);
    viewer.scene.requestRender();
  };

  // Orbit around the selected building.
  const orbitCamera = (
    direction: 'left' | 'right' | 'up' | 'down'
  ) => {
    const orbit = cameraOrbitRef.current;
    const step = CesiumMath.toRadians(8);

    if (direction === 'left') orbit.heading -= step;
    if (direction === 'right') orbit.heading += step;
    if (direction === 'up') {
      orbit.pitch = Math.min(-0.12, orbit.pitch + step);
    }
    if (direction === 'down') {
      orbit.pitch = Math.max(-1.35, orbit.pitch - step);
    }

    applyOrbit();
  };

  const resetCamera = () => {
    const sphere = modelRef.current?.boundingSphere;
    const radius = sphere ? Math.max(sphere.radius, 5) : 30;

    cameraOrbitRef.current = {
      heading: CesiumMath.toRadians(25),
      pitch: CesiumMath.toRadians(-38),
      range: radius * 3.5,
    };

    applyOrbit();
  };

  const loadedBuildingCount = buildings.length;

  const modelCoverage =
    manifest && loadedBuildingCount
      ? ((manifest.glb_count / loadedBuildingCount) * 100).toFixed(1)
      : null;

  const selectedEntry = selected
    ? manifestById.get(String(selected.building_id))
    : undefined;

  const selectedConfidence = selected ? confidenceOf(selected) : null;

  const isLowDetail =
    !!selectedEntry &&
    (selectedEntry.vertices < LOW_DETAIL_VERTICES || !selectedEntry.watertight);

  const legend = colorMode === 'confidence' ? CONFIDENCE_LEGEND : DECISION_LEGEND;

  const fmtPct = (value: unknown) =>
    typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '—';

  return (
    <main className="min-h-screen w-full space-y-5 bg-slate-950 p-4 text-slate-100 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
            Spatial intelligence / digital twin
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-white">
            City Explorer
          </h1>
          <p className="mt-1 max-w-xl text-sm text-slate-400">
            Explore the building inventory and inspect reconstructed 3D assets.
          </p>
        </div>

        <div className="flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-[10px] font-semibold tracking-wider text-emerald-300">
          <span className="h-2 w-2 rounded-full bg-emerald-400" />
          LIVE DATA CONNECTION
        </div>
      </header>

      <section className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <div className="rounded-xl border border-slate-700 bg-slate-900 p-4">
          <span className="text-[10px] font-semibold tracking-widest text-slate-500">
            BUILDINGS LOADED
          </span>
          <strong className="mt-2 block text-2xl font-semibold tabular-nums text-slate-100">
            {loading ? '—' : loadedBuildingCount.toLocaleString()}
          </strong>
        </div>

        <div className="rounded-xl border border-slate-700 bg-slate-900 p-4">
          <span className="text-[10px] font-semibold tracking-widest text-slate-500">
            3D RECONSTRUCTIONS
          </span>
          <strong className="mt-2 block text-2xl font-semibold tabular-nums text-slate-100">
            {manifest ? manifest.glb_count.toLocaleString() : '—'}
          </strong>
        </div>

        <div className="rounded-xl border border-slate-700 bg-slate-900 p-4">
          <span className="text-[10px] font-semibold tracking-widest text-slate-500">
            MODEL COVERAGE
          </span>
          <strong className="mt-2 block text-2xl font-semibold tabular-nums text-slate-100">
            {modelCoverage ? `${modelCoverage}%` : '—'}
          </strong>
        </div>

        <div className="rounded-xl border border-slate-700 bg-slate-900 p-4">
          <span className="text-[10px] font-semibold tracking-widest text-slate-500">
            SELECTED ASSET
          </span>
          <strong className="mt-2 block text-2xl font-semibold tabular-nums text-slate-100">
            {selected ? `#${selected.building_id}` : 'None'}
          </strong>
        </div>
      </section>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">
          <AlertCircle size={16} />
          {error}
        </div>
      )}

      <section className="grid min-h-[680px] grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_390px]">
        <div className="relative min-h-[620px] overflow-hidden rounded-xl border border-slate-700/70 bg-slate-900">
          <div className="absolute inset-x-0 top-0 z-20 flex h-14 items-center justify-between border-b border-slate-700 bg-slate-900/95 px-4">
            <div className="flex items-center gap-2 text-xs font-semibold tracking-wider text-slate-300">
              <MapPin size={16} />
              <span>ESTONIA · BUILDING INVENTORY</span>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                title="Zoom in"
                onClick={() => viewerRef.current?.camera.zoomIn(250)}
                className="rounded-md border border-slate-700 bg-slate-800 p-2 text-slate-300 hover:bg-slate-700"
              >
                <Plus size={16} />
              </button>

              <button
                type="button"
                title="Zoom out"
                onClick={() => viewerRef.current?.camera.zoomOut(250)}
                className="rounded-md border border-slate-700 bg-slate-800 p-2 text-slate-300 hover:bg-slate-700"
              >
                <Minus size={16} />
              </button>

              <button
                type="button"
                title="Reset view"
                onClick={() => {
                  viewerRef.current?.camera.lookAtTransform(Matrix4.IDENTITY);
                  viewerRef.current?.camera.flyHome(1);
                }}
                className="rounded-md border border-slate-700 bg-slate-800 p-2 text-slate-300 hover:bg-slate-700"
              >
                <RotateCcw size={15} />
              </button>
            </div>
          </div>

          <div
            className="absolute inset-0 top-14 bottom-10"
            ref={hostRef}
          >
            {loading && (
              <div className="absolute inset-0 z-30 flex items-center justify-center gap-2 bg-slate-950/70 text-sm text-slate-300">
                <LoaderCircle className="animate-spin" size={22} />
                Loading geospatial inventory…
              </div>
            )}
          </div>

          {/* Camera orbit controls */}
          <div className="absolute bottom-16 right-4 z-30 w-40 rounded-xl border border-slate-600/70 bg-slate-900/95 p-3 shadow-2xl backdrop-blur">
            <div className="mb-2 text-center text-[9px] font-bold tracking-[0.18em] text-slate-400">
              CAMERA ORBIT
            </div>

            <div className="flex flex-col items-center gap-1.5">
              <button
                type="button"
                title="Tilt up"
                onClick={() => orbitCamera('up')}
                disabled={!selected || !cameraTargetRef.current}
                className="rounded-md border border-slate-700 bg-slate-800 p-2 text-slate-300 transition hover:bg-slate-700 hover:text-emerald-300 disabled:opacity-40"
              >
                <ChevronUp size={17} />
              </button>

              <div className="flex gap-2">
                <button
                  type="button"
                  title="Orbit left"
                  onClick={() => orbitCamera('left')}
                  disabled={!selected || !cameraTargetRef.current}
                  className="rounded-md border border-slate-700 bg-slate-800 p-2 text-slate-300 transition hover:bg-slate-700 hover:text-emerald-300 disabled:opacity-40"
                >
                  <RotateCcw size={16} />
                </button>

                <button
                  type="button"
                  title="Orbit right"
                  onClick={() => orbitCamera('right')}
                  disabled={!selected || !cameraTargetRef.current}
                  className="rounded-md border border-slate-700 bg-slate-800 p-2 text-slate-300 transition hover:bg-slate-700 hover:text-emerald-300 disabled:opacity-40"
                >
                  <RotateCw size={16} />
                </button>
              </div>

              <button
                type="button"
                title="Tilt down"
                onClick={() => orbitCamera('down')}
                disabled={!selected || !cameraTargetRef.current}
                className="rounded-md border border-slate-700 bg-slate-800 p-2 text-slate-300 transition hover:bg-slate-700 hover:text-emerald-300 disabled:opacity-40"
              >
                <ChevronDown size={17} />
              </button>
            </div>

            <button
              type="button"
              onClick={resetCamera}
              disabled={!selected || !cameraTargetRef.current}
              className="mt-2 flex w-full items-center justify-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/5 px-2 py-2 text-[11px] font-medium text-emerald-300 transition hover:bg-emerald-500/10 disabled:opacity-40"
            >
              <RotateCcw size={13} />
              Reset angle
            </button>
          </div>

          <div className="absolute inset-x-0 bottom-0 z-20 flex flex-wrap items-center gap-4 border-t border-slate-700 bg-slate-900/95 px-4 py-3 text-[11px] text-slate-400">
            {legend.map((item) => (
              <span key={item.label}>
                <i
                  className="mr-1 inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: item.color }}
                />
                {item.label}
              </span>
            ))}
            <span className="ml-auto">Map data © OpenStreetMap</span>
          </div>

          <div className="absolute left-4 top-[4.5rem] z-20 space-y-3 rounded-xl border border-slate-600/70 bg-slate-900/95 p-3 text-xs text-slate-300 shadow-xl backdrop-blur">
            <div className="flex items-center gap-2 text-[10px] font-bold tracking-widest text-slate-400">
              <Layers3 size={15} />
              MAP LAYERS
            </div>

            <label className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={showInventory}
                onChange={(event) => setShowInventory(event.target.checked)}
              />
              Building inventory
            </label>

            <label className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={showModels}
                onChange={(event) => setShowModels(event.target.checked)}
              />
              3D model on selection
            </label>

            <div className="space-y-1 border-t border-slate-700 pt-2">
              <div className="text-[10px] font-bold tracking-widest text-slate-500">
                COLOUR BY
              </div>
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name="colorMode"
                  checked={colorMode === 'confidence'}
                  onChange={() => setColorMode('confidence')}
                />
                Confidence
              </label>
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name="colorMode"
                  checked={colorMode === 'decision'}
                  onChange={() => setColorMode('decision')}
                />
                Decision
              </label>
            </div>
          </div>
        </div>

        <aside className="flex max-h-[780px] min-h-[620px] flex-col overflow-hidden rounded-xl border border-slate-700/70 bg-slate-900">
          <div className="space-y-3 border-b border-slate-700 p-4">
            <span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
              Asset locator
            </span>

            <h2 className="text-xl font-medium text-slate-100">
              Find a building
            </h2>

            <div className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-400">
              <Search size={15} />
              <input
                className="min-w-0 flex-1 bg-transparent text-sm text-slate-200 outline-none placeholder:text-slate-600"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search building ID…"
              />
              <kbd className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-400">
                {results.length}
              </kbd>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <select
                value={actionFilter}
                onChange={(event) => setActionFilter(event.target.value)}
                className="rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-slate-300 outline-none"
                aria-label="Filter by decision"
              >
                <option value="ALL">All decisions</option>
                <option value="ACCEPT">Accepted</option>
                <option value="ACCEPT_FLAG">Accepted with flag</option>
                <option value="ESCALATE">Escalate</option>
              </select>

              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
                className="rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-slate-300 outline-none"
                aria-label="Filter by processing status"
              >
                <option value="ALL">All statuses</option>
                {statusOptions.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
            </div>

            <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={only3d}
                onChange={(event) => setOnly3d(event.target.checked)}
              />
              Only buildings with a 3D model
              <span className="ml-auto text-slate-500">
                {filteredBuildings.length.toLocaleString()} shown
              </span>
            </label>
          </div>

          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
            {results.map((building) => (
              <button
                key={building.building_id}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left transition hover:bg-slate-800 ${
                  String(selected?.building_id) === String(building.building_id)
                    ? 'bg-slate-800 ring-1 ring-emerald-500/20'
                    : ''
                }`}
                onClick={() => selectBuilding(building)}
              >
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: markerColor(building, colorMode) }}
                />

                <span className="min-w-0 flex-1">
                  <strong className="block text-sm font-medium text-slate-200">
                    Building {building.building_id}
                  </strong>
                  <small className="mt-1 block truncate text-[11px] text-slate-500">
                    {building.action || 'Unclassified'} ·{' '}
                    {building.solar_reliability || 'Solar status unavailable'}
                  </small>
                </span>

                <span
                  className={`rounded-md border px-2 py-1 text-[10px] font-semibold ${
                    glbIds.has(String(building.building_id))
                      ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                      : 'border-slate-700 text-slate-500'
                  }`}
                >
                  {glbIds.has(String(building.building_id)) ? '3D' : '2D'}
                </span>
              </button>
            ))}

            {!loading && results.length === 0 && (
              <p className="p-5 text-center text-sm text-slate-500">
                No buildings match these filters.
              </p>
            )}
          </div>

          {selected && (
            <div className="max-h-[360px] space-y-4 overflow-y-auto border-t border-slate-700 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
                    Selected asset
                  </span>
                  <h3 className="mt-1 text-lg font-medium text-slate-100">
                    Building {selected.building_id}
                  </h3>
                </div>

                <button
                  className="rounded-md border border-slate-700 p-2 text-slate-400 hover:bg-slate-800"
                  onClick={() => setSelected(null)}
                  aria-label="Clear selection"
                >
                  <X size={16} />
                </button>
              </div>

              {isLowDetail && (
                <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200">
                  Low-detail estimate: this reconstruction has only{' '}
                  {selectedEntry?.vertices} vertices
                  {selectedEntry && !selectedEntry.watertight
                    ? ' and is not watertight'
                    : ''}
                  . Treat the 3D shape as approximate.
                </div>
              )}

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <small className="block text-xs text-slate-500">Decision</small>
                  <strong className="mt-1 block text-sm font-semibold text-slate-200">
                    {String(selected.action || '—').replace('_', ' ')}
                  </strong>
                </div>

                <div>
                  <small className="block text-xs text-slate-500">Confidence</small>
                  <strong className="mt-1 block text-sm font-semibold text-slate-200">
                    {selectedConfidence !== null
                      ? `${(selectedConfidence * 100).toFixed(1)}%`
                      : '—'}
                  </strong>
                </div>

                <div>
                  <small className="block text-xs text-slate-500">Solar potential</small>
                  <strong className="mt-1 block text-sm font-semibold text-slate-200">
                    {typeof selected.annual_kwh === 'number'
                      ? `${Math.round(selected.annual_kwh).toLocaleString()} kWh`
                      : '—'}
                  </strong>
                </div>

                <div>
                  <small className="block text-xs text-slate-500">Roof area</small>
                  <strong className="mt-1 block text-sm font-semibold text-slate-200">
                    {typeof selected.usable_roof_area_m2 === 'number'
                      ? `${selected.usable_roof_area_m2.toFixed(1)} m²`
                      : '—'}
                  </strong>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg border border-slate-700/70 bg-slate-950/50 p-3 text-[11px]">
                <div className="col-span-2 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                  Uncertainty and reliability
                </div>
                <span className="text-slate-500">Model confidence</span>
                <span className="text-right text-slate-300">{fmtPct(selected.model_confidence)}</span>
                <span className="text-slate-500">Combined confidence</span>
                <span className="text-right text-slate-300">{fmtPct(selected.combined_confidence)}</span>
                <span className="text-slate-500">Confidence class</span>
                <span className="text-right text-slate-300">{String(selected.confidence_class ?? '—')}</span>
                <span className="text-slate-500">P(bad)</span>
                <span className="text-right text-slate-300">{fmtPct(selected.p_bad)}</span>
                <span className="text-slate-500">Solar reliability</span>
                <span className="text-right text-slate-300">{String(selected.solar_reliability ?? '—')}</span>
                <span className="text-slate-500">Processing status</span>
                <span className="text-right text-slate-300">{String(selected.status ?? '—')}</span>
                {selectedEntry && (
                  <>
                    <span className="text-slate-500">Mesh vertices / faces</span>
                    <span className="text-right text-slate-300">
                      {selectedEntry.vertices} / {selectedEntry.faces}
                    </span>
                    <span className="text-slate-500">Watertight</span>
                    <span className="text-right text-slate-300">
                      {selectedEntry.watertight ? 'Yes' : 'No'}
                    </span>
                  </>
                )}
              </div>

              {modelLoading && (
                <div className="flex items-center gap-2 text-xs text-emerald-300">
                  <LoaderCircle className="animate-spin" size={14} />
                  Loading GLB reconstruction…
                </div>
              )}

              {modelError && (
                <div className="flex items-center gap-2 text-xs text-red-300">
                  <AlertCircle size={14} />
                  {modelError}
                </div>
              )}

              {selectedEntry && (
                <a
                  className="flex items-center justify-between rounded-lg border border-slate-600 px-3 py-3 text-xs font-medium text-slate-200 transition hover:bg-slate-800"
                  href={`${API_ROOT}/assets/glb/${encodeURIComponent(selectedEntry.glb_filename)}`}
                  download={selectedEntry.glb_filename}
                >
                  Download GLB model
                  <Download size={14} />
                </a>
              )}

              <Link
                className="flex items-center justify-between rounded-lg border border-emerald-500/30 px-3 py-3 text-xs font-medium text-emerald-300 transition hover:bg-emerald-500/10"
                to={`/buildings/${selected.building_id}`}
              >
                Open full building record
                <Crosshair size={14} />
              </Link>
            </div>
          )}

          {!selected && (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center text-slate-400">
              <Building2 size={20} />
              <strong>Select a building</strong>
              <span>
                Choose a point on the map or an asset from the list to inspect
                its data and load its 3D reconstruction.
              </span>
            </div>
          )}
        </aside>
      </section>

      <footer className="flex items-center gap-2 text-xs text-slate-500">
        <Activity size={14} />
        GLB models are loaded on demand for the selected building. Model
        placement uses manifest WGS84 coordinates and local east-north-up axes.
      </footer>
    </main>
  );
}
