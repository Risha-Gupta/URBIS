import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";

function disposeObject(object) {
  object.traverse((child) => {
    if (child.geometry) {
      child.geometry.dispose();
    }

    if (child.material) {
      if (Array.isArray(child.material)) {
        child.material.forEach((material) => material.dispose());
      } else {
        child.material.dispose();
      }
    }
  });
}

function createPredictionWireframe(data) {
  const group = new THREE.Group();

  const corners = Array.isArray(data.corners)
    ? data.corners
    : [];

  const edges = Array.isArray(data.edges)
    ? data.edges
    : [];

  if (corners.length > 0) {
    const positions = [];

    for (const corner of corners) {
      if (!Array.isArray(corner) || corner.length < 3) {
        continue;
      }

      positions.push(
        Number(corner[0]) || 0,
        Number(corner[1]) || 0,
        Number(corner[2]) || 0
      );
    }

    const geometry = new THREE.BufferGeometry();

    geometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(positions, 3)
    );

    const material = new THREE.PointsMaterial({
      color: 0xffd166,
      size: 7,
      sizeAttenuation: false,
    });

    group.add(
      new THREE.Points(
        geometry,
        material
      )
    );
  }

  if (edges.length > 0) {
    const positions = [];

    for (const edge of edges) {
      if (!Array.isArray(edge) || edge.length < 2) {
        continue;
      }

      const a = Number(edge[0]);
      const b = Number(edge[1]);

      if (
        !Number.isInteger(a) ||
        !Number.isInteger(b) ||
        !corners[a] ||
        !corners[b]
      ) {
        continue;
      }

      const start = corners[a];
      const end = corners[b];

      positions.push(
        Number(start[0]) || 0,
        Number(start[1]) || 0,
        Number(start[2]) || 0,

        Number(end[0]) || 0,
        Number(end[1]) || 0,
        Number(end[2]) || 0
      );
    }

    const geometry = new THREE.BufferGeometry();

    geometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(
        positions,
        3
      )
    );

    const material =
      new THREE.LineBasicMaterial({
        color: 0x4dff72,
      });

    group.add(
      new THREE.LineSegments(
        geometry,
        material
      )
    );
  }

  return group;
}

function prepareMesh(object) {
  const material =
    new THREE.MeshStandardMaterial({
      color: 0x8ab4f8,
      side: THREE.DoubleSide,
      flatShading: false,
      roughness: 0.8,
      metalness: 0.0,
    });

  object.traverse((child) => {
    if (!child.isMesh) {
      return;
    }

    child.material = material;

    child.geometry.computeVertexNormals();
    child.geometry.computeBoundingBox();
    child.geometry.computeBoundingSphere();
  });

  return object;
}

function getObjectStats(object) {
  let meshes = 0;
  let vertices = 0;
  let triangles = 0;

  object.traverse((child) => {
    if (!child.isMesh) {
      return;
    }

    meshes++;

    const geometry = child.geometry;

    if (geometry.attributes.position) {
      vertices +=
        geometry.attributes.position.count;
    }

    if (geometry.index) {
      triangles +=
        geometry.index.count / 3;
    } else if (geometry.attributes.position) {
      triangles +=
        geometry.attributes.position.count / 3;
    }
  });

  return {
    meshes,
    vertices,
    triangles,
  };
}

export default function Viewer({
  buildingId,
  mode,
  resetCount,
  onStatus,
}) {
  const mountRef = useRef(null);

  const stateRef = useRef({
    scene: null,
    camera: null,
    renderer: null,
    controls: null,
    grid: null,
    content: null,
    wireGroup: null,
    meshGroup: null,
    fit: null,
  });

  const modeRef = useRef(mode);

  modeRef.current = mode;

  /*
   * ============================================================
   * THREE.JS INITIALIZATION
   * ============================================================
   */

  useEffect(() => {
    const mount = mountRef.current;

    if (!mount) {
      return;
    }

    const scene = new THREE.Scene();

    scene.background =
      new THREE.Color(0x0e1116);

    const camera =
      new THREE.PerspectiveCamera(
        50,
        1,
        0.01,
        1000
      );

    const renderer =
      new THREE.WebGLRenderer({
        antialias: true,
      });

    renderer.setPixelRatio(
      Math.min(
        window.devicePixelRatio || 1,
        2
      )
    );

    mount.appendChild(
      renderer.domElement
    );

    const controls =
      new OrbitControls(
        camera,
        renderer.domElement
      );

    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 0.01;
    controls.maxDistance = 10000;

    /*
     * Lighting
     */

    const ambient =
      new THREE.AmbientLight(
        0xffffff,
        0.7
      );

    scene.add(ambient);

    const directional =
      new THREE.DirectionalLight(
        0xffffff,
        1.4
      );

    directional.position.set(
      5,
      10,
      7
    );

    scene.add(directional);

    /*
     * Grid
     */

    const grid =
      new THREE.GridHelper(
        4,
        20,
        0x2a3140,
        0x1a2029
      );

    scene.add(grid);

    /*
     * Content container
     */

    const content =
      new THREE.Group();

    scene.add(content);

    stateRef.current = {
      scene,
      camera,
      renderer,
      controls,
      grid,
      content,
      wireGroup: null,
      meshGroup: null,
      fit: null,
    };

    /*
     * Resize
     */

    const resize = () => {
      const width =
        mount.clientWidth || 1;

      const height =
        mount.clientHeight || 1;

      renderer.setSize(
        width,
        height
      );

      camera.aspect =
        width / height;

      camera.updateProjectionMatrix();
    };

    const resizeObserver =
      new ResizeObserver(resize);

    resizeObserver.observe(mount);

    resize();

    /*
     * Render loop
     */

    let animationFrame = 0;

    const animate = () => {
      animationFrame =
        requestAnimationFrame(
          animate
        );

      controls.update();

      renderer.render(
        scene,
        camera
      );
    };

    animate();

    /*
     * Cleanup
     */

    return () => {
      cancelAnimationFrame(
        animationFrame
      );

      resizeObserver.disconnect();

      controls.dispose();
      renderer.dispose();

      if (
        renderer.domElement.parentNode ===
        mount
      ) {
        mount.removeChild(
          renderer.domElement
        );
      }
    };
  }, []);

  /*
   * ============================================================
   * CAMERA FIT
   * ============================================================
   */

  const fitCamera = (object) => {
    const state =
      stateRef.current;

    if (
      !state.camera ||
      !state.controls ||
      !object
    ) {
      return;
    }

    const box =
      new THREE.Box3().setFromObject(
        object
      );

    if (box.isEmpty()) {
      return;
    }

    const center =
      box.getCenter(
        new THREE.Vector3()
      );

    const size =
      box.getSize(
        new THREE.Vector3()
      );

    const maxDimension =
      Math.max(
        size.x,
        size.y,
        size.z
      );

    if (!Number.isFinite(maxDimension)) {
      return;
    }

    const radius =
      Math.max(
        maxDimension * 0.5,
        0.5
      );

    const fov =
      THREE.MathUtils.degToRad(
        state.camera.fov
      );

    const distance =
      (radius / Math.tan(fov / 2)) *
      2.0;

    state.controls.target.copy(
      center
    );

    state.camera.position.set(
      center.x + distance,
      center.y + distance * 0.65,
      center.z + distance
    );

    state.camera.near =
      Math.max(
        distance / 100,
        0.001
      );

    state.camera.far =
      Math.max(
        distance * 100,
        100
      );

    state.camera.updateProjectionMatrix();

    if (state.grid) {
      state.grid.position.y =
        box.min.y;
    }

    state.controls.update();

    state.fit = () =>
      fitCamera(object);
  };

  /*
   * ============================================================
   * MODE
   * ============================================================
   */

  const applyMode = () => {
    const state =
      stateRef.current;

    if (!state) {
      return;
    }

    const currentMode =
      modeRef.current;

    /*
     * Wireframe / prediction
     */

    if (state.wireGroup) {
      state.wireGroup.visible =
        currentMode !== "mesh";
    }

    /*
     * OBJ mesh
     */

    if (state.meshGroup) {
      state.meshGroup.visible =
        currentMode !== "wireframe";
    }

    /*
     * Overlay transparency
     */

    if (state.meshGroup) {
      state.meshGroup.traverse(
        (object) => {
          if (!object.isMesh) {
            return;
          }

          if (!object.material) {
            return;
          }

          object.material.transparent =
            currentMode === "overlay";

          object.material.opacity =
            currentMode === "overlay"
              ? 0.5
              : 1.0;

          object.material.depthWrite =
            currentMode !== "overlay";
        }
      );
    }
  };

  /*
   * ============================================================
   * LOAD BUILDING
   * ============================================================
   */

  useEffect(() => {
    const state =
      stateRef.current;

    if (
      !buildingId ||
      !state.renderer
    ) {
      return;
    }

    let cancelled = false;

    onStatus?.(
      `Loading building ${buildingId}...`
    );

    /*
     * Remove previous building
     */

    while (
      state.content &&
      state.content.children.length
    ) {
      const child =
        state.content.children.pop();

      disposeObject(child);
    }

    state.wireGroup = null;
    state.meshGroup = null;
    state.fit = null;

    /*
     * Public data path
     */

    const base =
      `${import.meta.env.BASE_URL}data/buildings`;

    /*
     * ==========================================================
     * LOAD PREDICTION JSON
     * ==========================================================
     */

    fetch(
      `${base}/${buildingId}.json`
    )
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            `HTTP ${response.status}`
          );
        }

        return response.json();
      })
      .then((data) => {
        if (cancelled) {
          return;
        }

        console.log(
          `[Viewer] Prediction loaded: ${buildingId}`,
          data
        );

        /*
         * Current Phase 2 schema:
         *
         * corners
         * corner_scores
         * edges
         *
         * There is NO edge_scores.
         */

        if (
          !Array.isArray(
            data.corners
          )
        ) {
          throw new Error(
            "Missing corners"
          );
        }

        if (
          !Array.isArray(
            data.edges
          )
        ) {
          throw new Error(
            "Missing edges"
          );
        }

        const wire =
          createPredictionWireframe(
            data
          );

        state.wireGroup = wire;

        state.content.add(
          wire
        );

        console.log(
          `[Viewer] Building ${buildingId}:`,
          {
            corners:
              data.corners.length,
            edges:
              data.edges.length,
            cornerScores:
              Array.isArray(
                data.corner_scores
              )
                ? data.corner_scores.length
                : 0,
          }
        );

        applyMode();

        fitCamera(
          state.content
        );
      })
      .catch((error) => {
        console.error(
          `[Viewer] Prediction failed for ${buildingId}:`,
          error
        );

        if (!cancelled) {
          onStatus?.(
            `Prediction unavailable for ${buildingId}`
          );
        }
      });

    /*
     * ==========================================================
     * LOAD OBJ
     * ==========================================================
     */

    const loader =
      new OBJLoader();

    loader.load(
      `${base}/${buildingId}_mesh.obj`,

      (object) => {
        if (cancelled) {
          disposeObject(object);
          return;
        }

        console.log(
          `[Viewer] OBJ loaded: ${buildingId}`
        );

        const stats =
          getObjectStats(
            object
          );

        console.log(
          `[Viewer] OBJ stats:`,
          stats
        );

        /*
         * Prepare mesh.
         *
         * flatShading is intentionally FALSE.
         * The new OBJ already contains proper
         * triangular faces, so we let Three.js
         * calculate normals from the geometry.
         */

        prepareMesh(object);

        state.meshGroup =
          object;

        state.content.add(
          object
        );

        applyMode();

        fitCamera(
          state.content
        );

        onStatus?.("");

        console.log(
          `[Viewer] Building ${buildingId} ready`
        );
      },

      (progress) => {
        if (
          !progress.total
        ) {
          return;
        }

        const percent =
          (progress.loaded /
            progress.total) *
          100;

        console.log(
          `[Viewer] OBJ ${buildingId}: ${percent.toFixed(1)}%`
        );
      },

      (error) => {
        console.error(
          `[Viewer] OBJ failed for ${buildingId}:`,
          error
        );

        if (!cancelled) {
          onStatus?.(
            `Mesh unavailable for ${buildingId}`
          );
        }
      }
    );

    return () => {
      cancelled = true;
    };

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildingId]);

  /*
   * ============================================================
   * MODE CHANGE
   * ============================================================
   */

  useEffect(() => {
    modeRef.current = mode;

    applyMode();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  /*
   * ============================================================
   * RESET CAMERA
   * ============================================================
   */

  useEffect(() => {
    if (resetCount > 0) {
      stateRef.current.fit?.();
    }
  }, [resetCount]);

  return (
    <div
      ref={mountRef}
      className="viewer"
      style={{
        width: "100%",
        height: "100%",
        overflow: "hidden",
      }}
    />
  );
}