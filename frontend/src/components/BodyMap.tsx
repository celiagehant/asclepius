import { Component, lazy, Suspense, useMemo, useState, type ReactNode } from "react";
import { REGION_LABELS, SEVERITY_COLORS, type RegionView } from "../lib/panel";

const Body3D = lazy(() => import("./Body3D"));  // three.js loads only when the body is shown
const ORDER: Record<string, number> = { urgent: 0, discuss: 1, watch: 2 };

export function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl")));
  } catch {
    return false;
  }
}

class GLBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export default function BodyMap({ regions, waiting, force2d, focusRegions, focusLabel, onSelectRegion }: {
  regions: RegionView[]; waiting?: boolean; force2d?: boolean; focusRegions?: string[]; focusLabel?: string | null;
  onSelectRegion?: (region: string | null) => void;
}) {
  // The body is static: nothing reacts to the mouse and nothing moves. Only a click on a colored
  // (flagged) area does something: it shows below what the panel found there. Clicking the same
  // area again clears it.
  const [selected, setSelected] = useState<string | null>(null);
  const focus = focusRegions ?? [];
  const [use3d] = useState(() => !force2d && webglAvailable());
  const touch = useMemo(() => !!window.matchMedia?.("(hover: none)").matches, []);
  const flagged = new Set(regions.map((r) => r.region));
  const sorted = [...regions].sort((a, b) => ORDER[a.severity] - ORDER[b.severity]);
  const info = selected ? regions.find((r) => r.region === selected) : null;
  const select = (id: string) => {
    if (!flagged.has(id)) return;                 // only colored areas can be clicked
    setSelected((cur) => (cur === id ? null : id));
    onSelectRegion?.(id);                         // also lights up the explanation cards that involve it
  };
  const flat = <Body2D regions={regions} selected={selected} focus={focus} onSelect={select} />;

  return (
    <section className="card body-card" aria-label="Body map">
      <div className="body-head">
        <h2>Body map</h2>
        <div className="legend" aria-label="Severity legend">
          {(["urgent", "discuss", "watch"] as const).map((s) => (
            <span key={s}><i style={{ background: SEVERITY_COLORS[s] }} />{s}</span>
          ))}
        </div>
      </div>
      <div className="hologram">
        {use3d ? (
          <GLBoundary fallback={flat}>
            <Suspense fallback={<div className="holo-loading">Preparing the body map…</div>}>
              <Body3D regions={regions} selected={selected} focus={focus} onSelect={select} />
            </Suspense>
          </GLBoundary>
        ) : flat}
      </div>
      <div className="holo-info" aria-live="polite">
          {info ? (
            <>
              <div className="holo-title"><i style={{ background: SEVERITY_COLORS[info.severity] }} />{REGION_LABELS[info.region]} · {info.severity}</div>
              <p>{info.reason}</p>
              <p className="holo-who">Flagged by: {info.specialists.join(", ") || "the coordinator"}</p>
            </>
          ) : focus.length > 0 && focusLabel ? (
            <>
              <div className="holo-title focus-title">{focusLabel}</div>
              <p>{focus.map((r) => REGION_LABELS[r] ?? r).join(" · ")}</p>
            </>
          ) : waiting ? (
            <div className="holo-hint">The colored areas appear when the coordinator finishes the summary.</div>
          ) : regions.length ? (
            <div className="holo-hint">{touch ? "Tap" : "Click"} a colored area, or a name below, to see what the panel found there.</div>
          ) : (
            <div className="holo-hint">The panel did not flag any body area.</div>
          )}
        </div>
      {sorted.length > 0 && (
        <ul className="region-legend">
          {sorted.map((r) => (
            <li key={r.region} tabIndex={0} onClick={() => select(r.region)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(r.region); } }}
              className={selected === r.region ? "on" : ""}>
              <i style={{ background: SEVERITY_COLORS[r.severity] }} />
              <strong>{REGION_LABELS[r.region]}</strong> <span className="muted small">{r.severity}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// 2D fallback: a front-view silhouette with the same regions, for browsers without WebGL.
const SPOTS: Record<string, [number, number, number][]> = {
  brain: [[100, 34, 15]], eyes: [[93, 40, 3.5], [107, 40, 3.5]], ent: [[83, 42, 4.5], [117, 42, 4.5], [100, 50, 4]],
  thyroid: [[100, 70, 6]], lungs: [[86, 102, 13], [114, 102, 13]], heart: [[106, 108, 9]], liver: [[88, 132, 11]],
  stomach: [[112, 134, 9]], kidneys: [[87, 146, 6], [113, 146, 6]], intestines: [[100, 160, 13]], bladder_prostate: [[100, 184, 6]],
  reproductive: [[100, 194, 7]], bones_joints: [[64, 86, 5], [136, 86, 5], [56, 128, 5], [144, 128, 5], [86, 196, 5], [114, 196, 5], [86, 262, 5], [114, 262, 5]],
  mind: [[100, 12, 6]], blood: [[100, 120, 3], [100, 150, 3], [86, 230, 3], [114, 230, 3], [60, 110, 3], [140, 110, 3]],
};

function Body2D({ regions, selected, focus, onSelect }: {
  regions: RegionView[]; selected: string | null; focus: string[]; onSelect: (id: string) => void;
}) {
  const byId = Object.fromEntries(regions.map((r) => [r.region, r]));
  const skin = byId.skin;
  const stroke = skin ? SEVERITY_COLORS[skin.severity] : "#2f6fd1";
  return (
    <svg viewBox="0 0 200 330" className="body2d" role="img" aria-label="Body map (2D)">
      <g fill="rgba(47,125,225,0.07)" stroke={stroke} strokeWidth={1.2} onClick={() => onSelect("skin")}>
        <ellipse cx="100" cy="38" rx="20" ry="24" />
        <rect x="93" y="60" width="14" height="12" rx="4" />
        <rect x="68" y="72" width="64" height="90" rx="26" />
        <rect x="72" y="150" width="56" height="50" rx="20" />
        <rect x="52" y="78" width="16" height="80" rx="8" transform="rotate(8 60 78)" />
        <rect x="132" y="78" width="16" height="80" rx="8" transform="rotate(-8 140 78)" />
        <rect x="78" y="192" width="18" height="120" rx="9" />
        <rect x="104" y="192" width="18" height="120" rx="9" />
      </g>
      {Object.entries(SPOTS).map(([id, spots]) => {
        const v = byId[id];
        const color = v ? SEVERITY_COLORS[v.severity] : "#7fa6dc";
        return (
          <g key={id} onClick={v ? () => onSelect(id) : undefined} style={{ cursor: v ? "pointer" : "default" }}>
            {spots.map(([x, y, r], i) => (
              <circle key={i} cx={x} cy={y} r={r} fill={focus.includes(id) && !v ? "#0b2a4a" : color}
                fillOpacity={v || focus.includes(id) ? 0.9 : 0.12} stroke={selected === id ? "#0b2a4a" : undefined} strokeWidth={selected === id ? 1.4 : 0} />
            ))}
            <title>{REGION_LABELS[id]}{v ? ` · ${v.severity}: ${v.reason}` : ""}</title>
          </g>
        );
      })}
    </svg>
  );
}
