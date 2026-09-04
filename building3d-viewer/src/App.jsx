import { useEffect, useState } from "react";
import Viewer from "./Viewer.jsx";
import "./styles.css";

const MODES = [
  { key: "wireframe", label: "Wireframe" },
  { key: "mesh", label: "Final Mesh" },
  { key: "overlay", label: "Overlay" },
];

const pct = (x) => `${(x * 100).toFixed(1)}%`;
const avg = (a) =>
  a && a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0;

export default function App() {
  const [buildings, setBuildings] = useState([]);
  const [active, setActive] = useState(null);
  const [mode, setMode] = useState("wireframe");
  const [info, setInfo] = useState(null);
  const [status, setStatus] = useState("loading…");
  const [resetCount, setResetCount] = useState(0);

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data/buildings.json`)
      .then((r) => {
        if (!r.ok) throw new Error("buildings.json missing");
        return r.json();
      })
      .then((list) => {
        setBuildings(list);
        if (list.length) setActive(list[0].id);
      })
      .catch(() =>
        setStatus("data/buildings.json not found — run scripts/prepare_data.py first")
      );
  }, []);

  useEffect(() => {
    if (!active) return;
    setInfo(null);
    fetch(`${import.meta.env.BASE_URL}data/buildings/${active}.json`)
      .then((r) => r.json())
      .then(setInfo)
      .catch(() => setInfo(null));
  }, [active]);

  return (
    <div className="app">
      <header className="topbar">
        <span className="logo">BUILDING3D RECONSTRUCTION</span>
        <span className="badge">PHASE 2</span>
      </header>

      <aside className="sidebar">
        <div className="sidebar-title">BUILDINGS</div>
        <ul className="building-list">
          {buildings.map((b) => (
            <li
              key={b.id}
              className={b.id === active ? "active" : ""}
              onClick={() => setActive(b.id)}
            >
              <span className="bid">{b.id}</span>
              <span className="bmeta">
                {b.n_corners}c · {b.n_edges}e
              </span>
            </li>
          ))}
        </ul>
        <div className="sidebar-foot">{buildings.length} buildings</div>
      </aside>

      <main className="viewer-wrap">
        <Viewer
          buildingId={active}
          mode={mode}
          resetCount={resetCount}
          onStatus={setStatus}
        />
        <div className="status">{status}</div>
      </main>

      <footer className="bottombar">
        <div className="modes">
          {MODES.map((m) => (
            <button
              key={m.key}
              className={mode === m.key ? "on" : ""}
              onClick={() => setMode(m.key)}
            >
              {m.label}
            </button>
          ))}
          <button className="reset" onClick={() => setResetCount((c) => c + 1)}>
            Reset View
          </button>
        </div>
        <div className="stats">
          {info ? (
            <>
              <span className="stat-id">Building {active}</span>
              <span>Corners: {info.corners.length}</span>
              <span>Edges: {info.edges.length}</span>
              <span>Corner F1/conf: {pct(avg(info.corner_scores))}</span>
              <span>Edge conf: {pct(avg(info.edge_scores))}</span>
            </>
          ) : (
            <span>{active ? `Loading building ${active}…` : " "}</span>
          )}
        </div>
      </footer>
    </div>
  );
}
