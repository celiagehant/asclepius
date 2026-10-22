// The conference room in 3D: an oval table seen from slightly above, with each panel member as a
// seated torso (head, hair, white coat over scrubs in the specialty's color, arms on the table).
// The room stands still; members who are working lean in and nod. Everything drawn in code (no
// downloaded models). Name tags, speech bubbles and threads are HTML/SVG overlays placed by
// projecting each seat's anchors to the screen (reported upward through onLayout).
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

export interface Seat {
  id: string;
  color: string;           // scrubs color (the specialty's color)
  angle: number;           // degrees around the table: 90 = head of the table, far side
  talking: boolean;        // working or speaking: leans in and nods
  reading?: boolean;       // round 1: holds the case file up and reads it
  focused: boolean;        // linked to the selected card or finding
  coordinator?: boolean;
}
export type Point = { x: number; y: number };   // percent of the room's width and height
export interface RoomLayout { head: Record<string, Point>; chest: Record<string, Point>; tag: Record<string, Point>; table: Point }

const SEAT_RX = 2.75, SEAT_RZ = 1.72;   // the ellipse the chairs stand on
const TABLE_RX = 2.2, TABLE_RZ = 1.25;
const TABLE_Y = 0.55;
const SKIN = ["#f1c7a5", "#e0ac87", "#c68863", "#a86b48", "#7f4f33", "#f3d3b8"];
const HAIR = ["#2b1d14", "#4a3222", "#1b1b1b", "#7a5a3a", "#a8a097", "#3b2a20"];

function hash(id: string): number {
  let h = 7;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h;
}

export function seatPosition(angle: number): { pos: THREE.Vector3; rotY: number } {
  const a = (angle * Math.PI) / 180;
  const pos = new THREE.Vector3(SEAT_RX * Math.cos(a), 0, -SEAT_RZ * Math.sin(a));
  return { pos, rotY: Math.atan2(-pos.x, -pos.z) };   // face the middle of the table
}

/** A limb (cylinder) stood between two points in the bust's local space. */
function Limb({ from, to, r, color }: { from: [number, number, number]; to: [number, number, number]; r: number; color: string }) {
  const { mid, q, len } = useMemo(() => {
    const a = new THREE.Vector3(...from), b = new THREE.Vector3(...to);
    const qq = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
    return { mid: a.clone().add(b).multiplyScalar(0.5), q: qq, len: a.distanceTo(b) };
  }, [from, to]);
  return (
    <mesh position={mid} quaternion={q}>
      <capsuleGeometry args={[r, len, 6, 12]} />
      <meshStandardMaterial color={color} roughness={0.75} />
    </mesh>
  );
}

function Bust({ seat }: { seat: Seat }) {
  const body = useRef<THREE.Group>(null);
  const head = useRef<THREE.Group>(null);
  const sheet = useRef<THREE.Group>(null);
  const h = hash(seat.id);
  const skin = SKIN[h % SKIN.length];
  const hair = HAIR[(h >> 3) % HAIR.length];
  const phase = (h % 100) / 16;
  const { pos, rotY } = useMemo(() => seatPosition(seat.angle), [seat.angle]);
  const coat = seat.focused ? "#e7f0ff" : "#f6f8fb";
  useFrame(({ clock }) => {
    const t = clock.elapsedTime + phase;
    if (body.current) {
      const lean = seat.talking ? 0.12 : 0.02;
      body.current.rotation.x += (lean - body.current.rotation.x) * 0.08;   // lean in toward the table while talking
    }
    if (head.current) {
      head.current.rotation.x = seat.reading ? 0.32 + 0.03 * Math.sin(t * 1.6)            // looking down at the file
        : seat.talking ? 0.1 * Math.sin(t * 5.2) : 0.015 * Math.sin(t * 1.1);             // nod while talking
      head.current.rotation.y = seat.talking ? 0.08 * Math.sin(t * 2.3) : 0;
    }
    if (sheet.current) sheet.current.rotation.x = seat.reading ? -0.15 + 0.12 * Math.max(0, Math.sin(t * 0.9)) : 0;  // turning a page
  });
  const scale = seat.coordinator ? 1.1 : 1;
  return (
    <group position={pos} rotation={[0, rotY, 0]} scale={scale}>
      {/* chair */}
      <mesh position={[0, 0.98, -0.34]}><boxGeometry args={[0.78, 0.95, 0.12]} /><meshStandardMaterial color="#1d3f6e" roughness={0.6} /></mesh>
      <mesh position={[0, 0.4, -0.05]}><boxGeometry args={[0.72, 0.1, 0.66]} /><meshStandardMaterial color="#244a7c" roughness={0.6} /></mesh>
      <group ref={body} position={[0, 0.45, 0]}>
        {/* torso: white coat over scrubs */}
        <mesh position={[0, 0.34, 0]} scale={[1.18, 1, 0.74]}><capsuleGeometry args={[0.3, 0.34, 8, 16]} /><meshStandardMaterial color={coat} roughness={0.8} /></mesh>
        <mesh position={[0, 0.58, 0.17]} rotation={[0.25, 0, Math.PI]} scale={[1, 1, 0.5]}><coneGeometry args={[0.13, 0.32, 3]} /><meshStandardMaterial color={seat.color} roughness={0.7} /></mesh>
        <mesh position={[0, 0.7, 0.02]}><cylinderGeometry args={[0.15, 0.17, 0.08, 16]} /><meshStandardMaterial color={seat.color} roughness={0.7} /></mesh>
        {/* arms: resting on the table, or holding the case file up while reading (round 1) */}
        {([-1, 1] as const).map((s) => seat.reading ? (
          <group key={s}>
            <Limb from={[s * 0.34, 0.56, 0]} to={[s * 0.3, 0.24, 0.22]} r={0.085} color={coat} />
            <Limb from={[s * 0.3, 0.24, 0.22]} to={[s * 0.17, 0.42, 0.46]} r={0.075} color={coat} />
            <mesh position={[s * 0.15, 0.45, 0.5]}><sphereGeometry args={[0.065, 12, 10]} /><meshStandardMaterial color={skin} roughness={0.7} /></mesh>
          </group>
        ) : (
          <group key={s}>
            <Limb from={[s * 0.34, 0.56, 0]} to={[s * 0.36, 0.22, 0.2]} r={0.085} color={coat} />
            <Limb from={[s * 0.36, 0.22, 0.2]} to={[s * 0.2, 0.16, 0.52]} r={0.075} color={coat} />
            <mesh position={[s * 0.17, 0.16, 0.6]}><sphereGeometry args={[0.065, 12, 10]} /><meshStandardMaterial color={skin} roughness={0.7} /></mesh>
          </group>
        ))}
        {/* the case file: open in the hands while reading, closed on the table otherwise */}
        {seat.reading ? (
          <group position={[0, 0.5, 0.52]} rotation={[-0.95, 0, 0]}>
            <mesh><boxGeometry args={[0.46, 0.015, 0.32]} /><meshStandardMaterial color="#2f5f9e" roughness={0.6} /></mesh>
            <mesh position={[-0.11, 0.012, 0]}><boxGeometry args={[0.21, 0.01, 0.29]} /><meshStandardMaterial color="#fbf8f0" roughness={0.9} /></mesh>
            <group ref={sheet} position={[0.005, 0.014, 0]}>
              <mesh position={[0.11, 0, 0]}><boxGeometry args={[0.21, 0.008, 0.29]} /><meshStandardMaterial color="#ffffff" roughness={0.9} /></mesh>
              {[-0.08, -0.04, 0, 0.04, 0.08].map((z) => (
                <mesh key={z} position={[0.11, 0.006, z]}><boxGeometry args={[0.16, 0.002, 0.008]} /><meshBasicMaterial color="#9fb3cc" /></mesh>
              ))}
            </group>
          </group>
        ) : (
          <group position={[0, 0.14, 0.72]} rotation={[0, 0.25, 0]}>
            <mesh><boxGeometry args={[0.3, 0.025, 0.22]} /><meshStandardMaterial color="#2f5f9e" roughness={0.6} /></mesh>
            <mesh position={[0, 0.016, 0]}><boxGeometry args={[0.27, 0.008, 0.2]} /><meshStandardMaterial color="#fbf8f0" roughness={0.9} /></mesh>
          </group>
        )}
        {/* neck and head */}
        <mesh position={[0, 0.8, 0]}><cylinderGeometry args={[0.08, 0.09, 0.16, 12]} /><meshStandardMaterial color={skin} roughness={0.7} /></mesh>
        <group ref={head} position={[0, 1.02, 0]}>
          <mesh scale={[0.92, 1.06, 0.96]}><sphereGeometry args={[0.2, 24, 18]} /><meshStandardMaterial color={skin} roughness={0.65} /></mesh>
          <mesh position={[0, 0.035, -0.02]} scale={[0.97, 1.0, 1.0]}>
            <sphereGeometry args={[0.212, 24, 14, 0, Math.PI * 2, 0, Math.PI * 0.55]} />
            <meshStandardMaterial color={hair} roughness={0.9} />
          </mesh>
          {/* eyes, so everyone looks toward the table */}
          {([-1, 1] as const).map((s) => (
            <mesh key={s} position={[s * 0.065, 0.0, 0.18]}><sphereGeometry args={[0.018, 8, 6]} /><meshBasicMaterial color="#1b2633" /></mesh>
          ))}
        </group>
      </group>
    </group>
  );
}

function Table() {
  return (
    <group position={[0, 0, 0]}>
      <mesh position={[0, TABLE_Y, 0]} scale={[TABLE_RX, 1, TABLE_RZ]}>
        <cylinderGeometry args={[1, 1, 0.09, 64]} /><meshStandardMaterial color="#ffffff" roughness={0.35} />
      </mesh>
      <mesh position={[0, TABLE_Y + 0.047, 0]} rotation={[-Math.PI / 2, 0, 0]} scale={[TABLE_RX, TABLE_RZ, 1]}>
        <ringGeometry args={[0.965, 1, 64]} /><meshBasicMaterial color="#b8893b" transparent opacity={0.75} />
      </mesh>
      <mesh position={[0, TABLE_Y + 0.048, 0]} rotation={[-Math.PI / 2, 0, 0]} scale={[0.75, 0.42, 1]}>
        <circleGeometry args={[1, 48]} /><meshBasicMaterial color="#f3eee2" />
      </mesh>
      <mesh position={[0, TABLE_Y / 2, 0]}><cylinderGeometry args={[0.35, 0.5, TABLE_Y, 24]} /><meshStandardMaterial color="#e4dccb" roughness={0.6} /></mesh>
      <mesh position={[0, 0, 0]} rotation={[-Math.PI / 2, 0, 0]} scale={[4.3, 3.1, 1]}>
        <circleGeometry args={[1, 64]} /><meshBasicMaterial color="#ece5d6" />
      </mesh>
    </group>
  );
}

/** Projects each seat's anchors to screen percentages whenever the canvas size changes. */
function Projector({ seats, onLayout }: { seats: Seat[]; onLayout: (l: RoomLayout) => void }) {
  const { camera, size } = useThree();
  const key = seats.map((s) => `${s.id}:${s.angle}:${s.coordinator ? 1 : 0}`).join("|");
  useEffect(() => {
    camera.lookAt(0, 1.0, -0.25);
    camera.updateMatrixWorld();
    const toPct = (v: THREE.Vector3): Point => {
      const p = v.clone().project(camera);
      return { x: ((p.x + 1) / 2) * 100, y: ((1 - p.y) / 2) * 100 };
    };
    const layout: RoomLayout = { head: {}, chest: {}, tag: {}, table: toPct(new THREE.Vector3(0, TABLE_Y + 0.05, 0.15)) };
    for (const s of seats) {
      const { pos, rotY } = seatPosition(s.angle);
      const k = s.coordinator ? 1.1 : 1;
      const local = (x: number, y: number, z: number) =>
        new THREE.Vector3(x * k, y * k, z * k).applyAxisAngle(new THREE.Vector3(0, 1, 0), rotY).add(pos);
      layout.tag[s.id] = toPct(local(0, 1.72, 0));    // name tag just above the head
      layout.head[s.id] = toPct(local(0, 2.3, 0));    // speech bubble above the name tag
      layout.chest[s.id] = toPct(local(0, 0.95, 0.1));
    }
    onLayout(layout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera, size.width, size.height, key]);
  return null;
}

export default function ConferenceRoom3D({ seats, onLayout }: { seats: Seat[]; onLayout: (l: RoomLayout) => void }) {
  return (
    <Canvas camera={{ position: [0, 4.4, 7.4], fov: 38 }} dpr={[1, 2]} gl={{ antialias: true, alpha: true }}>
      <hemisphereLight args={["#ffffff", "#dbe6f5", 1.25]} />
      <directionalLight position={[3, 6, 4]} intensity={1.15} />
      <directionalLight position={[-4, 3, 2]} intensity={0.35} />
      <Projector seats={seats} onLayout={onLayout} />
      <Table />
      {seats.map((s) => <Bust key={s.id} seat={s} />)}
    </Canvas>
  );
}
