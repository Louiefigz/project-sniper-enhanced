// Native pipeline authoring. Layout intent is not observed caption-safety proof.
"use strict";
const nplRenderer = {
  LINE_STAGGER_S: 0.12,
  NODE_STAGGER_S: 0.15,
  LAND_DEFAULT_START_S: 0.2,
  LAND_DEFAULT_GAP_S: 0.9,
  defaults: {
    eyebrow: "", eyebrowAccent: "result", headlineLines: "", explainer: "",
    nodes: "", activeIndex: 0, footChip: "", footAccent: "result",
    moduleLands: "", exit: "hold", presenterFrame: false, layout: "full-canvas",
  },
  sample: {
    eyebrow: "ONE INSTRUCTION TO FINISHED VIDEO",
    headlineLines: "The chain changed.|The outcome held.",
    nodes: "01~PROMPT|02~ELEVENLABS VOICE|03~HEYGEN AVATAR V|" +
      "04~HYPERFRAMES EDIT|05~INDEPENDENT QA|06~FINISHED VIDEO",
    activeIndex: 5,
  },
  text(vars, key) { return (vars[key] == null ? "" : String(vars[key])).trim(); },
  variables() {
    const hf = window.__hyperframes;
    let vars = Object.assign({}, this.defaults, hf && hf.getVariables ? hf.getVariables() : {});
    const content = ["eyebrow", "headlineLines", "explainer", "nodes", "footChip"];
    if (content.every((key) => !this.text(vars, key))) vars = Object.assign({}, vars, this.sample);
    return vars;
  },
  layout(context) {
    const { vars, root } = context;
    const presenter = vars.presenterFrame === true || String(vars.presenterFrame) === "true";
    if (!["full-canvas", "caption-safe-upper-v1", "teaching-full-width-v1"].includes(vars.layout)) {
      throw new Error("module-pipeline: unsupported explicit layout");
    }
    if (vars.layout === "caption-safe-upper-v1") {
      const count = this.text(vars, "nodes").split("|").length;
      if (presenter || vars.exit !== "hold" || count < 2 || count > 6) {
        throw new Error("module-pipeline: upper layout requires 2-6 nodes, hold exit and no presenter hole");
      }
    }
    if (vars.layout === "teaching-full-width-v1") {
      const count = this.text(vars, "nodes").split("|").length;
      const noPresenter = vars.presenterFrame === false || vars.presenterFrame === "false";
      if (!noPresenter || count < 2 || count > 6 || !["hold", "blur-recede"].includes(vars.exit)) {
        throw new Error("module-pipeline: teaching layout requires 2-6 nodes, a supported exit and no presenter hole");
      }
    }
    root.dataset.sniperLayout = vars.layout;
    if (presenter) root.classList.add("has-presenter");
  },
  eyebrow(vars) {
    const text = this.text(vars, "eyebrow"), element = document.getElementById("npl-eyebrow");
    if (!text) { element.remove(); return; }
    document.getElementById("npl-eyebrow-text").textContent = text;
    element.dataset.sniperProtectedRole = "eyebrow";
    if (this.text(vars, "eyebrowAccent") === "process") element.classList.add("process");
  },
  headline(vars) {
    const text = this.text(vars, "headlineLines"), element = document.getElementById("npl-headline");
    if (!text) { element.remove(); return; }
    const lines = text.split("|").map((line) => line.trim());
    if (lines.length > 2) {
      throw new Error("module-pipeline: headlineLines is 2 lines max (§1.1 thesis grammar), got " + lines.length);
    }
    lines.forEach((line, index) => {
      const child = document.createElement("span");
      child.className = "line" + (index === 1 ? " l2" : "");
      child.dataset.sniperProtectedRole = "headline-line-" + (index + 1);
      child.textContent = line; element.appendChild(child);
    });
  },
  explainer(vars) {
    const text = this.text(vars, "explainer"), element = document.getElementById("npl-explainer");
    if (!text) { element.remove(); return; }
    element.textContent = text; element.dataset.sniperProtectedRole = "explainer";
  },
  node(line, index, activeIndex) {
    const fields = line.split("~").map((field) => field.trim());
    if (fields.length !== 2 || !fields[0] || !fields[1]) {
      throw new Error("module-pipeline: node " + (index + 1) + " needs num~label, got '" + line + "'");
    }
    const node = document.createElement("div"), numrow = document.createElement("div");
    node.className = "npl-node" + (index + 1 === activeIndex ? " active" : "");
    node.dataset.sniperProtectedRole = "node-" + (index + 1);
    numrow.className = "numrow";
    const num = document.createElement("span"); num.className = "num"; num.textContent = fields[0];
    numrow.appendChild(num);
    if (index + 1 === activeIndex) {
      const dot = document.createElement("span"); dot.className = "activedot"; numrow.appendChild(dot);
    }
    const label = document.createElement("span"); label.className = "label"; label.textContent = fields[1];
    node.appendChild(numrow); node.appendChild(label); return node;
  },
  nativeCell(node, index, count) {
    const cell = document.createElement("div"); cell.className = "npl-native-cell";
    cell.appendChild(node);
    if (index < count - 1) {
      const link = document.createElement("span"); link.className = "npl-native-link";
      link.dataset.sniperProtectedRole = "connector-" + (index + 1); cell.appendChild(link);
    }
    return cell;
  },
  chain(vars) {
    const raw = this.text(vars, "nodes"), chain = document.getElementById("npl-chain");
    if (!raw) { chain.remove(); return []; }
    const lines = raw.split("|");
    if (lines.length < 2 || lines.length > 8) {
      throw new Error("module-pipeline: nodes needs 2-8 tiles, got " + lines.length);
    }
    const activeRaw = vars.activeIndex;
    const activeIndex = activeRaw == null || String(activeRaw).trim() === "" ? 0 : Number(activeRaw);
    if (!isFinite(activeIndex) || activeIndex < 0 || activeIndex > lines.length || activeIndex % 1 !== 0) {
      throw new Error("module-pipeline: activeIndex must be an integer in [0," + lines.length +
        "], got '" + vars.activeIndex + "'");
    }
    return lines.map((line, index) => {
      const node = this.node(line, index, activeIndex);
      chain.appendChild(vars.layout === "caption-safe-upper-v1" ? this.nativeCell(node, index, lines.length) : node);
      return node;
    });
  },
  foot(vars) {
    const text = this.text(vars, "footChip"), element = document.getElementById("npl-foot");
    if (!text) { element.remove(); return; }
    document.getElementById("npl-foot-text").textContent = text;
    element.dataset.sniperProtectedRole = "footnote";
    const accent = this.text(vars, "footAccent") || "result";
    if (accent === "process" || accent === "warn") element.classList.add(accent);
    else if (accent !== "result") {
      throw new Error("module-pipeline: footAccent '" + accent + "' not in result|process|warn");
    }
  },
  lands(context) {
    const { vars, nodes } = context, modules = [];
    if (["eyebrow", "headlineLines", "explainer"].some((key) => this.text(vars, key))) modules.push("head");
    if (nodes.length) modules.push("chain");
    if (this.text(vars, "footChip")) modules.push("foot");
    const value = vars.moduleLands;
    const raw = Array.isArray(value) ? value.map(String) :
      String(value == null ? "" : value).trim() ? String(value).split(/[|,]/) : [];
    const lands = raw.length ? raw.map((item) => parseFloat(item)) :
      modules.map((_, index) => this.LAND_DEFAULT_START_S + index * this.LAND_DEFAULT_GAP_S);
    if (raw.length && (lands.length !== modules.length || lands.some((item) => !isFinite(item)))) {
      throw new Error("module-pipeline: moduleLands needs " + modules.length +
        " finite times for modules [" + modules.join(", ") + "], got '" + raw.join(",") + "'");
    }
    return Object.fromEntries(modules.map((name, index) => [name, lands[index]]));
  },
  animateHead(context, timeline, at) {
    if (at == null) return;
    const { vars, motion } = context;
    let headAt = at;
    if (this.text(vars, "eyebrow")) {
      motion.textRamp(timeline, document.getElementById("npl-eyebrow"), at);
      headAt += motion.EYEBROW_LEAD_S;
    }
    let lastAt = headAt;
    if (this.text(vars, "headlineLines")) {
      document.getElementById("npl-headline").querySelectorAll(".line").forEach((line, index) => {
        lastAt = headAt + index * this.LINE_STAGGER_S; motion.textRamp(timeline, line, lastAt);
      });
    }
    if (this.text(vars, "explainer")) {
      motion.textRamp(timeline, document.getElementById("npl-explainer"), lastAt + this.LINE_STAGGER_S);
    }
  },
  animate(context) {
    const lands = this.lands(context), timeline = gsap.timeline({ paused: true });
    this.animateHead(context, timeline, lands.head);
    if (lands.chain != null) {
      context.motion.textRamp(timeline, document.getElementById("npl-chain"), lands.chain);
      context.nodes.forEach((node, index) => {
        const target = context.vars.layout === "caption-safe-upper-v1" ? node.parentElement : node;
        context.motion.textRamp(timeline, target, lands.chain + index * this.NODE_STAGGER_S);
      });
    }
    if (lands.foot != null) context.motion.textRamp(timeline, document.getElementById("npl-foot"), lands.foot);
    if (String(context.vars.exit) === "blur-recede") {
      context.motion.blurRecede(timeline, "#npl-stage-layer", context.duration - context.motion.EXIT_BLUR_S);
    }
    timeline.seek(0);
    window.__timelines = window.__timelines || {};
    window.__timelines["module-pipeline"] = timeline;
  },
  boot() {
    const root = document.getElementById("npl-root"), vars = this.variables();
    const context = { root, vars, duration: parseFloat(root.dataset.duration) || 9,
      motion: window.__motionTokens, nodes: [] };
    this.layout(context);
    this.eyebrow(vars); this.headline(vars); this.explainer(vars);
    context.nodes = this.chain(vars); this.foot(vars); this.animate(context);
  },
};
nplRenderer.boot();
