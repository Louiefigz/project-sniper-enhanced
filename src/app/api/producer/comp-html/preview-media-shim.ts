import type { MediaMap } from "./preview-media";

// The audited templates use img.src and one synchronous SVG XHR (stroke-draw).
// This adapter resolves only exact, prevalidated resources embedded by the server.
// It never fetches from the parent, rewrites variables, or relaxes frame security.
const MEDIA_SHIM = String.raw`
(function (resources) {
  function resolve(value) {
    var key = String(value);
    if (Object.prototype.hasOwnProperty.call(resources, key)) return resources[key].data;
    if (/^\/?(?:icons|assets)\//.test(key)) {
      throw new Error("Preview asset was not embedded: " + key);
    }
    return value;
  }
  var imageSrc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src");
  if (!imageSrc || !imageSrc.set || !imageSrc.get) throw new Error("Preview image adapter unavailable");
  Object.defineProperty(HTMLImageElement.prototype, "src", {
    configurable: imageSrc.configurable,
    enumerable: imageSrc.enumerable,
    get: imageSrc.get,
    set: function (value) { imageSrc.set.call(this, resolve(value)); }
  });
  var open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function () {
    var args = Array.prototype.slice.call(arguments);
    var key = String(args[1]);
    if (Object.prototype.hasOwnProperty.call(resources, key)) {
      if (String(args[0]).toUpperCase() !== "GET") throw new Error("Embedded preview assets are read-only");
      args[1] = resources[key].data;
    } else if (/^\/?(?:icons|assets)\//.test(key)) {
      throw new Error("Preview asset was not embedded: " + key);
    }
    return open.apply(this, args);
  };
})(__SNIPER_EMBEDDED_MEDIA__);
`;

/** Inject before template scripts, after the parent's error/health listener. */
export function mediaShim(map: MediaMap): string {
  if (!Object.keys(map).length) return "";
  const json = JSON.stringify(map).replace(/</gu, "\\u003c");
  return `<script data-sniper-preview-media>${MEDIA_SHIM.replace("__SNIPER_EMBEDDED_MEDIA__", json)}</script>`;
}
