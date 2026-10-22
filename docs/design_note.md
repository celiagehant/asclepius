# Design note: the panel view and the 3D body

**Update (2026-10-21): the Asclepius look.** The app is now called Asclepius, after the Greek
god of medicine, with the Rod of Asclepius as its logo: one staff and one serpent, the true
medical symbol, rather than the two-snake caduceus.
- **Style:** white and near-white surfaces, a deep clinical navy (`#0b2a4a`), calm blues
  (`#1f5fae`, `#2f7de1`), and serif headings (Iowan Old Style or Palatino, from the system,
  so nothing is downloaded) over a clean sans-serif body.
- **The panel** is a still 3D conference room. Each member is a seated torso (white coat over
  scrubs in the specialty's color) around an oval table, with the coordinator at the head.
  Whoever is working leans in and nods. Name tags and speech bubbles are HTML overlays
  anchored to each person (at most two bubbles at a time), and the members not needed sit in
  an "on call" strip. Without WebGL, or on narrow screens, the card layout below is used.
- **The case board** became "What the doctors found": the doctor's avatar, a plain label
  ("Out of range", "Borderline", "Worth noting"), the body area with an icon; ids only on
  hover.
- **The body map** is a light card with a blue figure, and it is completely static: no
  hover effects, no pulsing, nothing moves, and it is only redrawn when something changes.
  Only the colored (flagged) organs can be clicked; a click shows below what the panel found
  there, and a second click clears it. The names under the body work the same way.

**Update (2026-10-22): ΛSCLEPIUS.**
- **Wordmark:** "ΛSCLEPIUS", with the Greek capital lambda standing in for the A, and the
  original Greek "Ἀσκληπιός" as the subtitle. Screen readers announce "Asclepius".
- **Logo:** a blue shield (protection) with a white medical cross (medicine) and a laurel
  wreath (Greece).
- **Public home page:** inspired by leading hospitals. A large serif promise and a drawing
  of the AI conference, then how it works in four steps, what you receive, a navy "Your
  data, protected" section (every claim is something the app really does), safety
  commitments, the panel, an FAQ and a closing call to action. The sign-in pages share its
  trust panel, and the logged-in home opens with a welcome banner.
- **The conference room:** in round 1 each doctor holds an open case file and reads it.
  Speech bubbles are short two-line previews above the name tags. The full discussion is in
  a "Conversation" tab beside "Findings", which switches on by itself during the debate.
  Replays run at a reading pace and can be paused or skipped.
- **The body map column** scrolls on its own below the sticky top bar.

**Update (2026-10-22, later): Greek, medical and hospital style.**
- **Emblem:** a Greek-coin medallion, navy with a gold rim, a staff, and one serpent that rises into three heads. "One serpent,
  many heads" stands for many specialists looking at one patient, a holistic approach; the welcome and log-in pages explain it.
- **Palette:** marble white (`#fbfaf6`), stone (`#f1ede3`), navy (`#0b2a4a`), Aegean blue (`#2f6fb5`), gold (`#b8893b`). The
  severity colors are unchanged.
- **Greek key (meander):** a thin gold divider under the header, above the footer and between sections. Gold eyebrows have
  short gold rules, and key cards have a gold top line.
- **Log-in / sign-up:** the original layout (text left, form right, no blue box), with a faint emblem watermark.
- **Logged-in home:** a light marble welcome card instead of a blue box.
- **Room:** the coordinator sorts the records and the doctors read their routed files before round 1.

The sections below describe the original layout and palette, kept for the record.

## Layout

The case page reads top to bottom, in the order a patient needs things:

1. **Emergency banner (only when something present now needs same-day care).** It sits
   above everything else, so nothing can push it out of view.
2. **The panel.** This is the story of the review. Cards sit in a semicircle around a
   table. The **coordinator sits at the head**, at the front facing the viewer, because it
   leads and speaks last.
   - **Inner arc:** the specialists on this case.
   - **Outer arc:** the rest of the roster, dimmed. The full roster is visible, so the
     user can see who was *not* called and why the panel is small.
   - Cards are spaced by equal arc length rather than equal angle, so they don't bunch up
     where the ellipse curves.
3. **Body map and case summary, side by side.** The body is on the left and stays pinned
   (sticky) while the summary scrolls, so a red region is never far from the text that
   explains it. While the panel is still working, the right column shows the live log
   instead of the summary.
4. **Chat** in a floating window that stays on screen while the patient scrolls.
5. **Details last:** specialist reports with exact quotes and sources, then "How the
   conference ran": the four rounds, who took part, and tokens and cost per round.

On screens narrower than 820 px the semicircle becomes a stacked grid (coordinator first),
the body moves above the summary, and speech bubbles become inline notes.

## How the panel comes alive

The panel is driven by the same server-sent events as the live log; there is no separate
animation script.

| Event | What the user sees |
|---|---|
| `document_routed` | Matching doctors light up in their color, move to the inner arc, and show "Reviewing <file>". |
| `panel_selected` | Doctors not chosen slide back to the outer arc and dim. |
| `specialist_started` / `tool_call` | The card glows and shows what it is doing ("Checking PubMed: …", "Checking FDA label: naproxen"). |
| `comment` (round 2) | A one-line speech bubble: agrees, disagrees, connection or answer. Bubbles fade as the conference moves on, and only show during the rounds. |
| `specialist_done` | A green check in the corner. |
| `coordinator_thinking` / `safety_check` | The coordinator card narrates the synthesis and the safety review. |

The pharmacist card shows a pill icon and the number of medications under review.

Finished cases offer **Replay the conference**, which plays the saved event log at about 7
events per second.

## Palette

| Role | Color | Why |
|---|---|---|
| Brand / text headings | `#0f3d4c` deep teal-navy | Calm, clinical, high contrast on white (AA for body text). |
| Accent | `#1f8a7e` teal | Links, progress and "why we ask" notes. Medical without the usual hospital blue. |
| Background | `#f4f7f7` near-white | Cards (`#ffffff`) separate from the page with a 1 px `#dbe5e7` line instead of heavy shadows. |
| Warning / disclaimer | `#fff6e5` with `#f0c36d` | Visible on every screen but not alarming. |
| Emergency banner | `#b3261e` red (medical), `#6b2fa0` purple (crisis) | Crisis resources use a calmer purple, not alarm red, to feel supportive rather than frightening. |
| Hologram | `#5ff3ff` cyan on `#061a24` | A dark panel inside a light page draws the eye. Additive blending makes overlapping translucent shapes glow like a projection. |

**Severity** (body regions and red flags) uses one consistent scale:

| Severity | Color | Meaning |
|---|---|---|
| Urgent | `#ff4d5e` red, pulsing | Needs care today |
| Discuss | `#ffb627` amber | Raise it at the next appointment, soon |
| Watch | `#4fa8ff` blue | Keep an eye on it |

Red, amber and blue (not green) stay distinguishable with the common red-green color
deficiencies. Color is never the only signal: every region also shows its severity as a
word in the legend and hover card, and urgent regions pulse.

**Specialty colors.** There are 19 distinct hues, one per roster entry. Each is used for
the card's top border, avatar and "AI specialist" tag, so a doctor is recognizable at a
glance across the panel, comments and reports. Hues that are easily confused sit apart in
the roster (cardiology red vs hematology raspberry). New specialties added to the registry
get a stable color generated from their id.

## The 3D body

- **A human figure built in code** with React Three Fiber: the torso is a lathe of a human
  side profile (shoulders, chest, waist, hips), arms and legs are tapered limbs with
  elbows, knees, hands and feet. No downloaded model, so nothing is licensed and nothing
  extra is fetched.
- **The hologram look:**
  - a faint cyan fill plus a sparse wireframe outline, so flagged organs stand out
  - additive blending
  - a still floor ring
  - faint scanlines on the panel background
- **The 16 regions** come from the coordinator's fixed list:
  - brain, eyes, ear-nose-throat, thyroid, heart, lungs, stomach, liver, intestines,
    kidneys, bladder and prostate, reproductive organs
  - blood: vessel tubes along the trunk and limbs
  - bones and joints: glowing joint spheres
  - skin: a faint tint of the whole figure (never a solid color that hides the organs)
  - mind: a halo above the head
- **Region states:** unflagged regions stay faint cyan, and flagged ones glow in their
  severity color.
- **Interaction:**
  - The body stands still in a fixed front view: no rotation, no dragging, no zoom. Only an
    urgent region, or one linked to the selected explanation card, pulses gently.
  - The shell ignores the pointer, so hover reaches the organs inside it.
  - Hovering shows the region, its severity, the coordinator's reason and which
    specialists flagged it. The legend chips below work the same way and are reachable by
    keyboard.
- **Fallback:** if WebGL is unavailable or the 3D view crashes (error boundary), a 2D SVG
  body with the same regions, colors and hover card is shown.
- **Loading:** the three.js code is loaded only when a body is on screen, so the rest of
  the app stays light (about 290 KB instead of about 1.2 MB).
- **Reduced motion:** with `prefers-reduced-motion`, pulsing, card glides and bubble
  animations are all turned off.

## Typography and tone

- **Type:** the system UI font stack, which is fast, familiar and legible. Body text is
  15–16 px, and labels in small caps are used only for categories (AI specialist, severity,
  comment type).
- **"AI specialist" tag:** on every card and in every report, so no agent is ever mistaken
  for a real physician.
