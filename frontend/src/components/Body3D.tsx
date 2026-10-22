// The 3D body: a translucent human figure seen from the front, standing still (no rotation, no
// dragging), drawn from simple geometry in code (no downloaded model). The torso is a lathe of a
// human profile (shoulders, chest, waist, hips); arms and legs are tapered limbs with joints.
// Each of the 16 regions glows by severity; hovering or tapping a region reports it upward.
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import { SEVERITY_COLORS, type RegionView } from "../lib/panel";

// A light, clinical look: a blue figure on a white card (normal blending, so colors stay true).
const FIGURE = "#2f6fd1";
const QUIET = "#7fa6dc";      // organs with nothing flagged
const FOCUS = "#0b2a4a";      // an organ linked to the selected explanation card
type Vec3 = [number, number, number];
type Part =
  | { shape: "sphere" | "capsule" | "torus"; pos?: Vec3; rot?: Vec3; scale?: Vec3; args: number[] }
  | { shape: "tube"; args: number[]; points: Vec3[] }
  | { shape: "limb"; from: Vec3; to: Vec3; args: [number, number] }                 // radius at `from`, radius at `to`
  | { shape: "lathe"; pos?: Vec3; scale?: Vec3; profile: [number, number][] };       // [radius, height] pairs, bottom to top

// Side view of the torso as [radius, height]: pelvis, hips, waist, ribs, chest, shoulders, neck base.
const TORSO: [number, number][] = [
  [0.05, 0.92], [0.22, 0.96], [0.31, 1.06], [0.34, 1.2], [0.32, 1.36], [0.27, 1.55], [0.28, 1.72], [0.33, 1.92],
  [0.38, 2.12], [0.4, 2.27], [0.38, 2.4], [0.3, 2.5], [0.17, 2.56], [0.1, 2.6],
];
const SHOULDER: Vec3 = [0.44, 2.4, 0];
const ELBOW: Vec3 = [0.55, 1.86, 0.02];
const WRIST: Vec3 = [0.61, 1.36, 0.06];
const HIP: Vec3 = [0.17, 1.0, 0];
const KNEE: Vec3 = [0.16, 0.44, 0.02];
const ANKLE: Vec3 = [0.15, -0.26, 0];
const side = (s: number, p: Vec3): Vec3 => [s * p[0], p[1], p[2]];

// The body shell. The body faces +z; the patient's right side is -x.
const SHELL: Part[] = [
  { shape: "sphere", pos: [0, 3.0, 0.01], args: [0.25], scale: [0.86, 1.06, 0.96] },           // head
  { shape: "sphere", pos: [0, 2.86, 0.06], args: [0.15], scale: [1, 0.8, 0.95] },               // jaw and chin
  { shape: "limb", from: [0, 2.56, 0], to: [0, 2.82, 0.01], args: [0.1, 0.085] },                // neck
  { shape: "lathe", profile: TORSO, scale: [1, 1, 0.56] },                                       // torso
  ...([-1, 1] as const).flatMap((s): Part[] => [
    { shape: "sphere", pos: side(s, [0.4, 2.42, 0]), args: [0.12], scale: [1, 0.85, 0.9] },     // shoulder (deltoid)
    { shape: "limb", from: side(s, SHOULDER), to: side(s, ELBOW), args: [0.095, 0.07] },         // upper arm
    { shape: "sphere", pos: side(s, ELBOW), args: [0.07] },                                      // elbow
    { shape: "limb", from: side(s, ELBOW), to: side(s, WRIST), args: [0.068, 0.05] },           // forearm
    { shape: "sphere", pos: side(s, [0.63, 1.22, 0.07]), args: [0.06], scale: [0.75, 1.45, 0.5] }, // hand
    { shape: "limb", from: side(s, HIP), to: side(s, KNEE), args: [0.15, 0.095] },               // thigh
    { shape: "sphere", pos: side(s, KNEE), args: [0.095] },                                      // knee
    { shape: "limb", from: side(s, KNEE), to: side(s, ANKLE), args: [0.09, 0.06] },              // lower leg
    { shape: "sphere", pos: side(s, [0.15, -0.35, 0.09]), args: [0.08], scale: [0.75, 0.5, 1.75] }, // foot
  ]),
];

const BLOOD_PATHS: Vec3[][] = [
  [[0.06, 2.15, 0.1], [0.02, 1.7, 0.06], [0, 1.2, 0.05], [-0.17, 0.8, 0.04], [-0.16, 0.44, 0.04], [-0.15, -0.25, 0.04]],
  [[0, 1.2, 0.05], [0.17, 0.8, 0.04], [0.16, 0.44, 0.04], [0.15, -0.25, 0.04]],
  ...([-1, 1] as const).map((s) => [[0.04 * s, 2.32, 0.05], side(s, [0.36, 2.4, 0.03]), side(s, [0.55, 1.86, 0.04]), side(s, [0.61, 1.36, 0.07]), side(s, [0.63, 1.24, 0.08])] as Vec3[]),
  [[0.03, 2.35, 0.06], [0.05, 2.65, 0.06], [0.07, 2.92, 0.02]],
];

const JOINTS: Vec3[] = ([-1, 1] as const).flatMap((s) => [side(s, [0.44, 2.4, 0.02]), side(s, ELBOW), side(s, WRIST), side(s, [0.18, 1.06, 0.02]), side(s, KNEE), side(s, ANKLE)]);

export const REGION_PARTS: Record<string, Part[]> = {
  brain: [{ shape: "sphere", pos: [0, 3.06, -0.01], args: [0.19], scale: [0.95, 0.85, 1.05] }],
  eyes: [{ shape: "sphere", pos: [-0.08, 3.0, 0.21], args: [0.04] }, { shape: "sphere", pos: [0.08, 3.0, 0.21], args: [0.04] }],
  ent: [{ shape: "sphere", pos: [-0.22, 2.98, 0], args: [0.05] }, { shape: "sphere", pos: [0.22, 2.98, 0], args: [0.05] },
        { shape: "sphere", pos: [0, 2.92, 0.24], args: [0.04] }, { shape: "capsule", pos: [0, 2.72, 0.04], args: [0.032, 0.12] }],
  thyroid: [{ shape: "sphere", pos: [0, 2.62, 0.08], args: [0.06], scale: [1.7, 0.8, 0.7] }],
  lungs: [{ shape: "sphere", pos: [-0.19, 2.15, 0], args: [0.16], scale: [1, 1.6, 0.85] }, { shape: "sphere", pos: [0.19, 2.15, 0], args: [0.16], scale: [1, 1.6, 0.85] }],
  heart: [{ shape: "sphere", pos: [0.07, 2.06, 0.11], args: [0.11], scale: [1, 1.15, 0.9] }],
  liver: [{ shape: "sphere", pos: [-0.14, 1.75, 0.06], args: [0.15], scale: [1.55, 0.72, 0.85] }],
  stomach: [{ shape: "sphere", pos: [0.15, 1.7, 0.09], args: [0.11], scale: [1.3, 1, 0.85] }],
  kidneys: [{ shape: "sphere", pos: [-0.15, 1.57, -0.08], args: [0.065], scale: [0.8, 1.35, 0.8] }, { shape: "sphere", pos: [0.15, 1.57, -0.08], args: [0.065], scale: [0.8, 1.35, 0.8] }],
  intestines: [{ shape: "torus", pos: [0, 1.34, 0.09], args: [0.14, 0.045] }, { shape: "sphere", pos: [0, 1.34, 0.09], args: [0.085] }],
  bladder_prostate: [{ shape: "sphere", pos: [0, 1.08, 0.09], args: [0.075] }],
  reproductive: [{ shape: "sphere", pos: [0, 0.98, -0.01], args: [0.08], scale: [1.7, 0.75, 0.9] }],
  blood: BLOOD_PATHS.map((points) => ({ shape: "tube" as const, args: [0.016], points })),
  bones_joints: JOINTS.map((pos) => ({ shape: "sphere" as const, pos, args: [0.055] })),
  mind: [{ shape: "torus", pos: [0, 3.42, 0], rot: [Math.PI / 2, 0, 0], args: [0.28, 0.015] }],
};

function Geometry({ part, low }: { part: Part; low?: boolean }) {
  const curve = useMemo(() => (part.shape === "tube" ? new THREE.CatmullRomCurve3(part.points.map((p) => new THREE.Vector3(...p))) : null), [part]);
  const lathe = useMemo(() => (part.shape === "lathe" ? part.profile.map(([r, y]) => new THREE.Vector2(r, y)) : null), [part]);
  switch (part.shape) {
    case "sphere": return <sphereGeometry args={[part.args[0], low ? 12 : 28, low ? 8 : 18]} />;
    case "capsule": return <capsuleGeometry args={[part.args[0], part.args[1], 6, 16]} />;
    case "torus": return <torusGeometry args={[part.args[0], part.args[1], 12, 40]} />;
    case "tube": return <tubeGeometry args={[curve!, 48, part.args[0], 6, false]} />;
    case "lathe": return <latheGeometry args={[lathe!, low ? 16 : 40]} />;
    case "limb": {
      const len = new THREE.Vector3(...part.from).distanceTo(new THREE.Vector3(...part.to));
      return <cylinderGeometry args={[part.args[1], part.args[0], len, low ? 8 : 20, 1, true]} />;  // cylinder top = `to` end
    }
  }
}

/** Position, rotation and scale for a part; a limb is a cylinder stood between its two joints. */
function placement(part: Part): { position?: THREE.Vector3 | Vec3; quaternion?: THREE.Quaternion; rotation?: Vec3; scale?: Vec3 } {
  if (part.shape === "limb") {
    const a = new THREE.Vector3(...part.from), b = new THREE.Vector3(...part.to);
    const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
    return { position: a.add(b).multiplyScalar(0.5), quaternion: q };
  }
  if (part.shape === "tube") return {};
  return { position: part.pos, rotation: "rot" in part ? part.rot : undefined, scale: part.scale };
}

function Placed({ part, children }: { part: Part; children: ReactNode }) {
  const p = useMemo(() => placement(part), [part]);
  return <group position={p.position} quaternion={p.quaternion} rotation={p.rotation} scale={p.scale}>{children}</group>;
}

const noRaycast = () => null;

/** The body: a faint blue figure with a sparse outline, so flagged organs stand out against it.
 *  A skin finding only tints the figure; it never paints the whole body. */
function Shell({ tint, tintOpacity }: { tint: string; tintOpacity: number }) {
  return (
    <group>
      {SHELL.map((p, i) => (
        <Placed key={i} part={p}>
          <mesh raycast={noRaycast}>
            <Geometry part={p} />
            <meshBasicMaterial color={tint} transparent opacity={tintOpacity} depthWrite={false} side={THREE.DoubleSide} />
          </mesh>
          <mesh raycast={noRaycast}>
            <Geometry part={p} low />
            <meshBasicMaterial color={FIGURE} wireframe transparent opacity={0.22} depthWrite={false} />
          </mesh>
        </Placed>
      ))}
    </group>
  );
}

function Region({ id, view, hovered, focused, dimmed, onHover, onSelect, motion }: {
  id: string; view?: RegionView; hovered: boolean; focused: boolean; dimmed: boolean; onHover: (id: string | null) => void;
  onSelect?: (id: string | null) => void; motion: boolean;
}) {
  const group = useRef<THREE.Group>(null);
  // A region linked to the selected explanation card glows white-hot; the others step back.
  const color = focused && !view ? FOCUS : view ? SEVERITY_COLORS[view.severity] : QUIET;
  const opacity = focused ? 1 : dimmed ? (view ? 0.3 : 0.06) : view ? (hovered ? 1 : 0.85) : 0.14;
  const interactive = !!view || focused;   // healthy organs ignore the pointer
  useFrame(({ clock }) => {
    if (!group.current) return;
    // The body stands still; only a flagged region breathes gently so it is easy to spot.
    const pulse = motion && (focused || view?.severity === "urgent") ? 1 + (focused ? 0.12 : 0.07) * Math.sin(clock.elapsedTime * (focused ? 4 : 3)) : 1;
    // No growth on hover: a region that grows under the pointer makes it enter and leave in a loop (flicker).
    group.current.scale.lerp(new THREE.Vector3(pulse, pulse, pulse), 0.2);
  });
  return (
    <group ref={group}
      onPointerOver={interactive ? (e) => { e.stopPropagation(); onHover(id); } : undefined}
      onPointerOut={interactive ? (e) => { if (e.pointerType === "mouse") { e.stopPropagation(); onHover(null); } } : undefined}
      onClick={interactive ? (e) => { e.stopPropagation(); onHover(id); onSelect?.(id); } : undefined}>
      {REGION_PARTS[id].map((p, i) => (
        <Placed key={i} part={p}>
          <mesh raycast={interactive ? undefined : noRaycast}>
            <Geometry part={p} />
            <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} />
          </mesh>
        </Placed>
      ))}
    </group>
  );
}

/** A fixed front view: the camera looks at the middle of the body and never moves. */
function FixedCamera() {
  const { camera } = useThree();
  useEffect(() => { camera.lookAt(0, 1.42, 0); camera.updateProjectionMatrix(); }, [camera]);
  return null;
}

function Floor() {
  return (
    <group position={[0, -0.47, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <mesh raycast={noRaycast}><ringGeometry args={[0.7, 0.73, 64]} />
        <meshBasicMaterial color={FIGURE} transparent opacity={0.28} side={THREE.DoubleSide} /></mesh>
      <mesh raycast={noRaycast}><circleGeometry args={[0.95, 64]} />
        <meshBasicMaterial color={FIGURE} transparent opacity={0.05} side={THREE.DoubleSide} /></mesh>
    </group>
  );
}

export default function Body3D({ regions, hovered, onHover, motion, focus, onSelect, children }: {
  regions: RegionView[]; hovered: string | null; onHover: (id: string | null) => void; motion: boolean;
  focus?: string[]; onSelect?: (id: string | null) => void; children?: ReactNode;
}) {
  const focused = new Set(focus ?? []);
  const byId = Object.fromEntries(regions.map((r) => [r.region, r]));
  const skin = byId.skin;
  return (
    <Canvas camera={{ position: [0, 1.42, 7.4], fov: 33 }} dpr={[1, 2]} gl={{ antialias: true, alpha: true }}
      onPointerMissed={() => onHover(null)}>
      <FixedCamera />
      <Shell tint={skin ? SEVERITY_COLORS[skin.severity] : "#a8c4ec"} tintOpacity={skin ? (hovered === "skin" || focused.has("skin") ? 0.2 : 0.12) : 0.12} />
      {Object.keys(REGION_PARTS).map((id) => (
        <Region key={id} id={id} view={byId[id]} hovered={hovered === id} focused={focused.has(id)} dimmed={focused.size > 0 && !focused.has(id)}
          onHover={onHover} onSelect={onSelect} motion={motion} />
      ))}
      <Floor />
      {children}
    </Canvas>
  );
}
