/* Rookie 2.0 — "LESS DATA. MORE DECISIONS."
   Science runs in the Python engine (lunarmatch). This file collects inputs, drives the
   journey and presents conclusions the engine produced. It computes no scores, ranks or
   winners, and never invents place names or measurements. */
(function () {
"use strict";
var CFG = JSON.parse(document.getElementById("rookie-config").textContent);
var R_MOON_KM = CFG.moon_radius_km;                         /* IAU 2015 Moon sphere */
var reduceMotion = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
var engineOnline = false;

/* ------------------------------------------------------------------ state */
var S = {
  screen: 1,
  target: {preset_id: "shackleton_de_gerlache_ridge", lat: null, lon: null, radius_km: 7, label: ""},
  search_mode: "extraordinary",
  moon_dataset: firstDataset("Moon"),
  earth_dataset: firstDataset("Earth", true),
  earth: {scope_bbox: null, start_location: null, budget: null, currency: "USD", max_travel_km: null, equipment: []},
  scale: {lunar_footprint_m: 14000, terrestrial_footprint_m: 10000, characteristic_lengths_m: {leg_spacing: 4}},
  environment: {vacuum: "required", gravity: "numerical_correction", dust: "preferred",
                thermal_vacuum: "not_required", illumination: "preferred"},
  experiments: [], constraints: [],
  job: null, result: null, activeExp: null
};
applyPreset(S.target.preset_id);
S.earth.scope_bbox = defaultScope();

function firstDataset(body, preferReal) {
  var ds = CFG.datasets.filter(function (d) { return d.body === body; });
  if (preferReal) { var real = ds.filter(function (d) { return !d.is_mock; }); if (real.length) return real[0].id; }
  return ds.length ? ds[0].id : null;
}
function dsInfo(id) { return CFG.datasets.filter(function (d) { return d.id === id; })[0] || {}; }
function defaultScope() { var e = dsInfo(S.earth_dataset).coverage_extent; return e ? e.slice() : [-71, -25, -68, -22]; }
function preset(id) { return CFG.presets.filter(function (p) { return p.id === id; })[0]; }
function applyPreset(id) {
  var p = preset(id); S.target.preset_id = id; S.target.label = p.name;
  if (p.point) { S.target.lat = p.point.lat; S.target.lon = p.point.lon; if (p.suggested_radius_km) S.target.radius_km = p.suggested_radius_km; }
  else if (p.status === "coordinates_pending_validation") { S.target.lat = null; S.target.lon = null; }
  S.scale.lunar_footprint_m = Math.round(2 * S.target.radius_km * 1000);
}
function exp(id) { return CFG.experiments.filter(function (e) { return e.experiment_id === id; })[0]; }

/* ------------------------------------------------------------------ helpers */
function h(tag, attrs, kids) {
  var el = document.createElement(tag);
  if (attrs) for (var k in attrs) {
    var v = attrs[k];
    if (v === null || v === undefined || v === false) continue;
    if (k === "text") el.textContent = v;
    else if (k === "on") for (var ev in v) el.addEventListener(ev, v[ev]);
    else el.setAttribute(k, v === true ? "" : v);
  }
  (function add(list) { (list || []).forEach(function (c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) return add(c);
    el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
  }); })(kids);
  return el;
}
function badge(cls, text) { return h("span", {"class": "badge " + cls, text: text}); }
function fmt(v, d) { return (v === null || v === undefined || isNaN(v)) ? "–" : Number(v).toFixed(d === undefined ? 1 : d); }
function num(v) { var x = parseFloat(v); return isFinite(x) ? x : null; }
function latStr(v) { return fmt(Math.abs(v), 4) + "°" + (v < 0 ? "S" : "N"); }
function lonStr(v) { return fmt(Math.abs(v), 4) + "°" + (v < 0 ? "W" : "E"); }
function coordStr(lat, lon) { return latStr(lat) + ", " + lonStr(lon); }

/* ------------------------------------------------------------------ lunar geodesy (sphere) */
var D2R = Math.PI / 180;
function xyz(lat, lon, r) { r = r || 1; var p = lat * D2R, l = lon * D2R; return [r * Math.cos(p) * Math.cos(l), r * Math.cos(p) * Math.sin(l), r * Math.sin(p)]; }
function latlon(x, y, z) { var r = Math.sqrt(x * x + y * y + z * z); return [Math.asin(z / r) / D2R, Math.atan2(y, x) / D2R]; }
function destination(lat, lon, brg, dKm) {
  var d = dKm / R_MOON_KM, p1 = lat * D2R, l1 = lon * D2R, b = brg * D2R;
  var p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  var l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [p2 / D2R, ((l2 / D2R + 540) % 360) - 180];
}
function capAreaKm2(rKm) { return 2 * Math.PI * R_MOON_KM * R_MOON_KM * (1 - Math.cos(rKm / R_MOON_KM)); }
window.RookieGeo = {destination: destination, capAreaKm2: capAreaKm2, latlon: latlon, xyz: xyz};

/* ------------------------------------------------------------------ stepper */
var STEPS = [["Where on the Moon?", 1], ["Your constraints", 2], ["Where to test", 3]];
function canGo(n) { return n === 1 || (n === 2 && moonErrors().length === 0) || (n === 3 && !!S.result); }
function renderStepper() {
  var ol = document.getElementById("stepper"); ol.textContent = "";
  STEPS.forEach(function (s) {
    ol.appendChild(h("li", null, [h("button", {type: "button", "aria-current": S.screen === s[1] ? "step" : null,
      disabled: !canGo(s[1]), on: {click: function () { go(s[1]); }}},
      [h("span", {"class": "n", text: s[1]}), h("span", {"class": "l", text: s[0]})])]));
  });
}
function go(n) {
  if (!canGo(n)) return;
  S.screen = n;
  [1, 2, 3].forEach(function (i) { document.getElementById("screen" + i).hidden = i !== n; });
  ({1: renderScreen1, 2: renderScreen2, 3: renderScreen3})[n]();
  renderStepper();
  document.getElementById("main").focus({preventScroll: true});
  window.scrollTo(0, 0);
}

/* ================================================================== SCREEN 1 — WHERE ON THE MOON? */
function moonErrors() {
  var e = [], t = S.target, p = preset(t.preset_id);
  if (t.lat === null || t.lon === null) e.push(p.status === "coordinates_pending_validation"
    ? p.name + " has no published coordinates yet — click the Moon or type coordinates."
    : "Pick a spot: click the Moon or type coordinates.");
  else if (t.lat < -90 || t.lat > 90 || t.lon < -180 || t.lon > 180) e.push("Coordinates are out of range.");
  if (!(t.radius_km > 0) || t.radius_km > 500) e.push("Radius must be between 0 and 500 km.");
  if (!S.experiments.length) e.push("Choose at least one experiment.");
  return e;
}
function renderScreen1() {
  var sc = document.getElementById("screen1"); sc.textContent = "";
  var t = S.target, p = preset(t.preset_id), errs = moonErrors();
  var lat = h("input", {type: "number", step: "0.001", value: t.lat === null ? "" : t.lat, id: "latIn", "aria-label": "Latitude"});
  var lon = h("input", {type: "number", step: "0.001", value: t.lon === null ? "" : t.lon, id: "lonIn", "aria-label": "Longitude"});
  var rad = h("input", {type: "number", step: "0.5", min: 0.1, value: t.radius_km, id: "radIn", "aria-label": "Radius in km"});
  function onCoord() {
    S.target.lat = num(lat.value); S.target.lon = num(lon.value); S.target.radius_km = num(rad.value) || 0;
    var pp = preset(S.target.preset_id).point;
    if (!pp || S.target.lat !== pp.lat || S.target.lon !== pp.lon) { S.target.preset_id = "custom"; S.target.label = "Custom location"; }
    S.scale.lunar_footprint_m = Math.round(2 * S.target.radius_km * 1000);
    renderScreen1(); renderStepper();
  }
  [lat, lon, rad].forEach(function (i) { i.addEventListener("change", onCoord); });
  var chips = h("div", {"class": "chips", role: "radiogroup", "aria-label": "Lunar target"}, CFG.presets.map(function (q) {
    var dot = q.status === "verified_point" ? "ok" : q.status === "coordinates_pending_validation" ? "warn" : "user";
    return h("button", {"class": "chip", type: "button", role: "radio", "aria-checked": String(q.id === t.preset_id),
      title: q.note || "", on: {click: function () { applyPreset(q.id); renderScreen1(); renderStepper(); }}},
      [h("span", {"class": "dot " + dot, "aria-hidden": "true"}), q.name.split(" (")[0]]);
  }));
  var expChips = h("div", {"class": "chips"}, CFG.experiments.map(function (e) {
    var on = S.experiments.indexOf(e.experiment_id) >= 0;
    return h("button", {"class": "chip exp", type: "button", "aria-pressed": String(on), title: e.objective + " · " + e.notes,
      on: {click: function () {
        if (on) S.experiments = S.experiments.filter(function (x) { return x !== e.experiment_id; }); else S.experiments.push(e.experiment_id);
        renderScreen1(); renderStepper(); }}}, [on ? "✓ " : "", e.name_en]);
  }));
  var summary = t.lat !== null && t.lon !== null && t.radius_km > 0
    ? fmt(t.radius_km, 1) + " km around " + coordStr(t.lat, t.lon) + " · " + fmt(capAreaKm2(t.radius_km), 0) + " km² on the Moon" : "No spot chosen yet";
  sc.appendChild(h("div", {"class": "hero"}, [h("h1", {id: "s1title", text: "Where on the Moon?"}),
    h("p", {"class": "lead", text: "Pick the lunar terrain your test should represent and what you want to test. Rookie will look for matching places on Earth."})]));
  sc.appendChild(h("div", {"class": "split"}, [
    h("div", {"class": "globe-wrap"}, [h("div", {id: "moonGlobe", role: "img", "aria-label": "Interactive Moon globe. Drag to rotate, scroll to zoom, click to choose a spot."}),
      h("div", {"class": "globe-tools"}, [h("button", {type: "button", on: {click: function () { zoomGlobe(true); }}, text: "Zoom to spot"}),
        h("button", {type: "button", on: {click: function () { zoomGlobe(false); }}, text: "Whole Moon"})]),
      h("div", {"class": "globe-note", text: "Plain sphere with grid lines — no lunar imagery is drawn."})]),
    h("div", {"class": "panel"}, [
      h("div", {"class": "q"}, [h("h2", {text: "1 · Lunar spot"}), chips,
        p.status === "coordinates_pending_validation" ? h("p", {"class": "hint warn", text: "No published coordinates for this region yet."}) : null,
        p.status === "verified_point" ? h("p", {"class": "hint"}, ["Verified point · ", h("a", {href: p.source, target: "_blank", rel: "noopener", text: "source"})]) : null,
        h("div", {"class": "coords"}, [h("label", null, ["Lat ", lat]), h("label", null, ["Lon ", lon]), h("label", null, ["Radius km ", rad])]),
        h("p", {"class": "summary", text: summary})]),
      h("div", {"class": "q"}, [h("h2", {text: "2 · What do you want to test?"}), expChips,
        h("p", {"class": "hint", text: "All experiments are planning-only; none is approved for scoring yet."})]),
      h("div", {"class": "q"}, [h("h2", {text: "3 · How should Rookie search?"}),
        h("div", {"class": "seg", role: "radiogroup"}, [
          segBtn("extraordinary", "Discover new places", "Searches real Earth terrain — no predefined site list."),
          segBtn("ordinary", "Known analog sites", "Searches the verified catalogue (" + (CFG.catalog.sites ? CFG.catalog.sites + " sites" : "currently empty") + ").")])]),
      dsInfo(S.moon_dataset).is_mock ? h("p", {"class": "hint"}, [badge("b-mock", "DEMO"), " Lunar terrain is demo (MOCK) data until real LOLA/LROC data are connected."]) : null,
      errs.length ? h("ul", {"class": "errs"}, errs.map(function (e) { return h("li", {text: e}); })) : null,
      h("button", {"class": "btn big", type: "button", disabled: errs.length > 0, on: {click: function () { go(2); }}, text: "Next: your constraints →"})])]));
  drawGlobe();
}
function segBtn(id, title, sub) {
  return h("button", {"class": "segbtn", type: "button", role: "radio", "aria-checked": String(S.search_mode === id),
    on: {click: function () { S.search_mode = id; renderScreen1(); }}}, [h("strong", {text: title}), h("span", {text: sub})]);
}

/* ------------------------------------------------------------------ Moon globe */
var globeReady = false;
function sphereTrace() {
  var xs = [], ys = [], zs = [], tx = [];
  for (var la = -90; la <= 90; la += 3) { var rx = [], ry = [], rz = [], rt = [];
    for (var lo = -180; lo <= 180; lo += 3) { var p = xyz(la, lo); rx.push(p[0]); ry.push(p[1]); rz.push(p[2]); rt.push(coordStr(la, lo)); }
    xs.push(rx); ys.push(ry); zs.push(rz); tx.push(rt); }
  return {type: "surface", x: xs, y: ys, z: zs, text: tx, hovertemplate: "%{text}<extra>click to choose</extra>",
    surfacecolor: zs, colorscale: [[0, "#8a8f99"], [0.5, "#a7acb5"], [1, "#c3c7ce"]], showscale: false,
    lighting: {ambient: 0.55, diffuse: 0.75, specular: 0.05, roughness: 0.9}, lightposition: {x: 1e5, y: 5e4, z: 2e4},
    contours: {x: {highlight: false}, y: {highlight: false}, z: {highlight: false}}};
}
function graticule() {
  var tr = [];
  function line(pts, w) { tr.push({type: "scatter3d", mode: "lines", x: pts.map(function (p) { return p[0]; }), y: pts.map(function (p) { return p[1]; }),
    z: pts.map(function (p) { return p[2]; }), line: {color: "rgba(30,40,70,0.45)", width: w || 1}, hoverinfo: "skip", showlegend: false}); }
  for (var lo = -180; lo < 180; lo += 30) { var m = []; for (var la = -90; la <= 90; la += 3) m.push(xyz(la, lo, 1.003)); line(m); }
  for (var la2 = -75; la2 <= 75; la2 += 15) { var pl = []; for (var l2 = -180; l2 <= 180; l2 += 3) pl.push(xyz(la2, l2, 1.003)); line(pl, la2 === 0 ? 2 : 1); }
  return tr;
}
function presetMarkers() {
  var v = CFG.presets.filter(function (p) { return p.point; }), pts = v.map(function (p) { return xyz(p.point.lat, p.point.lon, 1.012); });
  return {type: "scatter3d", mode: "markers+text", x: pts.map(function (p) { return p[0]; }), y: pts.map(function (p) { return p[1]; }),
    z: pts.map(function (p) { return p[2]; }), text: v.map(function (p) { return "  " + p.name.split(" (")[0]; }),
    textfont: {color: "#7fe0b4", size: 11}, marker: {size: 5, color: "#5fd0a0", symbol: "diamond"},
    hovertemplate: v.map(function (p) { return p.name + "<br>" + coordStr(p.point.lat, p.point.lon) + "<br>verified point<extra></extra>"; }), showlegend: false};
}
function selectionTraces() {
  var t = S.target;
  if (t.lat === null || t.lon === null || !(t.radius_km > 0)) return [{type: "scatter3d", x: [], y: [], z: []}, {type: "scatter3d", x: [], y: [], z: []}];
  var ring = []; for (var b = 0; b <= 360; b += 4) { var d = destination(t.lat, t.lon, b, t.radius_km); ring.push(xyz(d[0], d[1], 1.015)); }
  var c = xyz(t.lat, t.lon, 1.02);
  return [{type: "scatter3d", mode: "lines", x: ring.map(function (p) { return p[0]; }), y: ring.map(function (p) { return p[1]; }),
      z: ring.map(function (p) { return p[2]; }), line: {color: "#eb6834", width: 6}, hoverinfo: "skip", showlegend: false},
    {type: "scatter3d", mode: "markers", x: [c[0]], y: [c[1]], z: [c[2]], marker: {size: 6, color: "#eb6834"},
      hovertemplate: "Your spot: " + coordStr(t.lat, t.lon) + "<extra></extra>", showlegend: false}];
}
function drawGlobe() {
  var el = document.getElementById("moonGlobe"); if (!el || !window.Plotly) return;
  var t = S.target, eye = t.lat !== null ? xyz(t.lat, t.lon, 1.7) : [0.4, -0.6, -1.6];
  Plotly.newPlot(el, [sphereTrace()].concat(graticule(), [presetMarkers()], selectionTraces()),
    {margin: {l: 0, r: 0, t: 0, b: 0}, paper_bgcolor: "rgba(0,0,0,0)", showlegend: false,
     scene: {xaxis: {visible: false}, yaxis: {visible: false}, zaxis: {visible: false}, aspectmode: "data", bgcolor: "rgba(0,0,0,0)",
       camera: {eye: {x: eye[0], y: eye[1], z: eye[2]}, up: {x: 0, y: 0, z: 1}}}},
    {displaylogo: false, responsive: true, modeBarButtonsToRemove: ["toImage"]});
  globeReady = true;
  el.on("plotly_click", function (ev) {
    var p = ev.points && ev.points[0]; if (!p || p.data.type !== "surface") return;
    var ll = latlon(p.x, p.y, p.z);
    S.target.preset_id = "custom"; S.target.label = "Custom location";
    S.target.lat = Math.round(ll[0] * 1e3) / 1e3; S.target.lon = Math.round(ll[1] * 1e3) / 1e3;
    renderScreen1(); renderStepper();
  });
}
function zoomGlobe(toSpot) {
  var el = document.getElementById("moonGlobe"), t = S.target; if (!el || !globeReady) return;
  var r = toSpot && t.lat !== null ? 1 + Math.max(0.012, 5 * t.radius_km / R_MOON_KM) : 1.7;
  var e = t.lat !== null ? xyz(t.lat, t.lon, r) : [0.4, -0.6, -1.6];
  var c = toSpot && t.lat !== null ? xyz(t.lat, t.lon, 0.98) : [0, 0, 0];
  Plotly.relayout(el, {"scene.camera.eye": {x: e[0], y: e[1], z: e[2]}, "scene.camera.center": {x: c[0], y: c[1], z: c[2]}});
}

/* ================================================================== SCREEN 2 — YOUR CONSTRAINTS */
function earthErrors() {
  var e = [], b = S.earth.scope_bbox;
  if (!b || b.some(function (v) { return v === null; })) e.push("Search area is incomplete.");
  else if (!(b[1] < b[3]) || b[0] === b[2]) e.push("Search area bounds are invalid.");
  if (S.earth.budget !== null && S.earth.budget < 0) e.push("Budget can't be negative.");
  if (!(S.scale.terrestrial_footprint_m > 0)) e.push("Test-area size must be positive.");
  return e;
}
function fieldL(label, input, hint) { return h("label", {"class": "f"}, [h("span", {text: label}), input, hint ? h("small", {text: hint}) : null]); }
function numIn(val, set, attrs) { var i = h("input", Object.assign({type: "number", value: val === null || val === undefined ? "" : val}, attrs || {}));
  i.addEventListener("change", function () { set(num(i.value)); renderScreen2(); }); return i; }
function txtIn(val, set) { var i = h("input", {type: "text", value: val || ""}); i.addEventListener("change", function () { set(i.value); renderScreen2(); }); return i; }
function setStart(k, v) { var s = Object.assign({}, S.earth.start_location || {}); s[k] = v;
  S.earth.start_location = (s.lat === null || s.lat === undefined) && (s.lon === null || s.lon === undefined) && !s.label ? null : s; }
function renderScreen2() {
  var sc = document.getElementById("screen2"); sc.textContent = "";
  var errs = earthErrors(), st = S.earth.start_location || {}, earthDs = dsInfo(S.earth_dataset);
  var cov = earthDs.coverage_extent, b = S.earth.scope_bbox;
  var spacing = earthDs.spacing_m || 30, minFoot = spacing * 10;
  var cur = h("select", {"aria-label": "Currency", on: {change: function () { S.earth.currency = cur.value; }}},
    ["USD", "EUR", "ILS", "GBP"].map(function (c) { return h("option", {value: c, selected: S.earth.currency === c ? true : null, text: c}); }));
  sc.appendChild(h("div", {"class": "hero"}, [h("h1", {id: "s2title", text: "Your constraints"}),
    h("p", {"class": "lead", text: "Three things are enough to start. Everything else has sensible defaults under Advanced."})]));
  sc.appendChild(h("div", {"class": "essentials"}, [
    h("div", {"class": "q"}, [h("h2", {text: "Where will your team start?"}),
      h("div", {"class": "row3"}, [fieldL("Latitude", numIn(st.lat, function (v) { setStart("lat", v); }, {step: "0.01"})),
        fieldL("Longitude", numIn(st.lon, function (v) { setStart("lon", v); }, {step: "0.01"})),
        fieldL("Name (optional)", txtIn(st.label, function (v) { setStart("label", v); }))]),
      h("small", {"class": "hint", text: "Used to show straight-line distance to each candidate. Travel cost is not estimated."})]),
    h("div", {"class": "q"}, [h("h2", {text: "Budget"}), h("div", {"class": "row2"}, [
      fieldL("Amount", numIn(S.earth.budget, function (v) { S.earth.budget = v; }, {min: 0})), fieldL("Currency", cur)]),
      h("small", {"class": "hint", text: "Recorded for planning. Rookie does not estimate costs yet, and budget never changes scientific results."})]),
    h("div", {"class": "q"}, [h("h2", {text: "Test-area size on Earth"}),
      fieldL("Side length (km)", numIn(S.scale.terrestrial_footprint_m / 1000, function (v) { S.scale.terrestrial_footprint_m = (v || 0) * 1000; }, {min: 0.1, step: "0.5"})),
      S.scale.terrestrial_footprint_m < minFoot ? h("p", {"class": "hint warn", text: "Too small for the available terrain data (~" + spacing + " m). Use at least " + fmt(minFoot / 1000, 1) + " km."})
        : h("small", {"class": "hint", text: "Your lunar area is " + fmt(S.scale.lunar_footprint_m / 1000, 1) + " km across. A smaller Earth area is fine, but it is not automatically physically equivalent."})])]));
  /* critical environmental limitations — always visible */
  sc.appendChild(h("div", {"class": "envstrip"}, [h("h2", {text: "What the Earth site cannot reproduce"})].concat(S.experiments.map(function (id) {
    var e = exp(id); return h("p", null, [h("strong", {text: e.name_en + ": "}), e.vacuum_sentence]); }))));
  sc.appendChild(h("p", {"class": "scopeline", text: "Search area: " + (cov && b && b.join() === cov.join()
    ? "everywhere Rookie currently has Earth terrain (" + coordStr(cov[1], cov[0]) + " to " + coordStr(cov[3], cov[2]) + ")."
    : "custom box " + b.map(function (v) { return fmt(v, 2); }).join(", ") + " (W, S, E, N).") + " Global search needs more terrain coverage."}));
  sc.appendChild(advanced());
  if (errs.length) sc.appendChild(h("ul", {"class": "errs"}, errs.map(function (e) { return h("li", {text: e}); })));
  sc.appendChild(h("div", {"class": "btnrow"}, [h("button", {"class": "btn sec", type: "button", on: {click: function () { go(1); }}, text: "← Back"}),
    h("button", {"class": "btn big go", type: "button", disabled: errs.length > 0, on: {click: startSearch}, text: "Send Rookie to search →"})]));
}
function advanced() {
  var env = S.environment, lvl = [["required", "Required"], ["preferred", "Preferred"], ["not_required", "Not required"]];
  function sel(key, label, opts) { var s = h("select", {on: {change: function () { S.environment[key] = s.value; }}},
    opts.map(function (o) { return h("option", {value: o[0], selected: env[key] === o[0] ? true : null, text: o[1]}); })); return fieldL(label, s); }
  var b = S.earth.scope_bbox || [null, null, null, null];
  var d = h("details", {"class": "advanced", open: S.advOpen ? true : null}, [h("summary", {text: "ADVANCED EXPERIMENT SETTINGS"}),
    h("h3", {text: "Lunar environment"}),
    h("div", {"class": "row3"}, [sel("vacuum", "Vacuum", lvl),
      sel("gravity", "Lunar gravity", [["physical_simulation", "Physical simulation"], ["numerical_correction", "Numerical correction"], ["not_required", "Not required"]]),
      sel("dust", "Dust behaviour", lvl), sel("thermal_vacuum", "Thermal-vacuum", lvl), sel("illumination", "Sun & shadows", lvl)]),
    h("h3", {text: "Scale"}),
    h("div", {"class": "row3"}, [fieldL("Lunar reference size (m)", numIn(S.scale.lunar_footprint_m, function (v) { S.scale.lunar_footprint_m = v; }, {min: 1})),
      fieldL("Lander leg spacing (m)", numIn(S.scale.characteristic_lengths_m.leg_spacing, function (v) {
        if (v) S.scale.characteristic_lengths_m.leg_spacing = v; else delete S.scale.characteristic_lengths_m.leg_spacing; }, {min: 0.1, step: "0.1"}),
        "Sets the terrain resolution needed for leg-scale checks (leg spacing ÷ 3)."),
      h("div", {"class": "f"}, [h("span", {text: "Scale ratio (Earth ÷ Moon)"}), h("strong", {text: fmt(S.scale.terrestrial_footprint_m / S.scale.lunar_footprint_m, 3)}),
        h("small", {text: "Geometry only — not dynamic, thermal or soil similarity."})])]),
    h("h3", {text: "Search"}),
    h("div", {"class": "row3"}, [fieldL("Steepest-slope limit (°)", numIn(S.constraints[0] ? num(S.constraints[0].split("<=")[1]) : null, function (v) {
        S.constraints = v === null ? [] : ["slope_deg.p90<=" + v]; }, {min: 0, max: 90, step: "0.5"}), "Optional. Leave empty for no limit."),
      fieldL("Equipment (comma separated)", txtIn(S.earth.equipment.join(", "), function (v) {
        S.earth.equipment = v.split(",").map(function (x) { return x.trim(); }).filter(Boolean); }))]),
    h("div", {"class": "row4"}, ["West", "South", "East", "North"].map(function (n, i) {
      return fieldL(n + " (°)", numIn(b[i], function (v) { S.earth.scope_bbox[i] = v; }, {step: "0.1"})); })),
    h("button", {"class": "btn sec small", type: "button", on: {click: function () { S.earth.scope_bbox = defaultScope(); renderScreen2(); }}, text: "Reset to available coverage"})]);
  d.addEventListener("toggle", function () { S.advOpen = d.open; });
  return d;
}

/* ================================================================== SEARCH (real engine stages) */
var FRIENDLY = [
  {label: "Understanding your lunar experiment", stages: ["lunar_target", "requirements"]},
  {label: "Searching available Earth terrain", stages: ["coverage", "earth_search"]},
  {label: "Comparing candidate locations", stages: ["compare", "evidence"]},
  {label: "Preparing your results", stages: ["results"]}];
var stageState = {};
function friendlyState(f) {
  var st = f.stages.map(function (s) { return (stageState[s] || {}).state || "pending"; });
  if (st.some(function (x) { return x === "blocked" || x === "failed"; })) return "blocked";
  if (st.every(function (x) { return x === "done"; })) return "done";
  if (st.some(function (x) { return x !== "pending"; })) return "running";
  return "pending";
}
function renderOverlay(status, msg) {
  var ov = document.getElementById("searchOverlay"); ov.hidden = false; ov.textContent = "";
  var A = CFG.animation || {}, running = status === "running";
  var img = A.available ? h("img", {src: running && !reduceMotion ? A.animated : A.still, alt: A.alt, width: A.width, height: A.height}) : null;
  var list = h("ol", {"class": "stages"}, FRIENDLY.map(function (f) { var s = friendlyState(f);
    return h("li", {"class": s}, [h("span", {"class": "ic", "aria-hidden": "true"}), h("span", {text: f.label})]); }));
  var buttons = [];
  if (status === "complete") buttons.push(h("button", {"class": "btn big go", type: "button", on: {click: function () { ov.hidden = true; go(3); }}, text: "See where to test →"}));
  if (["blocked", "failed", "offline", "invalid"].indexOf(status) >= 0) buttons.push(h("button", {"class": "btn sec", type: "button", on: {click: function () { ov.hidden = true; }}, text: "Back"}));
  ov.appendChild(h("div", {"class": "searchbox", role: "status", "aria-live": "polite"}, [img || h("div"), h("div", null, [
    h("h2", {id: "searchTitle", text: running ? "Rookie is sniffing out terrain…" : status === "complete" ? "Rookie found places to look at" : "Rookie couldn't finish"}),
    list, msg ? h("p", {"class": status === "complete" ? "hint" : "blocker", text: msg}) : null,
    h("div", {"class": "btnrow"}, buttons)])]));
}
function missionPayload() { return {target: S.target, search_mode: S.search_mode, moon_dataset: S.moon_dataset, earth_dataset: S.earth_dataset,
  earth: S.earth, scale: S.scale, environment: S.environment, experiments: S.experiments, constraints: S.constraints}; }
function startSearch() {
  stageState = {}; S.result = null;
  if (!engineOnline) { renderOverlay("offline", "The search engine isn't running. Start it with  python run_rookie.py --serve  and open http://127.0.0.1:8765"); return; }
  renderOverlay("running");
  fetch("/api/jobs", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(missionPayload())})
    .then(function (r) { return r.json().then(function (j) { return {code: r.status, body: j}; }); })
    .then(function (res) { if (res.code === 400) { renderOverlay("invalid", (res.body.errors || [res.body.error]).join(" ")); return; }
      S.job = res.body.job_id; poll(0); })
    .catch(function (e) { renderOverlay("failed", "Could not reach the engine: " + e); });
}
function poll(since) {
  fetch("/api/jobs/" + S.job + "?since=" + since).then(function (r) { return r.json(); }).then(function (j) {
    j.events.forEach(function (ev) { if (ev.state !== "progress") stageState[ev.stage] = {state: ev.state, detail: ev.detail}; });
    if (j.status === "queued" || j.status === "running") { renderOverlay("running"); setTimeout(function () { poll(j.n_events); }, 600); return; }
    S.result = j.result;
    if (j.status === "complete") {
      var n = (S.result.experiment_results || []).reduce(function (a, e) { return a + e.candidates.length; }, 0);
      renderOverlay("complete", n ? n + " discovered candidate areas (not ranked)." + (S.result.coverage_note ? " " + S.result.coverage_note : "")
        : "No candidate areas for the selected experiments." + (S.result.coverage_note ? " " + S.result.coverage_note : ""));
    } else if (j.status === "blocked") renderOverlay("blocked", plainBlocker(S.result.blocker.reason));
    else renderOverlay("failed", S.result.error || "Unknown error.");
    renderStepper();
  }).catch(function (e) { renderOverlay("failed", "Lost contact with the engine: " + e); });
}
function plainBlocker(reason) {
  if (/0 of \d+ coverage units/.test(reason)) return "Rookie has no Earth terrain for this search area yet. Choose an area with coverage, or add terrain data.";
  if (/catalogue has no entries/.test(reason)) return "The known-analog catalogue is still empty. Try “Discover new places” instead.";
  if (/below the resolvable size/.test(reason)) return "Your test area is smaller than the terrain data can resolve. Make it larger under Constraints.";
  return reason;
}

/* ================================================================== SCREEN 3 — WHERE TO TEST */
function renderScreen3() {
  var sc = document.getElementById("screen3"); sc.textContent = ""; var R = S.result;
  if (!R || !R.experiment_results) { sc.appendChild(h("p", {text: "No results yet."})); return; }
  if (!S.activeExp || !R.experiment_results.some(function (e) { return e.experiment_id === S.activeExp; })) S.activeExp = R.experiment_results[0].experiment_id;
  var ER = R.experiment_results.filter(function (e) { return e.experiment_id === S.activeExp; })[0];
  sc.appendChild(h("div", {"class": "hero"}, [h("h1", {id: "s3title", text: "Where should you test?"}),
    h("p", {"class": "lead", text: (R.coverage_note || "Rookie searched every area in your search region that has terrain data.")})]));
  if (R.contains_mock_data) sc.appendChild(h("p", {"class": "mockline"}, [badge("b-mock", "DEMO DATA"), " The lunar side uses demo (MOCK) terrain, so comparisons are illustrative. Earth terrain is " + (R.earth.contains_mock_data ? "also demo data." : "real.")]));
  if (R.experiment_results.length > 1) sc.appendChild(h("div", {"class": "tabs exp-tabs", role: "tablist"}, R.experiment_results.map(function (e) {
    return h("button", {type: "button", role: "tab", "aria-selected": String(e.experiment_id === S.activeExp),
      on: {click: function () { S.activeExp = e.experiment_id; renderScreen3(); }}}, [e.name, " ", h("span", {"class": "count", text: e.candidates.length ? String(e.candidates.length) : "—"})]); })));
  sc.appendChild(h("div", {"class": "bestline"}, [h("strong", {text: ER.best_site.label}), " ", h("span", {text: ER.best_site.reason})]));
  var layout = h("div", {"class": "results"}, [
    h("div", {"class": "mapcol"}, [h("div", {id: "earthMap", role: "img", "aria-label": "Map of discovered candidate areas"}), h("p", {"class": "hint", id: "mapNote"})]),
    h("div", {"class": "cardcol"}, ER.candidates.length ? [h("div", {"class": "previewhead"}, [h("strong", {text: ER.preview_label}), h("small", {text: ER.preview_rule})])]
      .concat(ER.candidates.map(function (c) { return resultCard(c, ER); }))
      : [h("div", {"class": "nocand"}, [h("strong", {text: "No locations suggested for this experiment yet"}), h("p", {text: ER.no_candidates_reason})])])]);
  sc.appendChild(layout);
  sc.appendChild(h("div", {"class": "twostage"}, [
    h("div", null, [h("h3", {text: "FIELD TEST"}), h("ul", null, (ER.validation.field || []).map(function (x) { return h("li", {text: x}); }))]),
    h("div", null, [h("h3", {text: "LABORATORY VALIDATION"}), h("p", {text: ER.validation.lab || "—"})]),
    h("p", {"class": "vac", text: ER.validation.vacuum_sentence})]));
  sc.appendChild(h("div", {"class": "winnerline"}, [h("strong", {text: "OVERALL MULTI-EXPERIMENT WINNER · "}), h("span", {text: R.overall_winner.label}),
    h("details", null, [h("summary", {text: "Why?"}), h("p", {"class": "hint", text: "Needs team approval of: " + R.overall_winner.required_before_computation.join(", ") + "."})])]));
  sc.appendChild(h("div", {"class": "btnrow"}, [h("button", {"class": "btn sec", type: "button", on: {click: function () { go(2); }}, text: "← Change constraints"}), h("span")]));
  drawEarthMap(R, ER);
}
function placeLine(c) {
  return c.place && c.place.label ? c.place.label + " · " + coordStr(c.centroid.lat, c.centroid.lon) : coordStr(c.centroid.lat, c.centroid.lon) + " (area centre)";
}
function resultCard(c, ER) {
  return h("article", {"class": "rcard", id: "card-" + c.id, tabindex: "-1"}, [
    h("div", {"class": "rhead"}, [h("span", {"class": "pin", text: c.label}), h("div", null, [h("div", {"class": "kick", text: "📍 " + c.title}),
      h("div", {"class": "loc", text: placeLine(c)}),
      h("div", {"class": "meta", text: c.size_km[0] + " × " + c.size_km[1] + " km area" + (c.distance_from_start_km !== null ? " · " + fmt(c.distance_from_start_km, 0) + " km from your start (straight line)" : "")})])]),
    h("p", {"class": "status"}, [badge("b-pending", "Unverified · not ranked")]),
    h("h4", {text: "Why Rookie identified it"}), h("ul", null, c.why.slice(0, 2).map(function (x) { return h("li", {text: x}); })),
    h("h4", {text: "What is still missing"}), h("ul", null, c.missing.slice(0, 1).map(function (x) { return h("li", {text: x}); })),
    h("h4", {text: "Next recommended action"}), h("ul", null, c.next_actions.slice(0, 1).map(function (x) { return h("li", {text: x}); })),
    h("div", {"class": "cardbtns"}, [h("button", {"class": "btn", type: "button", on: {click: function () { openSite(c, ER); }}, text: "EXPLORE SITE"}),
      h("button", {"class": "btn sec", type: "button", on: {click: function () { openAlternatives(ER); }}, text: "VIEW ALTERNATIVES"})])]);
}
function drawEarthMap(R, ER) {
  var el = document.getElementById("earthMap"); if (!el || !window.Plotly) return;
  var b = R.mission.earth.scope_bbox, traces = [];
  /* Plotly geo fills the side of a ring on its right: GeoJSON rings are counter-clockwise, so reverse them
     for drawing (otherwise the fill covers the whole globe outside the box). */
  function poly(ring, color, fill, name, cd, width) { ring = ring.slice().reverse();
    return {type: "scattergeo", mode: "lines", fill: fill ? "toself" : "none", fillcolor: fill || undefined,
    lon: ring.map(function (p) { return p[0]; }), lat: ring.map(function (p) { return p[1]; }), line: {color: color, width: width || 1},
    name: name, customdata: cd ? ring.map(function () { return cd; }) : null, hoverinfo: "name", showlegend: false}; }
  traces.push(poly([[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]], "#eb6834", null, "Your search area", null, 2));
  (R.earth.tiles || []).forEach(function (t) { var m = /^([NS])(\d{2})([EW])(\d{3})$/.exec(t.tile); if (!m) return;
    var la = (+m[2]) * (m[1] === "N" ? 1 : -1), lo = (+m[4]) * (m[3] === "E" ? 1 : -1);
    traces.push(poly([[lo, la], [lo + 1, la], [lo + 1, la + 1], [lo, la + 1], [lo, la]], t.status === "processed" ? "#5fd0a0" : "#4b5878", null,
      t.status === "processed" ? "Searched area" : "No terrain data here (not searched)")); });
  ER.alternatives.forEach(function (a) { traces.push(poly(a.boundary, "rgba(127,179,240,0.5)", "rgba(127,179,240,0.08)", "Other discovered area (not ranked)")); });
  ER.candidates.forEach(function (c) { traces.push(poly(c.boundary, "#f2b84b", "rgba(242,184,75,0.35)", "Candidate " + c.label, c.id, 2)); });
  traces.push({type: "scattergeo", mode: "markers+text", lon: ER.candidates.map(function (c) { return c.centroid.lon; }), lat: ER.candidates.map(function (c) { return c.centroid.lat; }),
    text: ER.candidates.map(function (c) { return c.label; }), textposition: "middle center", textfont: {color: "#111", size: 12},
    marker: {size: 18, color: "#f2b84b", line: {color: "#111", width: 1}}, customdata: ER.candidates.map(function (c) { return c.id; }),
    hovertemplate: "Candidate %{text}<extra>click to explore</extra>", showlegend: false});
  var sl = R.mission.earth.start_location;
  if (sl && sl.lat !== null && sl.lat !== undefined && sl.lon !== null && sl.lon !== undefined)
    traces.push({type: "scattergeo", mode: "markers", lon: [sl.lon], lat: [sl.lat], marker: {size: 11, color: "#ffffff", symbol: "star"}, name: "Your start", hoverinfo: "name", showlegend: false});
  var pad = 1.5, layout = {margin: {l: 0, r: 0, t: 0, b: 0}, paper_bgcolor: "#0a1020",
    geo: {projection: {type: "mercator"}, showland: true, landcolor: "#1b2640", showocean: true, oceancolor: "#0b1428", showcountries: true,
      countrycolor: "#4a5a80", coastlinecolor: "#7b8db8", bgcolor: "#0a1020", lataxis: {range: [b[1] - pad, b[3] + pad]}, lonaxis: {range: [b[0] - pad, b[2] + pad]}}};
  var note = document.getElementById("mapNote");
  function onClick(ev) { var p = ev.points && ev.points[0]; if (!p || !p.customdata) return;
    var c = ER.candidates.filter(function (x) { return x.id === p.customdata; })[0]; if (c) openSite(c, ER); }
  Plotly.newPlot(el, traces, layout, {displaylogo: false, responsive: true}).then(function () {
    note.textContent = "Yellow: candidate areas A–C. Blue outlines: other discovered areas. Green: searched terrain. Grey: no data. Click a candidate to explore it.";
    el.on("plotly_click", onClick);
  }).catch(function () {
    note.textContent = "World outlines need an internet connection; showing a plain latitude/longitude map.";
    Plotly.newPlot(el, traces.map(function (t) { return Object.assign({}, t, {type: "scatter", x: t.lon, y: t.lat}); }),
      {margin: {l: 50, r: 10, t: 10, b: 40}, paper_bgcolor: "#0a1020", plot_bgcolor: "#0a1020", font: {color: "#a6b1c8"},
       xaxis: {title: "Longitude", range: [b[0] - pad, b[2] + pad]}, yaxis: {title: "Latitude", range: [b[1] - pad, b[3] + pad], scaleanchor: "x"}},
      {displaylogo: false, responsive: true}).then(function () { el.on("plotly_click", onClick); });
  });
}
function openAlternatives(ER) {
  var ov = document.getElementById("detail"); ov.hidden = false; ov.textContent = "";
  function close() { ov.hidden = true; }
  ov.appendChild(h("div", {"class": "dialog narrow"}, [h("button", {"class": "btn sec close", type: "button", on: {click: close}, text: "Close ✕"}),
    h("h2", {id: "detailTitle", text: "Other discovered areas — " + ER.name}),
    h("p", {"class": "hint", text: ER.alternatives.length + " more areas passed Rookie's data checks. They are not ranked; listed by position."}),
    h("ul", {"class": "altlist"}, ER.alternatives.slice(0, 60).map(function (a) {
      return h("li", null, [coordStr(a.centroid[0], a.centroid[1]) + " · " + fmt(a.area_km2, 0) + " km² ",
        h("button", {"class": "btn sec small", type: "button", on: {click: function () { openSite(altCard(a, ER), ER); }}, text: "Explore"})]); })),
    ER.alternatives.length > 60 ? h("p", {"class": "hint", text: "Showing 60 of " + ER.alternatives.length + "."}) : null]));
}
function altCard(a, ER) {
  var first = ER.candidates[0] || {};
  return {id: a.id, label: "•", window_id: a.id, title: "DISCOVERED TEST LOCATION", centroid: {lat: a.centroid[0], lon: a.centroid[1]},
    boundary: a.boundary, area_km2: a.area_km2, size_km: first.size_km || ["–", "–"], place: null, distance_from_start_km: null,
    why: ["Passed Rookie's data checks for this experiment (details under View technical data)."],
    missing: (first.missing || []), next_actions: (first.next_actions || []), could_invalidate: first.could_invalidate || [],
    validation: first.validation || ER.validation, provenance: first.provenance || {}, experiment_name: ER.name, status: "unverified candidate"};
}

/* ------------------------------------------------------------------ site detail: 3 levels */
var figCache = {};
function openSite(c, ER) {
  var ov = document.getElementById("detail"); ov.hidden = false; ov.textContent = "";
  var level = 1, body = h("div");
  function close() { ov.hidden = true; document.removeEventListener("keydown", onKey); }
  function onKey(e) { if (e.key === "Escape") close(); }
  document.addEventListener("keydown", onKey);
  var nav = h("div", {"class": "levels", role: "tablist"}, [["The decision", 1], ["Why this site?", 2], ["View technical data", 3]].map(function (l) {
    return h("button", {type: "button", role: "tab", "aria-selected": String(level === l[1]), on: {click: function () { level = l[1];
      nav.querySelectorAll("button").forEach(function (b, i) { b.setAttribute("aria-selected", String(i + 1 === level)); }); show(); }}, text: l[0]}); }));
  ov.appendChild(h("div", {"class": "dialog"}, [h("button", {"class": "btn sec close", type: "button", on: {click: close}, text: "Close ✕"}),
    h("div", {"class": "kick", text: "📍 " + c.title + " · " + c.experiment_name}),
    h("h2", {id: "detailTitle", text: placeLine(c)}), nav, body]));
  function show() { body.textContent = ""; ({1: level1, 2: level2, 3: level3})[level](); }
  function level1() {
    body.appendChild(h("div", {"class": "l1"}, [
      h("dl", {"class": "kv"}, [h("dt", {text: "Location"}), h("dd", {text: placeLine(c)}),
        h("dt", {text: "What this point is"}), h("dd", {text: "The centre of a discovered area — not a verified or accessible test point."}),
        h("dt", {text: "Area"}), h("dd", {text: c.size_km[0] + " × " + c.size_km[1] + " km (" + fmt(c.area_km2, 0) + " km²)"}),
        c.place && c.place.source ? [h("dt", {text: "Place name"}), h("dd", {text: c.place.source})] : null,
        h("dt", {text: "Status"}), h("dd", {text: "Unverified candidate, not ranked"})]),
      h("h4", {text: "Why Rookie identified it"}), h("ul", null, c.why.map(function (x) { return h("li", {text: x}); })),
      h("h4", {text: "What is still missing"}), h("ul", null, c.missing.map(function (x) { return h("li", {text: x}); })),
      h("h4", {text: "Next recommended actions"}), h("ol", null, c.next_actions.map(function (x) { return h("li", {text: x}); }))]));
  }
  function level2() {
    var R = S.result, v = c.validation || {};
    body.appendChild(h("div", {"class": "l2"}, [
      h("h4", {text: "Evidence quality"}), h("p", {text: "Terrain screening only, from " + (c.provenance.earth || "Earth terrain data") + (c.provenance.earth_is_mock ? " (demo data)" : "") +
        ". The lunar side is " + (c.provenance.lunar_is_mock ? "demo (MOCK) terrain, so the comparison is illustrative." : "real lunar terrain.")}),
      h("h4", {text: "What could rule this site out"}), h("ul", null, (c.could_invalidate || []).map(function (x) { return h("li", {text: x}); })),
      h("h4", {text: "Search coverage"}), h("p", {text: R.coverage_note || R.earth.coverage.statement}),
      h("div", {"class": "twostage"}, [h("div", null, [h("h3", {text: "FIELD TEST"}), h("ul", null, (v.field || []).map(function (x) { return h("li", {text: x}); }))]),
        h("div", null, [h("h3", {text: "LABORATORY VALIDATION"}), h("p", {text: v.lab || "—"})]), h("p", {"class": "vac", text: v.vacuum_sentence || ""})]),
      h("h4", {text: "Spectral evidence (SWIR)"}), h("p", {text: R.swir && R.swir.present ? "Spectral evidence is not yet available for this location. (Research only; it would never count as soil-strength evidence.)" : "Not defined in the specification."}),
      h("h4", {text: "Scale"}), h("p", {text: "Earth test area vs lunar area: ratio " + fmt(R.scale.geometric_ratio, 3) + ". " + R.scale.limitation})]));
  }
  function level3() {
    var tabs = [["elevation", "Elevation"], ["slope", "Slope"], ["roughness", "Roughness"], ["terrain_3d", "3D terrain"], ["numbers", "Numbers & provenance"]], t = "elevation";
    var holder = h("div");
    var bar = h("div", {"class": "tabs", role: "tablist"}, tabs.map(function (x) { return h("button", {type: "button", role: "tab", "aria-selected": String(x[0] === t),
      on: {click: function () { t = x[0]; bar.querySelectorAll("button").forEach(function (b, i) { b.setAttribute("aria-selected", String(tabs[i][0] === t)); }); draw(); }}, text: x[1]}); }));
    body.appendChild(bar); body.appendChild(holder);
    function draw() {
      holder.textContent = "";
      if (t === "numbers") return holder.appendChild(numbersView(c));
      var fig = h("div", {"class": "fig"}); holder.appendChild(fig);
      var k = S.job + "|" + c.window_id;
      function plot(d) { var f = d.figures[t]; Plotly.newPlot(fig, f.data, f.layout, {displaylogo: false, responsive: true}); }
      if (figCache[k]) return plot(figCache[k]);
      fig.appendChild(h("p", {"class": "loading", text: "Loading real terrain from the engine…"}));
      fetch("/api/jobs/" + S.job + "/figures/" + encodeURIComponent(c.window_id)).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) { figCache[k] = d; fig.textContent = ""; plot(d); })
        .catch(function (e) { fig.textContent = ""; fig.appendChild(h("p", {"class": "blocker", text: "Terrain maps unavailable: " + e})); });
    }
    draw();
  }
  show();
}
function numbersView(c) {
  var R = S.result, w = (R.candidates || []).filter(function (x) { return x.id === c.window_id; })[0];
  if (!w) return h("p", {text: "No technical record."});
  var rows = Object.keys(w.comparison).map(function (k) { var f = w.comparison[k];
    return h("tr", null, [h("td", {text: k === "slope_deg" ? "Slope (°)" : "Roughness, 3×3 (m)"}),
      h("td", {"class": "num", text: f.status === "computed" ? fmt(f.moon.p50, 2) + " / " + fmt(f.moon.p90, 2) : "–"}),
      h("td", {"class": "num", text: f.status === "computed" ? fmt(f.earth.p50, 2) + " / " + fmt(f.earth.p90, 2) : "–"}),
      h("td", {"class": "num", text: f.status === "computed" ? fmt(f.w1, 2) : f.status})]); });
  var src = (w.dataset.sources || []).map(function (s) { return s.file + " (sha256 " + s.sha256.slice(0, 12) + "…)"; }).join("; ");
  return h("div", null, [h("div", {"class": "tw"}, [h("table", null, [h("thead", null, [h("tr", null, ["Feature", "Moon p50 / p90" + (R.moon.is_mock ? " (MOCK)" : ""), "Earth p50 / p90", "Distribution distance (W1)"].map(function (x) { return h("th", {text: x}); }))]),
    h("tbody", null, rows)])]),
    h("dl", {"class": "kv", style: "margin-top:12px"}, [h("dt", {text: "Earth data"}), h("dd", {text: w.dataset.label + " · " + src}),
      h("dt", {text: "Lunar data"}), h("dd", {text: R.moon.dataset_id + (R.moon.is_mock ? " (MOCK)" : "") + " · " + R.moon.n_samples + " samples"}),
      h("dt", {text: "Resolution"}), h("dd", {text: w.resolution_limitation}), h("dt", {text: "Scale check"}), h("dd", {text: w.spacing_check.detail}),
      h("dt", {text: "Bounds (W, S, E, N)"}), h("dd", {text: w.bounds_wsen.join(", ")}),
      h("dt", {text: "Window ID"}), h("dd", {text: w.id})]),
    h("p", {"class": "hint", text: "Per-feature distances only — no weights, scores or pass/fail (team decision 2026-11-15)."})]);
}

/* ------------------------------------------------------------------ boot */
function footer() {
  var f = document.getElementById("foot");
  f.appendChild(h("p", {text: "Rookie · LunarMatch engine · specification " + (CFG.spec.loaded || "—") + ". Candidates are discovered, not ranked; no experiment is approved."}));
}
function checkEngine() {
  var pill = document.getElementById("enginePill");
  if (location.protocol === "file:") { pill.className = "pill off"; pill.textContent = "Engine offline"; return; }
  fetch("/api/health").then(function (r) { return r.json(); }).then(function () {
    engineOnline = true; pill.className = "pill ok"; pill.textContent = "Engine online";
    return fetch("/api/config").then(function (r) { return r.json(); }).then(function (c) { var a = CFG.animation; CFG = c; CFG.animation = a; });
  }).catch(function () { pill.className = "pill off"; pill.textContent = "Engine offline"; });
}
/* Demo / test deep links (real engine only): #experiments=EXP_02&autorun=1 · #job=<id>&exp=EXP_02&site=A&level=3 */
function hashParams() { var q = {}; (location.hash || "").replace(/^#/, "").split("&").forEach(function (kv) {
  var p = kv.split("="); if (p[0]) q[decodeURIComponent(p[0])] = decodeURIComponent(p[1] || ""); }); return q; }
function applyHash(q) {
  if (q.experiments) S.experiments = q.experiments.split(",").filter(function (id) { return !!exp(id); });
  if (q.screen === "2" && canGo(2)) go(2); else if (q.experiments) renderScreen1();
  function afterResult() {
    var w = setInterval(function () { if (!S.result) return; clearInterval(w); document.getElementById("searchOverlay").hidden = true;
      if (q.exp) S.activeExp = q.exp; go(3);
      if (q.site) { var ER = S.result.experiment_results.filter(function (e) { return e.experiment_id === S.activeExp; })[0];
        var c = ER && ER.candidates.filter(function (x) { return x.label === q.site; })[0];
        if (c) { openSite(c, ER); if (q.level) { var b = document.querySelectorAll(".levels button")[+q.level - 1]; if (b) b.click(); } } } }, 200);
  }
  if (q.job) { S.job = q.job; afterResult(); var k = setInterval(function () { if (engineOnline) { clearInterval(k); poll(0); } }, 100); return; }
  if (q.autorun === "1") { afterResult(); var t = 0, kk = setInterval(function () { t++; if (engineOnline || t > 40) { clearInterval(kk); go(2); startSearch(); } }, 150); }
}
footer(); checkEngine(); go(1); applyHash(hashParams());
})();
