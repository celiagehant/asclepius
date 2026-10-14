// Ask the panel through the UI in headless Chrome; capture the panel lighting up and the answer.
import { writeFileSync } from "node:fs";
const [port, outDir] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 40 && !target; i++) { try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page"); } catch { await sleep(250); } }
const ws = new WebSocket(target.webSocketDebuggerUrl); await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } });
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (e) => (await send("Runtime.evaluate", { expression: e, awaitPromise: true, returnByValue: true })).result?.result?.value;
async function shoot(selector, name) {
  const r = await ev(`(() => { const el = document.querySelector('${selector}'); if (!el) return null; const b = el.getBoundingClientRect(); return { x: b.left, y: b.top + scrollY, w: b.width, h: Math.min(b.height, 1400) }; })()`);
  if (!r) return console.log("missing", selector);
  const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: r.x, y: r.y, width: r.w, height: r.h, scale: 1 } });
  writeFileSync(`${outDir}/${name}.png`, Buffer.from(shot.result.data, "base64")); console.log("saved", name);
}
await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: "http://127.0.0.1:8000/" }); await sleep(1200);
await ev(`fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({email:'${process.env.CC_SHOT_EMAIL}', password:'${process.env.CC_SHOT_PASSWORD}'})}).then(r => r.status)`);
await send("Page.navigate", { url: `http://127.0.0.1:8000/#/cases/${process.env.CC_SHOT_CASE ?? 1}` }); await sleep(300); await send("Page.reload", {}); await sleep(5000);
await ev(`document.querySelector('.disclaimer-bar').style.display = 'none'; 1`);
console.log("history:", await ev(`document.querySelectorAll('.msg-user, .msg-panel, .chat .emergency').length`));
const q = process.env.CC_CHAT_Q ?? "Why might he feel dizzy when he stands up?";
await ev(`(() => { const ta = document.querySelector('.chat-input textarea'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(ta, ${JSON.stringify(q)}); ta.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
await sleep(200);
await ev(`document.querySelector('.chat-input button').click(); 1`);
let litShot = false;
for (let i = 0; i < 200; i++) {
  const st = await ev(`({ working: document.querySelectorAll('.doctor.is-working').length, pending: !!document.querySelector('.chat-pending'), status: document.querySelector('.chat-pending .muted')?.textContent })`);
  if (!litShot && st.working > 0) {
    console.log("while answering:", st.status, "| doctors lit:", st.working);
    await ev(`window.scrollTo(0, 0); 1`); await sleep(200);
    await shoot(".panel-table-card", "chat_panel_lit");
    await ev(`document.querySelector('.chat').scrollIntoView(); 1`); await sleep(200);
    await shoot(".chat", "chat_pending");
    litShot = true;
  }
  if (!st.pending && litShot) break;
  await sleep(300);
}
await sleep(500);
console.log("answer:", JSON.stringify(await ev(`(() => { const last = [...document.querySelectorAll('.msg-panel')].pop(); return last ? { who: [...last.querySelectorAll('.answer-who strong')].map(x => x.textContent), reviewed: last.querySelector('.reviewed')?.textContent } : null; })()`)));
await ev(`window.scrollTo(0, 0); 1`); await sleep(300);
await shoot(".panel-table-card", "chat_panel_answered");
await ev(`document.querySelector('.chat').scrollIntoView(); 1`); await sleep(300);
await shoot(".chat", "chat_answer");
ws.close(); process.exit(0);
