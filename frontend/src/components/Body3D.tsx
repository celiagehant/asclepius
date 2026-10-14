// The 3D hologram body: simple shapes only (no downloaded model), translucent cyan, slow rotation,
// mouse orbit/zoom. Each of the 16 regions glows by severity; hovering reports the region upward.
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { SEVERITY_COLORS, type RegionView } from "../lib/panel";

const CYAN = "#5ff3ff";
type Vec3 = [number, number, number];
type Part = { shape: "sphere" | "capsule" | "torus" | "tube"; pos?: Vec3; rot?: Vec3; scale?: Vec3; args: number[]; points?: Vec3[] };

// Body shell (the hologram silhouette). The body faces +z; the patient's right side is -x.
const SHELL: Part[] = [
  { shape: "sphere", pos: [0, 3.0, 0], args: [0.28], scale: [0.92, 1.08, 1] },               // head
  { shape: "capsule", pos: [0, 2.66, 0], args: [0.1, 0.12] },                                // neck
  { shape: "capsule", pos: [0, 2.05, 0], args: [0.42, 0.62], scale: [1.12, 1, 0.62] },       // chest
  { shape: "capsule", pos: [0, 1.32, 0], args: [0.37, 0.34], scale: [1.05, 1, 0.6] },        // abdomen and pelvis
  ...([-1, 1] as const).flatMap((s) => [
    { shape: "capsule" as const, pos: [s * 0.62, 2.12, 0] as Vec3, rot: [0, 0, s * 0.12] as Vec3, args: [0.1, 0.5] },   // upper arm
    { shape: "capsule" as const, pos: [s * 0.71, 1.55, 0.04] as Vec3, rot: [0, 0, s * 0.05] as Vec3, args: [0.085, 0.5] }, // forearm
    { shape: "sphere" as const, pos: [s * 0.74, 1.18, 0.05] as Vec3, args: [0.08], scale: [0.8, 1.2, 0.6] as Vec3 },      // hand
    { shape: "capsule" as const, pos: [s * 0.2, 0.78, 0] as Vec3, args: [0.15, 0.62] },                                  // thigh
    { shape: "capsule" as const, pos: [s * 0.2, 0.07, 0] as Vec3, args: [0.11, 0.62] },                                  // shin
    { shape: "capsule" as const, pos: [s * 0.2, -0.36, 0.08] as Vec3, rot: [Math.PI / 2, 0, 0] as Vec3, args: [0.07, 0.16] }, // foot
  ]),
];

const BLOOD_PATHS: Vec3[][] = [
  [[0.08, 2.15, 0.1], [0.02, 1.7, 0.05], [0, 1.2, 0.05], [-0.2, 0.8, 0.04], [-0.2, 0.1, 0.03], [-0.2, -0.3, 0.06]],
  [[0, 1.2, 0.05], [0.2, 0.8, 0.04], [0.2, 0.1, 0.03], [0.2, -0.3, 0.06]],
  [[0.08, 2.3, 0.05], [0.4, 2.4, 0.02], [0.63, 2.0, 0.02], [0.72, 1.5, 0.05], [0.74, 1.2, 0.05]],
  [[0.02, 2.3, 0.05], [-0.4, 2.4, 0.02], [-0.63, 2.0, 0.02], [-0.72, 1.5, 0.05], [-0.74, 1.2, 0.05]],
  [[0.04, 2.35, 0.06], [0.06, 2.65, 0.05], [0.08, 2.9, 0.0]],
];

const JOINTS: Vec3[] = ([-1, 1] as const).flatMap((s) => [
  [s * 0.55, 2.4, 0], [s * 0.68, 1.84, 0.02], [s * 0.74, 1.28, 0.04], [s * 0.2, 1.12, 0], [s * 0.2, 0.43, 0.03], [s * 0.2, -0.26, 0.02],
] as Vec3[]);

export const REGION_PARTS: Record<string, Part[]> = {
  brain: [{ shape: "sphere", pos: [0, 3.05, -0.02], args: [0.2], scale: [0.95, 0.85, 1.05] }],
  eyes: [{ shape: "sphere", pos: [-0.09, 3.0, 0.23], args: [0.045] }, { shape: "sphere", pos: [0.09, 3.0, 0.23], args: [0.045] }],
  ent: [{ shape: "sphere", pos: [-0.27, 2.98, 0], args: [0.055] }, { shape: "sphere", pos: [0.27, 2.98, 0], args: [0.055] },
        { shape: "sphere", pos: [0, 2.9, 0.27], args: [0.045] }, { shape: "capsule", pos: [0, 2.72, 0.05], args: [0.035, 0.12] }],
  thyroid: [{ shape: "sphere", pos: [0, 2.6, 0.09], args: [0.065], scale: [1.7, 0.8, 0.7] }],
  lungs: [{ shape: "sphere", pos: [-0.22, 2.17, 0], args: [0.17], scale: [1, 1.65, 0.9] }, { shape: "sphere", pos: [0.22, 2.17, 0], args: [0.17], scale: [1, 1.65, 0.9] }],
  heart: [{ shape: "sphere", pos: [0.08, 2.08, 0.16], args: [0.12], scale: [1, 1.15, 0.9] }],
  liver: [{ shape: "sphere", pos: [-0.17, 1.75, 0.1], args: [0.16], scale: [1.6, 0.75, 0.9] }],
  stomach: [{ shape: "sphere", pos: [0.18, 1.7, 0.14], args: [0.12], scale: [1.3, 1, 0.85] }],
  kidneys: [{ shape: "sphere", pos: [-0.17, 1.58, -0.14], args: [0.07], scale: [0.8, 1.35, 0.8] }, { shape: "sphere", pos: [0.17, 1.58, -0.14], args: [0.07], scale: [0.8, 1.35, 0.8] }],
  intestines: [{ shape: "torus", pos: [0, 1.36, 0.14], args: [0.15, 0.05] }, { shape: "sphere", pos: [0, 1.36, 0.14], args: [0.09] }],
  bladder_prostate: [{ shape: "sphere", pos: [0, 1.08, 0.13], args: [0.08] }],
  reproductive: [{ shape: "sphere", pos: [0, 0.98, -0.02], args: [0.085], scale: [1.7, 0.75, 0.9] }],
  blood: BLOOD_PATHS.map((points) => ({ shape: "tube" as const, args: [0.018], points })),
  bones_joints: JOINTS.map((pos) => ({ shape: "sphere" as const, pos, args: [0.06] })),
  mind: [{ shape: "torus", pos: [0, 3.45, 0], rot: [Math.PI / 2, 0, 0], args: [0.3, 0.016] }],
};

function Geometry({ part }: { part: Part }) {
  const tube = useMemo(() => (part.shape === "tube" ? new THREE.CatmullRomCurve3(part.points!.map((p) => new THREE.Vector3(...p))) : null), [part]);
  switch (part.shape) {
    case "sphere": return <sphereGeometry args={[part.args[0], 24, 16]} />;
    case "capsule": return <capsuleGeometry args={[part.args[0], part.args[1], 6, 16]} />;
    case "torus": return <torusGeometry args={[part.args[0], part.args[1], 12, 40]} />;
    case "tube": return <tubeGeometry args={[tube!, 48, part.args[0], 6, false]} />;
  }
}

const noRaycast = () => null;

function Shell({ color, opacity }: { color: string; opacity: number }) {
  return (
    <group>
      {SHELL.map((p, i) => (
        <group key={i} position={p.pos} rotation={p.rot} scale={p.scale}>
          <mesh raycast={noRaycast}>
            <Geometry part={p} />
            <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} blending={THREE.AdditiveBlending} side={THREE.DoubleSide} />
          </mesh>
          <mesh raycast={noRaycast}>
            <Geometry part={p} />
            <meshBasicMaterial color={color} wireframe transparent opacity={opacity * 1.15} depthWrite={false} blending={THREE.AdditiveBlending} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

function Region({ id, view, hovered, onHover, motion }: {
  id: string; view?: RegionView; hovered: boolean; onHover: (id: string | null) => void; motion: boolean;
}) {
  const group = useRef<THREE.Group>(null);
  const color = view ? SEVERITY_COLORS[view.severity] : CYAN;
  const opacity = view ? (hovered ? 0.98 : 0.78) : hovered ? 0.35 : 0.1;
  useFrame(({ clock }) => {
    if (!group.current) return;
    const pulse = motion && view?.severity === "urgent" ? 1 + 0.08 * Math.sin(clock.elapsedTime * 3.2) : 1;
    const s = (hovered ? 1.12 : 1) * pulse;
    group.current.scale.lerp(new THREE.Vector3(s, s, s), 0.2);
  });
  return (
    <group ref={group}
      onPointerOver={(e) => { e.stopPropagation(); onHover(id); }}
      onPointerOut={(e) => { if (e.pointerType === "mouse") { e.stopPropagation(); onHover(null); } }}
      onClick={(e) => { e.stopPropagation(); onHover(id); }}>
      {REGION_PARTS[id].map((p, i) => (
        <group key={i} position={p.pos} rotation={p.rot} scale={p.scale}>
          <mesh>
            <Geometry part={p} />
            <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} blending={THREE.AdditiveBlending} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

function Controls({ autoRotate }: { autoRotate: boolean }) {
  const { camera, gl } = useThree();
  const ref = useRef<OrbitControls | null>(null);
  useEffect(() => {
    const c = new OrbitControls(camera, gl.domElement);
    c.enablePan = false;
    c.enableDamping = true;
    c.minDistance = 3.2;
    c.maxDistance = 9;
    c.minPolarAngle = 0.35;
    c.maxPolarAngle = 2.5;
    c.autoRotateSpeed = 0.9;
    c.target.set(0, 1.5, 0);
    ref.current = c;
    return () => c.dispose();
  }, [camera, gl]);
  useEffect(() => { if (ref.current) ref.current.autoRotate = autoRotate; }, [autoRotate]);
  useFrame(() => ref.current?.update());
  return null;
}

function Floor({ motion }: { motion: boolean }) {
  const ring = useRef<THREE.Mesh>(null);
  useFrame((_, dt) => { if (ring.current && motion) ring.current.rotation.z += dt * 0.3; });
  return (
    <group position={[0, -0.47, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <mesh ref={ring} raycast={noRaycast}><ringGeometry args={[0.75, 0.8, 64, 1, 0, Math.PI * 1.6]} />
        <meshBasicMaterial color={CYAN} transparent opacity={0.45} blending={THREE.AdditiveBlending} side={THREE.DoubleSide} /></mesh>
      <mesh raycast={noRaycast}><ringGeometry args={[1.05, 1.07, 64]} />
        <meshBasicMaterial color={CYAN} transparent opacity={0.25} blending={THREE.AdditiveBlending} side={THREE.DoubleSide} /></mesh>
      <mesh raycast={noRaycast}><circleGeometry args={[1.05, 64]} />
        <meshBasicMaterial color={CYAN} transparent opacity={0.05} blending={THREE.AdditiveBlending} side={THREE.DoubleSide} /></mesh>
    </group>
  );
}

export default function Body3D({ regions, hovered, onHover, motion, children }: {
  regions: RegionView[]; hovered: string | null; onHover: (id: string | null) => void; motion: boolean; children?: ReactNode;
}) {
  const byId = Object.fromEntries(regions.map((r) => [r.region, r]));
  const skin = byId.skin;
  return (
    <Canvas camera={{ position: [0, 1.55, 7.1], fov: 34 }} dpr={[1, 2]} gl={{ antialias: true, alpha: true }}
      onPointerMissed={() => onHover(null)} style={{ touchAction: "none" }}>
      <Controls autoRotate={motion && hovered === null} />
      <Shell color={skin ? SEVERITY_COLORS[skin.severity] : CYAN} opacity={skin ? (hovered === "skin" ? 0.22 : 0.15) : 0.09} />
      {Object.keys(REGION_PARTS).map((id) => (
        <Region key={id} id={id} view={byId[id]} hovered={hovered === id} onHover={onHover} motion={motion} />
      ))}
      <Floor motion={motion} />
      {children}
    </Canvas>
  );
}
