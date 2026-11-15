/* RookieSearch: reusable search-status component.
 *
 *   var rs = new RookieSearch({animated, still, alt, width, height, title});
 *   container.appendChild(rs.el);
 *   rs.setState("unavailable", "message");          // idle | searching | done | unavailable | error
 *   rs.run(function(){ return realSearchPromise; }, {searching: "...", error: "..."})
 *     .then(function(result){ ...render result... }); // task resolves {message: "..."}
 *
 * The animated GIF is loaded only in the "searching" state, so the dog never
 * "searches" unless a real task is running. With prefers-reduced-motion the
 * <picture> source swaps the animation for the still first frame.
 */
(function(global){
"use strict";
var LABELS = {idle:"Ready", searching:"Searching…", done:"Search complete",
              unavailable:"Search not enabled", error:"Search failed"};

function RookieSearch(opts){
  opts = opts || {};
  this.opts = opts;
  var fig = document.createElement("figure");
  fig.className = "rs";
  var frame = document.createElement("div");
  frame.className = "rs-frame";
  if (opts.animated && opts.still) {
    var pic = document.createElement("picture");
    this.source = document.createElement("source");
    this.source.media = "(prefers-reduced-motion: reduce)";
    this.source.srcset = opts.still;
    this.img = document.createElement("img");
    this.img.alt = opts.alt || "Rookie the guide dog";
    if (opts.width) this.img.width = opts.width;
    if (opts.height) this.img.height = opts.height;
    this.img.decoding = "async";
    this.img.src = opts.still;
    pic.appendChild(this.source); pic.appendChild(this.img); frame.appendChild(pic);
  } else {
    var miss = document.createElement("div");
    miss.className = "rs-missing";
    miss.textContent = opts.missingText || "Rookie animation not found.";
    frame.appendChild(miss);
  }
  var body = document.createElement("div"); body.className = "rs-body";
  this.badge = document.createElement("span"); this.badge.className = "rs-badge";
  var title = document.createElement("h3"); title.className = "rs-title";
  title.textContent = opts.title || "Earth analog search";
  this.msg = document.createElement("figcaption"); this.msg.className = "rs-msg";
  this.msg.setAttribute("role", "status"); this.msg.setAttribute("aria-live", "polite");
  body.appendChild(this.badge); body.appendChild(title); body.appendChild(this.msg);
  if (opts.credit) {
    var c = document.createElement("p"); c.className = "rs-credit"; c.textContent = opts.credit;
    body.appendChild(c);
  }
  fig.appendChild(frame); fig.appendChild(body);
  this.el = fig;
  this.setState("idle", opts.idleText || "");
}
RookieSearch.STATES = Object.keys(LABELS);
RookieSearch.prototype.setState = function(state, message){
  if (!LABELS[state]) throw new Error("unknown RookieSearch state: " + state);
  this.state = state;
  this.el.setAttribute("data-state", state);
  this.el.setAttribute("aria-busy", state === "searching" ? "true" : "false");
  this.badge.textContent = LABELS[state];
  if (this.img) this.img.src = state === "searching" ? this.opts.animated : this.opts.still;
  this.msg.textContent = message || "";
};
RookieSearch.prototype.run = function(task, messages){
  var self = this; messages = messages || {};
  self.setState("searching", messages.searching || "Sniffing out terrain that matches your target…");
  return Promise.resolve().then(task).then(function(result){
    self.setState("done", (result && result.message) || "");
    return result;
  }, function(err){
    self.setState("error", messages.error || ("The search stopped: " + (err && err.message || err)));
    throw err;
  });
};
global.RookieSearch = RookieSearch;
})(window);
