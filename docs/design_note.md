# Design note: the panel view and the 3D body

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
