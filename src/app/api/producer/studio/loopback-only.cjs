"use strict";

require("./review-only.cjs");

// Scoped to the Studio process this route starts, never the Sniper server.
// The CLI normally scans 100 ports. Refuse fallback rather than allowing its
// recorded requested port and actual listener to diverge after a bind race.
const net = require("node:net");
const originalListen = net.Server.prototype.listen;
net.Server.prototype.listen = function (...args) {
  const requested = Number(process.argv[process.argv.indexOf("--port") + 1]);
  const first = args[0];
  const port = Number(typeof first === "object" && first !== null ? first.port : first);
  if (!Number.isInteger(requested) || requested < 3990 || requested > 3999 || port !== requested) {
    throw new Error("Sniper Studio refuses a listener outside its exact assigned loopback port");
  }
  if (typeof first === "object" && first !== null) {
    args[0] = { ...first, host: "127.0.0.1" };
  } else if (typeof args[1] === "string") {
    args[1] = "127.0.0.1";
  } else {
    args.splice(1, 0, "127.0.0.1");
  }
  return Reflect.apply(originalListen, this, args);
};
