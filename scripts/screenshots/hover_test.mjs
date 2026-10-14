// Drive headless Chrome over CDP: log in, open the case, sweep the mouse over the 3D body.
import { writeFileSync } from "node:fs";
const [port, out] = [process.argv[2], process.argv[3]];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 40 && !target; i++) {
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page"); } catch { await sleep(250); }
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } });
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;

await send("Emulation.setDeviceMetricsOverride", { width: 1360, height: 900, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: "http://127.0.0.1:8000/" }); await sleep(1500);
await evaluate(`fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({email:'${process.env.CC_SHOT_EMAIL}', password:'${process.env.CC_SHOT_PASSWORD}'})}).then(r => r.status)`);
await send("Page.navigate", { url: `http://127.0.0.1:8000/#/cases/${process.env.CC_SHOT_CASE ?? 1}` }); await sleep(300);
await send("Page.reload", {}); await sleep(5000);
console.log("page:", JSON.stringify(await evaluate(`({hash: location.hash, h1: document.querySelector('h1')?.textContent, canvas: !!document.querySelector('.hologram canvas'), hologram: !!document.querySelector('.hologram'), err: document.querySelector('.error-text')?.textContent})`)));
await evaluate(`document.querySelector('.room-middle')?.scrollIntoView(); 1`); await sleep(2500);
console.log("after wait:", JSON.stringify(await evaluate(`({canvas: !!document.querySelector('.hologram canvas'), loading: document.querySelector('.holo-loading')?.textContent, body2d: !!document.querySelector('.body2d')})`)));
const info = await evaluate(`(() => { const c = document.querySelector('.hologram canvas'); const r = c.getBoundingClientRect();
  window.__seen = new Set(); new MutationObserver(() => { const t = document.querySelector('.holo-title')?.textContent; if (t) window.__seen.add(t); })
  .observe(document.querySelector('.holo-info'), { subtree: true, childList: true, characterData: true });
  return { x: r.left, y: r.top, w: r.width, h: r.height, webgl: !!c.getContext }; })()`);
console.log("canvas", JSON.stringify(info));
let best = null;
for (let fy = 0.06; fy < 0.7; fy += 0.02) {
  for (let fx = 0.3; fx <= 0.7; fx += 0.025) {
    const x = info.x + info.w * fx, y = info.y + info.h * fy;
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
    await sleep(12);
    const t = await evaluate(`document.querySelector('.holo-title')?.textContent || ''`);
    if (t.includes("urgent") && !best) best = { x, y, t };
  }
}
console.log("regions hovered:", JSON.stringify(await evaluate(`[...window.__seen]`)));
if (best) {
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: best.x, y: best.y }); await sleep(700);
  const sy = await evaluate("window.scrollY");
  const shot = await send("Page.captureScreenshot", { format: "png", clip: { x: info.x - 16, y: info.y + sy - 60, width: info.w + 32, height: info.h + 150, scale: 1 } });
  writeFileSync(out, Buffer.from(shot.result.data, "base64"));
  console.log("screenshot while hovering:", best.t);
}
ws.close(); process.exit(0);
