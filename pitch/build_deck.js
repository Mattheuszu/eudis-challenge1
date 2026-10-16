// Builds pitch/GPS_Under_Attack_pitch.pptx from the project's results.
// Run from the repo root:  node pitch/build_deck.js
// (needs: cd pitch && npm install pptxgenjs react-icons react react-dom sharp)
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

const ROOT = path.resolve(__dirname, "..");
const IMG = (f) => path.join(ROOT, f);
const OUT = path.join(__dirname, "GPS_Under_Attack_pitch.pptx");
const APPLY_THEME = process.env.PPTX_APPLY_THEME; // path to the pptx skill's scripts/apply_theme.js (optional)

// ---------------- theme ----------------
const THEME = {
  name: "GPS Under Attack",
  headFontFace: "Arial",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "0E1621", lt1: "FFFFFF", dk2: "17283A", lt2: "E8EDF2",
    accent1: "F26B1D", // signal orange - our motif
    accent2: "2EB872", // green - works / safe
    accent3: "E5484D", // red - threat / today
    accent4: "4EA8DE", // sky blue
    accent5: "93A1B3", // muted text
    accent6: "F5C451", // amber
    hlink: "4EA8DE", folHlink: "93A1B3",
  },
};
const HEX = THEME.colors;
const BG = HEX.dk1;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.title = "GPS Under Attack - EUDIS Defence Hackathon 2026";
pres.author = "Den and Guled";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;
const W = 13.333;

// ---------------- icons ----------------
async function icon(Comp, hex = "FFFFFF", size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + hex, size: String(size) }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

// ---------------- layouts ----------------
const FOOTER = "EUDIS Defence Hackathon 2026 · Challenge 1 · GNSS-denied navigation · Den & Guled";
pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: BG },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.7, y: 1.55, w: 6.2, h: 2.3, fontSize: 40, bold: true,
                                color: C.background1, valign: "top", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.7, y: 4.0, w: 6.0, h: 1.2, fontSize: 18,
                                color: C.background2, valign: "top", align: "left", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT_DARK",
  background: { color: BG },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.38, w: 10.0, h: 0.85, fontSize: 28, bold: true,
                                color: C.background1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { text: { text: FOOTER, options: { x: 0.6, y: 7.05, w: 10.5, h: 0.3, fontSize: 10, color: C.accent5, margin: 0 } } },
  ],
  slideNumber: { x: 12.3, y: 7.05, w: 0.45, h: 0.3, fontSize: 10, color: C.accent5, align: "right" },
});

// ---------------- helpers ----------------
function tag(slide, text) { // criterion pill, top right: the deck's motif
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 10.85, y: 0.55, w: 1.9, h: 0.42, rectRadius: 0.21,
    fill: { color: C.text2 }, line: { color: C.accent1, width: 1.25 }, objectName: "criterion tag" });
  slide.addText(text, { x: 10.85, y: 0.55, w: 1.9, h: 0.42, fontSize: 11, bold: true, color: C.accent1,
    align: "center", valign: "middle", charSpacing: 2, margin: 0, isTextBox: true, objectName: "criterion tag text" });
}

function picture(slide, file, x, y, w, ratio, name) { // white rounded card + image; returns bottom y
  const h = w / ratio;
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x - 0.07, y: y - 0.07, w: w + 0.14, h: h + 0.14, rectRadius: 0.08,
    fill: { color: C.background1 }, line: { color: C.background1, width: 0 }, objectName: name + " frame" });
  slide.addImage({ path: IMG(file), x, y, w, h, altText: name, objectName: name });
  return y + h;
}

function stat(slide, x, y, w, h, value, label, color, valueSize = 30) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.1, fill: { color: C.text2 },
    line: { color: C.text2, width: 0 }, objectName: "stat card " + value });
  slide.addText(value, { x: x + 0.15, y: y + 0.08, w: w - 0.3, h: h * 0.55, fontSize: valueSize, bold: true, color,
    valign: "bottom", margin: 0, fit: "shrink", isTextBox: true, objectName: "stat value " + value });
  slide.addText(label, { x: x + 0.15, y: y + 0.1 + h * 0.55, w: w - 0.3, h: h * 0.4 - 0.12, fontSize: 12,
    color: C.background2, valign: "top", margin: 0, isTextBox: true, objectName: "stat label " + value });
}

async function iconRow(slide, x, y, w, Comp, head, text, color = HEX.accent1) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: 0.6, h: 0.6, fill: { color: C.text2 }, line: { color, width: 1.5 },
    objectName: "icon circle " + head });
  slide.addImage({ data: await icon(Comp, color), x: x + 0.15, y: y + 0.15, w: 0.3, h: 0.3, altText: head });
  slide.addText([
    { text: head, options: { bold: true, fontSize: 15, color: C.background1, breakLine: true } },
    { text, options: { fontSize: 13, color: C.background2 } },
  ], { x: x + 0.8, y: y - 0.05, w: w - 0.8, h: 0.95, valign: "top", margin: 0, isTextBox: true, objectName: "row " + head });
}

function caption(slide, text, x, y, w, h = 0.35) {
  slide.addText(text, { x, y, w, h, fontSize: 11, italic: true, color: C.accent5, margin: 0, valign: "top",
    isTextBox: true, objectName: "caption" });
}

// ---------------- slides ----------------
async function build() {
  // 1. Title ---------------------------------------------------------------
  pres.addSection({ title: "Opening" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Opening" });
  s.addText("EUDIS DEFENCE HACKATHON 2026 · CHALLENGE 1", { x: 0.7, y: 0.9, w: 6.5, h: 0.4, fontSize: 13, bold: true,
    color: C.accent1, charSpacing: 2, margin: 0, isTextBox: true });
  s.addText("One drone gets jammed — the whole swarm learns", { placeholder: "title" });
  s.addText("GPS-denied navigation that detects the attack, shares it, and still completes the mission",
    { placeholder: "body" });
  s.addText([{ text: "Den", options: { bold: true, color: C.background1 } },
             { text: "  cyber security    ", options: { color: C.accent5 } },
             { text: "Guled", options: { bold: true, color: C.background1 } },
             { text: "  computer engineering", options: { color: C.accent5 } }],
    { x: 0.7, y: 5.6, w: 6.2, h: 0.4, fontSize: 15, margin: 0, isTextBox: true });
  picture(s, "gazebo_base.png", 7.35, 2.05, 5.4, 1289 / 609, "Gazebo battlefield with jammer dome and target");
  caption(s, "Our live simulation: real PX4 autopilots, an enemy GPS jammer (red dome) and the target", 7.35, 4.75, 5.4, 0.5);
  s.addNotes("0:00–0:15  Hi, we are Den and Guled. GPS is the single point of failure of today's drones. " +
    "Our idea in one sentence: when one drone gets jammed, the whole swarm learns from it and still completes the mission.");

  // 2. Problem -------------------------------------------------------------
  pres.addSection({ title: "Problem" });
  s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Problem" });
  s.addText("GPS is attacked “really often” — drones land blind", { placeholder: "title" });
  tag(s, "RELEVANCE");
  s.addText("What the Swedish Air Force (Helicopter Wing) told us", { x: 0.6, y: 1.5, w: 6.3, h: 0.4, fontSize: 15,
    bold: true, color: C.accent1, margin: 0, isTextBox: true });
  await iconRow(s, 0.6, 2.1, 6.4, fa.FaBroadcastTower, "“It happens really often”", "Jamming and spoofing — the Baltic sees it every day");
  await iconRow(s, 0.6, 3.15, 6.4, fa.FaStopwatch, "“Detect it as soon as possible”", "Both jamming and spoofing, depending on the mission");
  await iconRow(s, 0.6, 4.2, 6.4, fa.FaSnowflake, "“Snow hides the landmarks”", "Pre-made maps stop matching in winter");
  await iconRow(s, 0.6, 5.25, 6.4, fa.FaMapMarkedAlt, "“A drone once built its own map to get home”", "That real case is our starting point");
  picture(s, "log_analysis.png", 7.6, 1.5, 4.55, 1320 / 1200, "PX4 flight log during GPS jamming");
  stat(s, 7.6, 5.85, 2.2, 1.0, "5 s", "autopilot reaction time", C.accent3, 26);
  stat(s, 9.95, 5.85, 2.2, 1.0, "blind", "landing — never flies home", C.accent3, 26);
  s.addNotes("0:15–0:45  We started by interviewing the Swedish Air Force Helicopter Wing. Jamming happens really often, " +
    "it must be detected as soon as possible, and in winter snow hides the landmarks maps rely on. " +
    "We tested the real PX4 autopilot: after GPS loss it needs 5 seconds, then lands blind wherever it is. It never comes home.");

  // 3. Pivot + pipeline ----------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Problem" });
  s.addText("The military told us what is really missing", { placeholder: "title" });
  tag(s, "RELEVANCE");
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 1.5, w: 12.15, h: 1.55, rectRadius: 0.12, fill: { color: C.text2 },
    line: { color: C.accent1, width: 1.25 }, objectName: "military quote card" });
  s.addText([
    { text: "“Detect and return home — we already have that. ", options: { color: C.background2 } },
    { text: "We need the drone to tell the others, and the swarm to find its own way to the target.”",
      options: { color: C.background1, bold: true } },
  ], { x: 0.95, y: 1.6, w: 11.5, h: 1.0, fontSize: 19, italic: true, valign: "middle", margin: 0, isTextBox: true });
  s.addText("Military end-users, Friday — this changed our project", { x: 0.95, y: 2.55, w: 11.5, h: 0.35, fontSize: 12,
    color: C.accent5, margin: 0, isTextBox: true });
  const steps = [
    [fa.FaSatelliteDish, "DETECT", "jamming & spoofing", "Den"],
    [fa.FaMountain, "NAVIGATE", "without GPS, in snow", "Guled"],
    [fa.FaCrosshairs, "LOCATE", "the jammer", "Guled"],
    [fa.FaBrain, "DECIDE", "AI mission brain", "Guled"],
    [fa.FaProjectDiagram, "SHARE + REROUTE", "the whole swarm", "Den"],
    [fa.FaShieldAlt, "SECURE", "against fake warnings", "Den"],
  ];
  const bw = 1.82, gap = 0.245;
  for (let i = 0; i < steps.length; i++) {
    const [Comp, head, sub, who] = steps[i];
    const x = 0.6 + i * (bw + gap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 3.55, w: bw, h: 2.75, rectRadius: 0.12, fill: { color: C.text2 },
      line: { color: C.text2, width: 0 }, objectName: "step " + head });
    s.addShape(pres.shapes.OVAL, { x: x + bw / 2 - 0.4, y: 3.8, w: 0.8, h: 0.8, fill: { color: C.accent1 },
      line: { color: C.accent1, width: 0 }, objectName: "step icon circle " + head });
    s.addImage({ data: await icon(Comp, "FFFFFF"), x: x + bw / 2 - 0.2, y: 4.0, w: 0.4, h: 0.4, altText: head });
    s.addText(head, { x: x + 0.1, y: 4.75, w: bw - 0.2, h: 0.5, fontSize: 14, bold: true, color: C.background1,
      align: "center", valign: "middle", margin: 0, fit: "shrink", isTextBox: true });
    s.addText(sub, { x: x + 0.1, y: 5.25, w: bw - 0.2, h: 0.5, fontSize: 12, color: C.background2, align: "center",
      valign: "top", margin: 0, isTextBox: true });
    s.addText(who, { x: x + 0.1, y: 5.8, w: bw - 0.2, h: 0.35, fontSize: 12, bold: true, color: C.accent1,
      align: "center", margin: 0, isTextBox: true });
    if (i < steps.length - 1) {
      s.addShape(pres.shapes.RIGHT_ARROW, { x: x + bw + 0.03, y: 4.85, w: gap - 0.06, h: 0.3, fill: { color: C.accent5 },
        line: { color: C.accent5, width: 0 }, objectName: "arrow " + i });
    }
  }
  s.addNotes("0:45–1:10  On Friday the military told us: detect-and-return already exists. What they want is that the jammed drone " +
    "warns the others and the swarm still reaches the target. So we built this pipeline — six steps, split between the two of us.");

  // 4. DETECT --------------------------------------------------------------
  pres.addSection({ title: "Solution" });
  s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Solution" });
  s.addText("Detect: jamming in 1 s, slow spoofing in 13 s", { placeholder: "title" });
  tag(s, "INNOVATION");
  stat(s, 0.6, 1.45, 2.85, 1.15, "1 s vs 5 s", "jamming: our monitor vs PX4 (live)", C.accent2, 26);
  stat(s, 3.7, 1.45, 2.85, 1.15, "13 s", "0.5 m/s spoof caught (real flight data)", C.accent2, 26);
  stat(s, 6.8, 1.45, 2.85, 1.15, "never", "PX4-style check notices that spoof", C.accent3, 26);
  stat(s, 9.9, 1.45, 2.85, 1.15, "2 / 50", "false alarms without attack", C.accent4, 26);
  s.addText([
    { text: "GPS noise is random — a spoofer always pushes the same way. ", options: { bold: true, color: C.background1 } },
    { text: "We compare GPS with the drone's own motion sensors (IMU) over a 20 s window and catch the push.",
      options: { color: C.background2 } },
  ], { x: 0.6, y: 2.8, w: 12.15, h: 0.5, fontSize: 15, margin: 0, valign: "middle", isTextBox: true });
  picture(s, "log_spoof_result.png", 0.65, 3.5, 12.05, 2040 / 600, "Spoofing detection on real PX4 data");
  s.addNotes("1:10–1:35  Detection is the foundation. Jamming: our monitor reacts in 1 second, PX4 in 5. " +
    "Spoofing is the hard case: a slow 0.5 m/s drag keeps a perfect GPS fix. We compare GPS with the drone's own motion sensors — " +
    "noise is random, a spoofer always pushes one way. Caught in 13 seconds; a PX4-style check never notices.");

  // 5. NAVIGATE + LOCATE ---------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Solution" });
  s.addText("Navigate in snow — then find the jammer", { placeholder: "title" });
  tag(s, "INNOVATION");
  s.addText("NAVIGATE  ·  8.8 km without GPS, snowy day", { x: 0.6, y: 1.45, w: 6.0, h: 0.35, fontSize: 14, bold: true,
    color: C.accent1, margin: 0, isTextBox: true });
  let b = picture(s, "navigation/sim_long_result.png", 0.65, 1.95, 5.9, 1920 / 780, "Long-range navigation in snow");
  stat(s, 0.6, b + 0.3, 1.9, 1.15, "1 974 m", "off: IMU only", C.accent3, 22);
  stat(s, 2.6, b + 0.3, 1.9, 1.15, "1 874 m", "off: camera in snow (0/8 landmarks)", C.accent3, 22);
  stat(s, 4.6, b + 0.3, 2.0, 1.15, "14.5 m", "off: terrain matching", C.accent2, 22);
  caption(s, "Laser altimeter vs height map: the shape of the hills survives snow.", 0.6, b + 1.55, 6.0);
  s.addText("LOCATE  ·  every jammer gives itself away", { x: 6.85, y: 1.45, w: 5.9, h: 0.35, fontSize: 14, bold: true,
    color: C.accent1, margin: 0, isTextBox: true });
  b = picture(s, "navigation/jammer_hunt.png", 6.9, 1.95, 5.8, 2200 / 880, "Jammer localisation with two drones");
  stat(s, 6.85, b + 0.3, 2.85, 1.15, "~300 m", "one drone (typical)", C.accent6, 22);
  stat(s, 9.9, b + 0.3, 2.85, 1.15, "~120 m", "two drones (typical, 10 runs)", C.accent2, 22);
  caption(s, "GPS receivers measure interference — louder means closer.", 6.85, b + 1.55, 5.9);
  s.addNotes("1:35–2:05  Guled: without GPS the IMU drifts — almost 2 km after 8.8 km. A camera works on a normal day, " +
    "but in snow it recognised 0 of 8 landmarks. Terrain matching with a laser altimeter compares the shape of the hills, " +
    "which snow doesn't hide: 14.5 metres. And the jammed drones become sensors: two of them locate the jammer to about 120 metres.");

  // 6. DECIDE --------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Solution" });
  s.addText("Decide: an AI mission brain that can't break the rules", { placeholder: "title" });
  tag(s, "INNOVATION");
  b = picture(s, "navigation/ai_mission.png", 0.65, 1.55, 7.3, 2000 / 900, "AI mission brain run");
  caption(s, "Shown: offline rule-based mode. Claude mode uses the same tools and safety checks.", 0.6, b + 0.2, 7.4);
  await iconRow(s, 8.4, 1.6, 4.35, fa.FaBrain, "AI decides what", "Assess, measure, plan — explains each decision in plain language");
  await iconRow(s, 8.4, 2.75, 4.35, fa.FaTools, "Tested code decides how", "4 safe tools: measure, plan route, fly, broadcast");
  await iconRow(s, 8.4, 3.9, 4.35, fa.FaShieldAlt, "Safety check on every action", "Battery reserve and limits — the AI never flies the drone");
  stat(s, 8.4, 5.2, 2.05, 1.15, "aborted", "today: GPS lost → flies home", C.accent3, 22);
  stat(s, 10.6, 5.2, 2.15, 1.15, "8 m", "from target: mission completed", C.accent2, 22);
  s.addNotes("2:05–2:30  Guled: the military asked for a system that finds a solution on its own. Our AI mission brain assesses the situation, " +
    "measures, plans and reports — but it can only act through four safe tools, and every action passes a safety check. " +
    "The AI decides what, tested code decides how. Today's system aborts; ours completes the mission 8 metres from the target.");

  // 7. SHARE + REROUTE -----------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Solution" });
  s.addText("One scout gets jammed — the swarm gets through", { placeholder: "title" });
  tag(s, "INNOVATION");
  b = picture(s, "radar/radar_swarm_end.png", 0.65, 1.5, 8.0, 1440 / 880, "Jamming radar: swarm reroute replay");
  caption(s, "Flight-radar replay of our swarm simulation — drone expert Isabella's idea, built by Guled", 0.6, b + 0.15, 8.1);
  stat(s, 9.2, 1.5, 3.55, 1.05, "0 / 3", "reach the target today", C.accent3, 24);
  stat(s, 9.2, 2.7, 3.55, 1.05, "24 / 24", "with our swarm (8 random runs)", C.accent2, 24);
  stat(s, 9.2, 3.9, 3.55, 1.05, "16 s vs 68 s", "without GPS: swarm vs each alone", C.accent2, 24);
  stat(s, 9.2, 5.1, 3.55, 1.05, "−16 %", "mission time", C.accent4, 24);
  s.addNotes("2:30–3:00  Den: this is the core. Today all three drones fly into the jammer and are lost. Alone, each has to get jammed to learn. " +
    "In our swarm the first drone is a scout: it detects the jamming, backs out, and shares where GPS died. The others plan around it. " +
    "24 out of 24 drones reach the target over 8 random setups, and only the scout ever loses GPS.");

  // 7b. INSIDE THE ZONE + MAGNAV (Guled) ----------------------------------------
  s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Solution" });
  s.addText("Target inside the zone? The swarm is its own GPS", { placeholder: "title" });
  tag(s, "INNOVATION");
  s.addText("SWARM GPS  ·  edge drones keep GPS and range the drone inside", { x: 0.6, y: 1.45, w: 6.0, h: 0.35, fontSize: 14,
    bold: true, color: C.accent1, margin: 0, isTextBox: true });
  b = picture(s, "navigation/swarm_gps_result.png", 0.65, 1.95, 5.9, 1995 / 840, "Swarm GPS inside the jammed zone");
  stat(s, 0.6, b + 0.3, 2.9, 1.15, "59 m → 1 m", "error while observing the target (20 runs)", C.accent2, 24);
  stat(s, 3.65, b + 0.3, 2.95, 1.15, "2 m", "still, if one edge drone is lost", C.accent2, 24);
  caption(s, "Radio ranging on the drones' own link — not the band a GPS jammer hits.", 0.6, b + 1.55, 6.0);
  s.addText("MAGNAV  ·  the Earth's magnetic map can't be jammed", { x: 6.85, y: 1.45, w: 5.9, h: 0.35, fontSize: 14, bold: true,
    color: C.accent1, margin: 0, isTextBox: true });
  b = picture(s, "navigation/magnav_result.png", 6.9, 1.95, 5.8, 1995 / 787, "MagNav over land and sea");
  stat(s, 6.85, b + 0.3, 2.85, 1.15, "202 m", "terrain matching — blind over the sea", C.accent6, 24);
  stat(s, 9.9, b + 0.3, 2.85, 1.15, "38 m", "terrain + MagNav (typical, 20 km)", C.accent2, 24);
  caption(s, "It only listens — nothing to jam or spoof. Works over the Baltic, at night, in snow.", 6.85, b + 1.55, 5.9);
  s.addNotes("Guled: the enemy puts the jammer where it protects something — so the target is often inside. Drones waiting at the edge " +
    "still have GPS and measure their radio distance to the drone inside: the swarm becomes its own GPS, 1 metre instead of 59. " +
    "And over the sea, where hills disappear, the Earth's magnetic map still works and can't be jammed. " +
    "(Limits: assumes the drones' own radio link survives; the magnetic map in the demo is fairly strong.)");

  // 8. LIVE PX4 -------------------------------------------------------------
  pres.addSection({ title: "Proof" });
  s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Proof" });
  s.addText("Live: 3 real PX4 autopilots fly the mission in Gazebo", { placeholder: "title" });
  tag(s, "PROGRESS");
  b = picture(s, "gazebo_base.png", 0.65, 1.55, 7.35, 1289 / 609, "Gazebo: base, battlefield, jammer and target");
  caption(s, "Forward base with operators · battlefield · enemy jammer (red dome) · target facility", 0.6, b + 0.15, 7.4);
  picture(s, "mission_screenshot.png", 8.45, 1.55, 4.25, 1085 / 658, "Mission app after a live run");
  stat(s, 0.6, 5.55, 2.35, 1.25, "1 / 3", "drones ever jammed (the scout)", C.accent6, 24);
  stat(s, 3.1, 5.55, 2.35, 1.25, "3 / 3", "on station at the target", C.accent2, 24);
  stat(s, 5.6, 5.55, 2.4, 1.25, "33–38 m", "stand-off, never inside the building", C.accent4, 24);
  s.addText([
    { text: "Scout flies into the jammer → alarm → backs out blind on its own breadcrumbs → warns the swarm → others fly around.",
      options: { color: C.background2 } },
  ], { x: 8.4, y: 4.35, w: 4.35, h: 1.1, fontSize: 13, margin: 0, valign: "top", isTextBox: true });
  caption(s, "7 live test runs to get here — every failure is in our process log.", 8.4, 5.65, 4.35, 0.6);
  s.addNotes("3:00–3:30  Not just a Python model: three real PX4 autopilots in Gazebo, at a military base with a jammer on the battlefield. " +
    "The scout gets jammed, backs out blind on its own breadcrumbs and warns the others; all three end on station next to the target. " +
    "(Replace the left picture with the screen recording of the mission before uploading.)");

  // 9. ATTACK ---------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Proof" });
  s.addText("We attacked our own system: fake warnings", { placeholder: "title" });
  tag(s, "INNOVATION");
  b = picture(s, "swarm_attack.png", 0.65, 1.55, 8.75, 2310 / 814, "Fake-report attack and defence");
  s.addText("“A warning is cheap to believe.\nAn all-clear must be proven.”", { x: 0.6, y: b + 0.35, w: 8.8, h: 1.0,
    fontSize: 22, bold: true, italic: true, color: C.accent1, margin: 0, valign: "top", isTextBox: true });
  s.addText("Share measurements, never commands · check every report against physics and real GPS-loss evidence",
    { x: 0.6, y: b + 1.4, w: 8.8, h: 0.45, fontSize: 13, color: C.background2, margin: 0, isTextBox: true });
  stat(s, 9.85, 1.55, 2.9, 1.25, "9 → 1", "drones lured into the jammer: no defence vs ours (6 runs)", C.accent2, 28);
  stat(s, 9.85, 3.0, 2.9, 1.25, "6 / 6", "times the liar was caught", C.accent2, 28);
  stat(s, 9.85, 4.45, 2.9, 1.25, "0", "honest drones wrongly rejected", C.accent2, 28);
  s.addNotes("3:30–4:00  Den, cyber security: Guled asked — what if the enemy fakes the warnings? A captured drone with a valid key " +
    "reports 'all quiet' over the jammer. Undefended, it lured 9 drones into the trap. Our rule: a warning is cheap to believe, " +
    "an all-clear must be proven against places where a drone really lost GPS. Liar caught 6 out of 6, no honest drone rejected.");

  // 10. PROGRESS + PLAN -------------------------------------------------------
  pres.addSection({ title: "Progress and team" });
  s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Progress and team" });
  s.addText("48 hours of progress — and what's next", { placeholder: "title" });
  tag(s, "PROGRESS");
  stat(s, 0.6, 1.5, 1.9, 1.05, "4", "expert inputs", C.accent1, 26);
  stat(s, 2.65, 1.5, 1.9, 1.05, "15", "logged iterations", C.accent1, 26);
  stat(s, 4.7, 1.5, 1.9, 1.05, "24", "commits on GitHub", C.accent1, 26);
  const done = [
    "Thu: Air Force interview → tested real PX4 → spoof detector on real flight data",
    "Fri: live demo, navigation in snow, jammer hunter",
    "Fri: military feedback → swarm sharing, AI brain, attack defence",
    "Fri night: 3 PX4 drones live at a military base",
  ];
  s.addText(done.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < done.length - 1 } })),
    { x: 0.6, y: 2.8, w: 6.0, h: 2.2, fontSize: 14, color: C.background2, paraSpaceAfter: 6, margin: 0, valign: "top",
      isTextBox: true });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 5.45, w: 6.0, h: 1.15, rectRadius: 0.1, fill: { color: C.text2 },
    line: { color: C.accent5, width: 0.75 }, objectName: "honest limits card" });
  s.addText([
    { text: "Honest limits", options: { bold: true, color: C.accent6, breakLine: true } },
    { text: "Simulation only so far · jammer model is free-space · the swarm assumes its radio link survives · " +
      "very slow spoofs (< 0.1 m/s) are not caught", options: { color: C.background2 } },
  ], { x: 0.8, y: 5.55, w: 5.6, h: 0.95, fontSize: 13, margin: 0, valign: "top", isTextBox: true });
  s.addText("NEXT", { x: 7.0, y: 1.5, w: 5.7, h: 0.4, fontSize: 14, bold: true, color: C.accent1, charSpacing: 2, margin: 0,
    isTextBox: true });
  await iconRow(s, 7.0, 2.05, 5.75, fa.FaHelicopter, "Real drones in Terra lab", "Holybro PX4 drones + Vicon ground truth at LiU");
  await iconRow(s, 7.0, 3.1, 5.75, fa.FaSignal, "Real jamming indicators", "u-blox receivers already report interference to PX4");
  await iconRow(s, 7.0, 4.15, 5.75, fa.FaGlobeEurope, "AquaGuard Technologies", "Satellite/SAR imagery as backup map; our jammer reports as their data feed");
  await iconRow(s, 7.0, 5.2, 5.75, fa.FaUserCheck, "Operator in the loop", "Secure drone-to-drone link, human approval for reroutes");
  s.addNotes("4:00–4:30  In 48 hours: four expert inputs, fifteen logged iterations, twenty-four commits — every failure is documented. " +
    "Honest limits: it's simulation, the jammer model is simple, and the swarm needs its radio link. Next: real drones in Terra lab, " +
    "real interference readings from u-blox receivers, and — on drone expert Isabella's advice — AquaGuard's satellite imagery as a backup map.");

  // 11. TEAM + CLOSE ----------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Progress and team" });
  s.addText("Team", { placeholder: "title" });
  tag(s, "TEAM");
  const people = [
    [fa.FaUserShield, "Den", "Cyber security student", "Detection · swarm sharing · attack defence · live PX4 mission"],
    [fa.FaUserCog, "Guled", "Computer engineering student", "GPS-free navigation · jammer hunter · AI mission brain · slides"],
  ];
  for (let i = 0; i < 2; i++) {
    const [Comp, name, role, did] = people[i];
    const x = 0.6 + i * 6.15;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.5, w: 6.0, h: 1.9, rectRadius: 0.12, fill: { color: C.text2 },
      line: { color: C.text2, width: 0 }, objectName: "person card " + name });
    s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: 1.85, w: 1.1, h: 1.1, fill: { color: C.accent1 }, line: { color: C.accent1, width: 0 },
      objectName: "person icon circle " + name });
    s.addImage({ data: await icon(Comp, "FFFFFF"), x: x + 0.6, y: 2.15, w: 0.5, h: 0.5, altText: name });
    s.addText([
      { text: name, options: { bold: true, fontSize: 22, color: C.background1, breakLine: true } },
      { text: role, options: { fontSize: 14, color: C.accent1, breakLine: true } },
      { text: did, options: { fontSize: 13, color: C.background2 } },
    ], { x: x + 1.65, y: 1.65, w: 4.15, h: 1.6, margin: 0, valign: "middle", isTextBox: true });
  }
  s.addText([
    { text: "Shaped by: ", options: { bold: true, color: C.background1 } },
    { text: "Swedish Air Force Helicopter Wing · military end-users · drone expert Isabella · a satellite company · fellow participants",
      options: { color: C.background2 } },
  ], { x: 0.6, y: 3.7, w: 12.15, h: 0.5, fontSize: 14, margin: 0, isTextBox: true });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 4.6, w: 12.15, h: 2.0, rectRadius: 0.14, fill: { color: C.accent1 },
    line: { color: C.accent1, width: 0 }, objectName: "closing card" });
  s.addText([
    { text: "One drone gets jammed — the whole swarm learns.", options: { breakLine: true } },
    { text: "If the enemy fakes the warnings, physics exposes the liar.", options: { bold: false } },
  ], { x: 0.95, y: 4.7, w: 11.5, h: 1.8, fontSize: 26, bold: true, color: C.background1, valign: "middle", margin: 0,
    isTextBox: true });
  s.addNotes("4:30–5:00  We are a cyber-security and a computer-engineering student, and every step was shaped by the people who'd use it. " +
    "One drone gets jammed — the whole swarm learns. And if the enemy fakes the warnings, physics exposes the liar. Thank you.");

  await pres.writeFile({ fileName: OUT });
  if (APPLY_THEME) {
    const { applyTheme } = require(APPLY_THEME);
    await applyTheme(OUT, THEME);
  }
  console.log("Saved " + OUT);
}

build().catch((e) => { console.error(e); process.exit(1); });
