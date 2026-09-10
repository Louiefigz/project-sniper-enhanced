"use strict";

const { createHash } = require("node:crypto");
const policy = require("./review-policy.json");
const BUNDLE = "assets/index-BZBjzYc8.js";
const FONT_PATH = "/__sniper_studio_fonts.css";
const hash = (value) => createHash("sha256").update(value).digest("hex");
const MOTION_NOTICE = "Native motion-path editing is not qualified offline. Use Sniper motion controls.";
const GOOGLE_DISCOVERY = 'b.useEffect(()=>{let oe=!1;return _(!0),fetch("/api/fonts/google").then(Y=>Y.ok?Y.json():null).then(Y=>{oe||!Array.isArray(Y==null?void 0:Y.fonts)||w(eE([...Y.fonts,...NF]))}).catch(()=>{}).finally(()=>{oe||_(!1)}),()=>{oe=!0}},[])';

function replaceOnce(source, before, after) {
  if (source.split(before).length !== 2) throw new Error("Audited Studio runtime seam changed; re-audit required");
  return source.replace(before, () => after);
}

function replaceFunction(source, markers, expected, replacement) {
  const begin = source.indexOf(markers[0]), end = source.indexOf(markers[1], begin);
  if (begin < 0 || end < 0) throw new Error("Audited Studio runtime function is missing");
  const original = source.slice(begin, end);
  if (hash(original) !== expected) throw new Error("Audited Studio runtime function changed");
  return replaceOnce(source, original, replacement);
}

/** No eager CDN plugin for ordinary GSAP timelines. Actual motion-path vars
 * stay explicitly unsupported; neither a fake plugin nor a successful load is invented. */
const LOCAL_MOTION = `function _we(t){
  if(!t?.contentWindow||!t.contentDocument)return;
  const win=t.contentWindow;
  for(const timeline of Object.values(win.__timelines||{})){
    if(!timeline||typeof timeline.getChildren!=="function")continue;
    for(const tween of timeline.getChildren(true,true,true)){
      if(tween?.vars&&Object.prototype.hasOwnProperty.call(tween.vars,"motionPath")){
        throw new Error(${JSON.stringify(MOTION_NOTICE)});
      }
    }
  }
}`;

/** Exact pinned shell-only correction; vendor files and project HTML are unchanged. */
function transformStudioBundle(bytes) {
  if (hash(bytes) !== policy.uiSha256[BUNDLE]) throw new Error("Offline Studio requires the exact audited frontend bundle");
  let source = bytes.toString("utf8");
  source = replaceFunction(source, ["function _we(", "function Iwe("],
    "3053f53fed35d46cc99be4d64a5d8de2deb168806a6a1d28d522517d928e90ad", LOCAL_MOTION);
  // The actual soft-reload branch uses this same pattern to request the CDN.
  source = replaceOnce(source, "function Lwe(t,e,n,r){", `function Lwe(t,e,n,r){
    if(/motionPath\\s*[:{]/.test(e||""))throw new Error(${JSON.stringify(MOTION_NOTICE)});`);
  source = replaceFunction(source, ["function vZ(", "function ev("],
    "db16e0f96ec8b925aa3319b3c3d3ddddc8a2e6738da24c3c630eff89ebdc8453", "function vZ(t){return;}");
  // Native family selection/import is outside the timing/plain-copy bridge.
  // Disable it in React, not after a click; mounting no longer fetches Google CSS.
  source = replaceOnce(source, "function uFe({value:t,disabled:e,importedFonts:n,onImportFonts:r,onCommit:i}){",
    "function uFe({value:t,disabled:e,importedFonts:n,onImportFonts:r,onCommit:i}){e=true;");
  // This otherwise triggers a SERVER-side external metadata request, which a
  // browser request allowlist cannot see. Disabled family controls need no discovery.
  source = replaceOnce(source, GOOGLE_DISCOVERY, "b.useEffect(()=>{},[])");
  return Buffer.from(source, "utf8");
}

/** Shell text previews use the very same pinned local font bytes as compositions,
 * but none of tokens.css's scene/layout rules are applied to the Studio shell. */
function localFontStyles(bytes) {
  if (hash(bytes) !== policy.localFontTokensSha256) throw new Error("Studio local fonts require re-audit after token changes");
  const faces = bytes.toString("utf8").match(/@font-face\s*\{[^}]*\}/gu);
  if (!faces || faces.length !== 4 || faces.some((face) => !/url\(data:/u.test(face))) {
    throw new Error("Studio local font closure changed");
  }
  return Buffer.from(faces.join("\n"), "utf8");
}

module.exports = { BUNDLE, FONT_PATH, MOTION_NOTICE, transformStudioBundle, localFontStyles };
