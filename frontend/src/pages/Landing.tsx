import { colorOf, SPECIALTY_ICONS } from "../lib/panel";

// The public home page. Inspired by the calm, confident look of leading hospitals: one clear
// promise, how it works, what you receive, how your data is protected, and safety first.
// Every privacy claim here is something the app actually does (see README: accounts and privacy).

const PANEL = [
  ["cardiology", "Cardiology"], ["endocrinology", "Endocrinology"], ["gastroenterology", "Gastroenterology"], ["hematology", "Hematology"],
  ["nephrology", "Nephrology"], ["neurology", "Neurology"], ["rheumatology", "Rheumatology"], ["pulmonology", "Pulmonology"],
  ["dermatology", "Dermatology"], ["obstetrics_gynecology", "OB/GYN"], ["urology", "Urology"], ["orthopedics", "Orthopedics"],
  ["ophthalmology", "Ophthalmology"], ["otolaryngology", "ENT"], ["infectious_disease", "Infectious disease"], ["psychiatry", "Psychiatry"],
  ["clinical_pharmacist", "Clinical pharmacist"], ["lifestyle", "Lifestyle & prevention"], ["internal_medicine", "Internal medicine"], ["pediatrics", "Pediatrics"],
] as const;

export default function Landing({ publicDemo }: { publicDemo?: boolean }) {
  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  return (
    <div className="landing">
      <section className="hero-x">
        <div className="hero-copy">
          <p className="hero-eyebrow">AI case conference · for patients who see many doctors</p>
          <h1>All your specialists,<br /><em>finally at one table.</em></h1>
          <p className="hero-lead">Upload the records from each of your doctors. A panel of AI specialist agents reviews every one, connects
            what no single visit could, debates what fits, and gives you clear questions to bring to your own doctors.</p>
          <div className="hero-ctas">
            <a className="btn btn-xl" href="#/signup">Create your free account</a>
            <button className="btn btn-ghost btn-xl" onClick={() => scrollTo("how")}>See how it works</button>
          </div>
          <ul className="trust-row">
            <li><span aria-hidden>🔒</span> Private to your account</li>
            <li><span aria-hidden>🗑️</span> Delete everything in one click</li>
            <li><span aria-hidden>🛡️</span> Every answer safety-checked</li>
          </ul>
          {publicDemo && <p className="hero-demo"><strong>Demo:</strong> please use the fictional demo patients, not real medical records.</p>}
          <p className="hero-login muted small">Already have an account? <a href="#/login">Log in</a></p>
        </div>
        <div className="hero-art" aria-hidden><ConferenceArt /></div>
      </section>

      <section className="stats-strip" aria-label="At a glance">
        <div><strong>20</strong><span>AI specialist agents on call</span></div>
        <div><strong>4</strong><span>rounds of conference, from reading to recommendations</span></div>
        <div><strong>100%</strong><span>of findings quoted from your own records</span></div>
        <div><strong>~2 min</strong><span>for the whole panel to review a case</span></div>
      </section>

      <section id="how" className="l-section">
        <p className="l-eyebrow">How it works</p>
        <h2>A real case conference, run by AI specialist agents</h2>
        <p className="l-lead">In top hospitals, complex patients are discussed by a team of specialists around one table. Asclepius brings
          that idea to anyone with records from many doctors.</p>
        <ol className="steps-x">
          <li><span className="step-n">1</span><h3>Share your records</h3><p>Lab reports, visit notes, scans and photos of papers from every doctor, plus a short health questionnaire.</p></li>
          <li><span className="step-n">2</span><h3>Each specialist reads</h3><p>The right specialists are chosen for your case. Each reads only the records meant for them and posts what they find.</p></li>
          <li><span className="step-n">3</span><h3>They connect and debate</h3><p>The panel links findings across specialties. The coordinator challenges every idea with simpler explanations.</p></li>
          <li><span className="step-n">4</span><h3>You get a clear plan</h3><p>Possible explanations to discuss, who to see first, questions for each doctor and safe self-care steps.</p></li>
        </ol>
      </section>

      <section className="l-section l-split">
        <div>
          <p className="l-eyebrow">What you receive</p>
          <h2>Clarity to bring to your next appointment</h2>
          <ul className="check-list">
            <li><strong>Possible explanations, two-sided.</strong> Each one shows why it could fit and what argues against it, always labelled “not a diagnosis”.</li>
            <li><strong>Who to see first,</strong> in order, with anything urgent at the top.</li>
            <li><strong>Questions for each of your doctors,</strong> using their names.</li>
            <li><strong>Medicines to review with your prescribers,</strong> from a clinical pharmacist agent that checks every list together.</li>
            <li><strong>A body map</strong> showing where the findings are, and a chat to ask the panel follow-up questions.</li>
          </ul>
        </div>
        <div className="preview-card" aria-hidden>
          <div className="pv-top"><span className="pv-id">C1</span><span className="pv-strength">Stronger match</span></div>
          <h3>Slow blood loss in the gut could connect your tiredness, racing heart and low iron.</h3>
          <p className="pv-label">ⓘ Possible explanation to discuss with your doctor, not a diagnosis.</p>
          <div className="pv-cols">
            <div><h4>Why it could fit</h4><p>Very low ferritin · positive stool test · ulcer on endoscopy</p></div>
            <div><h4>What argues against it</h4><p>Heavier periods could also explain low iron</p></div>
          </div>
          <div className="pv-who">{["hematology", "gastroenterology", "cardiology"].map((id) => (
            <span key={id} className="pv-dot" style={{ ["--c" as string]: colorOf(id) }}>{SPECIALTY_ICONS[id]}</span>))}</div>
        </div>
      </section>

      <section id="privacy" className="l-section l-privacy">
        <p className="l-eyebrow light">Your data, protected</p>
        <h2>Your health story stays yours</h2>
        <div className="privacy-grid">
          <div><span className="pi" aria-hidden>👤</span><h3>Only you can open your case</h3><p>Every request is checked against your account. No other user can see your records, summaries or chats.</p></div>
          <div><span className="pi" aria-hidden>🔑</span><h3>Your password is never stored</h3><p>It is scrambled with scrypt, a one-way method, so even we cannot read it. Sessions use secure, HttpOnly cookies.</p></div>
          <div><span className="pi" aria-hidden>🗑️</span><h3>Delete everything, anytime</h3><p>One click removes your records, summaries, chats and, if you wish, your account.</p></div>
          <div><span className="pi" aria-hidden>🤝</span><h3>Shared only to prepare your summary</h3><p>Your records go to the AI service only to prepare your review. Medical libraries receive search terms, never your files.</p></div>
          <div><span className="pi" aria-hidden>🔐</span><h3>Encrypted connection</h3><p>On the live site, everything you send travels over HTTPS.</p></div>
          <div><span className="pi" aria-hidden>🧾</span><h3>Files read safely</h3><p>Hidden or invisible text in uploaded files is removed before any AI reads them, so a tampered document cannot steer the panel.</p></div>
        </div>
      </section>

      <section className="l-section">
        <p className="l-eyebrow">Safety first</p>
        <h2>Built to support your doctors, never to replace them</h2>
        <div className="safety-grid">
          <div><h3>Not a diagnosis</h3><p>Asclepius never diagnoses and never tells you to start or stop a medicine.</p></div>
          <div><h3>AI agents, clearly labelled</h3><p>Every panel member is an AI specialist agent, not a licensed physician, and says so.</p></div>
          <div><h3>A safety reviewer checks everything</h3><p>Every summary and chat answer is reviewed, then checked again by code, before you see it.</p></div>
          <div><h3>Emergencies come first</h3><p>Anything that needs care today is shown at the top, with who to call.</p></div>
        </div>
      </section>

      <section className="l-section">
        <p className="l-eyebrow">Meet the panel</p>
        <h2>Twenty AI specialist agents, on call for your case</h2>
        <p className="l-lead">Only the specialists your records call for join the table, led by internal medicine (or pediatrics for a child).</p>
        <div className="panel-chips">{PANEL.map(([id, name]) => (
          <span key={id} className="panel-chip"><span className="pc-dot" style={{ ["--c" as string]: colorOf(id) }}>{SPECIALTY_ICONS[id] ?? "•"}</span>{name}</span>
        ))}</div>
      </section>

      <section className="l-section l-faq">
        <p className="l-eyebrow">Questions</p>
        <h2>Good to know</h2>
        <details><summary>Is this a diagnosis or medical advice?</summary><p>No. It is an organized, educational summary to discuss with your own doctors. In an emergency call 911.</p></details>
        <details><summary>Who are the doctors at the table?</summary><p>AI specialist agents, each given a specialty's scope. None is a real or licensed physician.</p></details>
        <details><summary>What happens to my files?</summary><p>They are stored in your account so you can come back to your case, sent to the AI service only to prepare your review, and removed when you delete your data.</p></details>
        <details><summary>How long does a review take?</summary><p>About two minutes for the whole panel; chat answers take a few seconds.</p></details>
      </section>

      <section className="l-cta">
        <h2>Bring your specialists together.</h2>
        <p>Create a free account, answer a short questionnaire, and convene your panel.</p>
        <a className="btn btn-xl btn-light" href="#/signup">Get started</a>
      </section>

      <footer className="l-footer">
        <span><span className="lambda">Λ</span>SCLEPIUS · AI case conference</span>
        <span>An educational project (MGT 409, Yale SOM). Not a medical device.</span>
      </footer>
    </div>
  );
}

/** The hero drawing: a round table seen from above, AI specialists around it, findings linking across. */
function ConferenceArt() {
  const seats = [
    ["internal_medicine", 0], ["cardiology", 51], ["hematology", 103], ["gastroenterology", 154], ["clinical_pharmacist", 206],
    ["endocrinology", 257], ["nephrology", 309],
  ] as const;
  const pos = (deg: number, r: number) => {
    const a = ((deg - 90) * Math.PI) / 180;
    return [200 + r * Math.cos(a), 200 + r * Math.sin(a)];
  };
  return (
    <svg viewBox="0 0 400 400" className="conf-art">
      <defs>
        <radialGradient id="halo" cx="50%" cy="50%" r="50%"><stop offset="0" stopColor="#dce9fb" /><stop offset="1" stopColor="#f6f8fb" stopOpacity="0" /></radialGradient>
        <linearGradient id="tbl" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#ffffff" /><stop offset="1" stopColor="#eaf1fb" /></linearGradient>
        <filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="6" stdDeviation="8" floodColor="#0b2a4a" floodOpacity="0.15" /></filter>
      </defs>
      <circle cx="200" cy="200" r="195" fill="url(#halo)" />
      <circle cx="200" cy="200" r="112" fill="url(#tbl)" stroke="#2f7de1" strokeOpacity="0.35" strokeWidth="2" filter="url(#soft)" />
      {[[0, 2], [1, 3], [2, 4], [5, 1], [6, 3], [0, 5]].map(([a, b], i) => {
        const [x1, y1] = pos(seats[a][1], 150), [x2, y2] = pos(seats[b][1], 150);
        return <path key={i} d={`M${x1} ${y1} Q200 200 ${x2} ${y2}`} fill="none" stroke={i === 5 ? "#f0961a" : "#2f7de1"}
          strokeOpacity={i === 5 ? 0.8 : 0.45} strokeWidth="2.2" strokeDasharray={i === 5 ? "6 5" : undefined} className="art-line" />;
      })}
      <g transform="translate(168 168)">
        <rect width="64" height="64" rx="10" fill="#ffffff" stroke="#c9daf3" />
        <rect x="12" y="14" width="40" height="5" rx="2.5" fill="#2f7de1" opacity="0.7" />
        {[26, 34, 42, 50].map((y) => <rect key={y} x="12" y={y} width={y === 50 ? 24 : 40} height="3.5" rx="1.75" fill="#c4d3e6" />)}
      </g>
      {seats.map(([id, deg]) => {
        const [x, y] = pos(deg, 150);
        return (
          <g key={id} transform={`translate(${x} ${y})`} filter="url(#soft)">
            <circle r={id === "internal_medicine" ? 27 : 23} fill="#ffffff" />
            <circle r={id === "internal_medicine" ? 23 : 19} fill={colorOf(id)} />
            <text textAnchor="middle" dominantBaseline="central" fontSize={id === "internal_medicine" ? 18 : 15} fill="#fff">{SPECIALTY_ICONS[id]}</text>
          </g>
        );
      })}
      <g transform="translate(96 364)" filter="url(#soft)">
        <rect width="208" height="32" rx="16" fill="#ffffff" />
        <text x="104" y="20.5" textAnchor="middle" fontSize="10.5" fill="#1f5fae"><tspan fontWeight="700">Possible explanation</tspan> · not a diagnosis</text>
      </g>
      <g transform="translate(14 36)" filter="url(#soft)">
        <rect width="124" height="46" rx="12" fill="#ffffff" />
        <text x="14" y="20" fontSize="10.5" fontWeight="700" fill="#1e7d4f">✓ Safety-checked</text>
        <text x="14" y="35" fontSize="10" fill="#5a6b80">before you see it</text>
      </g>
    </svg>
  );
}
