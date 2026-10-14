// Capture report screenshots of the case room. Usage: node capture.mjs <port> <outdir> <mode: main|nogl>
import { writeFileSync } from "node:fs";
const [port, outDir, mode] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 40 && !target; i++) { try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page"); } catch { await sleep(250); } }
const ws = new WebSocket(target.webSocketDebuggerUrl); await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } });
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (e) => (await send("Runtime.evaluate", { expression: e, awaitPromise: true, returnByValue: true })).result?.result?.value;
async function shoot(selector, name, pad = 0) {
  const r = await ev(`(() => { const el = document.querySelector('${selector}'); if (!el) return null; const b = el.getBoundingClientRect(); return { x: b.left, y: b.top + scrollY, w: b.width, h: b.height }; })()`);
  if (!r) { console.log("missing", selector); return; }
  const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: Math.max(r.x - pad, 0), y: Math.max(r.y - pad, 0), width: r.w + pad * 2, height: r.h + pad * 2, scale: 1 } });
  writeFileSync(`${outDir}/${name}.png`, Buffer.from(shot.result.data, "base64")); console.log("saved", name);
}
await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: "http://127.0.0.1:8000/" }); await sleep(1200);
await ev(`fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({email:'${process.env.CC_SHOT_EMAIL}', password:'${process.env.CC_SHOT_PASSWORD}'})}).then(r => r.status)`);
await send("Page.navigate", { url: "http://127.0.0.1:8000/#/cases/1" }); await sleep(300); await send("Page.reload", {}); await sleep(5000);
await ev("document.querySelector('.disclaimer-bar').style.display = 'none'; 1");  // cropped report images only
if (mode === "tokens") {
  await shoot(".panel-table-card", "panel_spend_meters");
  await ev(`(() => { const d = document.querySelector('.run-details'); d.open = true; d.dispatchEvent(new Event('toggle')); d.scrollIntoView(); return 1; })()`);
  await sleep(2500);
  await ev(`document.querySelectorAll('.run-details .call-list').forEach(d => d.open = false); 1`);
  await shoot(".run-details", "run_details");
} else if (mode === "nogl") {
  console.log("fallback:", JSON.stringify(await ev(`({ canvas: !!document.querySelector('.hologram canvas'), svg: !!document.querySelector('.body2d') })`)));
  await ev(`document.querySelector('.body-card').scrollIntoView(); document.querySelector('.region-legend li')?.dispatchEvent(new MouseEvent('mouseover', {bubbles: true})); 1`); await sleep(500);
  await shoot(".body-card", "body_2d_fallback");
} else {
  await shoot(".panel-table-card", "panel_final");
  await shoot(".room-middle", "body_and_summary");
  await ev(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('Replay')).click(); 1`);
  for (let i = 0; i < 600; i++) {
    const st = await ev(`({ stage: document.querySelector('.table-stage')?.textContent, bubbles: document.querySelectorAll('.bubble').length })`);
    if (st.stage?.startsWith("Round 2") && st.bubbles >= 2) break;
    await sleep(30);
  }
  await sleep(150);
  await shoot(".panel-table-card", "panel_round2_bubbles");
  for (let i = 0; i < 80; i++) { if ((await ev(`document.querySelector('.table-stage')?.textContent`))?.startsWith("Round 1")) break; await sleep(60); }
}
ws.close(); process.exit(0);
