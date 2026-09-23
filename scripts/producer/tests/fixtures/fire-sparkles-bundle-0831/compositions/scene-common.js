(function () {
  "use strict";

  window.__seededRandom = function seededRandom(initialSeed) {
    let state = (Number(initialSeed) >>> 0) || 1;
    return function nextRandom() {
      state ^= state << 13;
      state ^= state >>> 17;
      state ^= state << 5;
      return (state >>> 0) / 4294967296;
    };
  };

  function number(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function createFlames(timeline, root, vars, duration) {
    const host = root.querySelector(".fire-field");
    if (!host) return;
    const random = window.__seededRandom(vars.seed);
    const count = Math.max(10, Math.min(28, Math.round(18 * number(vars.fireIntensity, 1))));
    for (let index = 0; index < count; index += 1) {
      const flame = document.createElement("i");
      flame.className = "flame";
      const width = 58 + random() * 78;
      flame.style.left = (random() * 690 - 10) + "px";
      flame.style.width = width + "px";
      flame.style.height = (190 + random() * 260) + "px";
      host.appendChild(flame);
      gsap.set(flame, {
        opacity: 0.58 + random() * 0.4,
        scaleX: 0.72 + random() * 0.45,
        rotate: -9 + random() * 18,
      });
      timeline.fromTo(flame, {
        y: 84,
        scaleY: 0.72,
      }, {
        y: -(70 + random() * 120),
        scaleY: 1.08 + random() * 0.4,
        duration: Math.max(0.6, duration - 0.4),
        ease: "power1.inOut",
      }, 0.4 + random() * 0.25);
    }
  }

  function createSparkles(timeline, root, vars, duration) {
    const host = root.querySelector(".sparkle-field");
    if (!host) return;
    const random = window.__seededRandom((Number(vars.seed) + 1013904223) >>> 0);
    const count = Math.max(8, Math.min(40, Math.round(number(vars.sparkleCount, 22))));
    for (let index = 0; index < count; index += 1) {
      const sparkle = document.createElement("i");
      sparkle.className = "sparkle";
      const size = 9 + random() * 23;
      sparkle.style.left = (34 + random() * 680) + "px";
      sparkle.style.top = (34 + random() * 620) + "px";
      sparkle.style.width = size + "px";
      sparkle.style.height = size + "px";
      host.appendChild(sparkle);
      timeline.fromTo(sparkle, {
        opacity: 0,
        scale: 0.2,
        rotate: -30 + random() * 60,
      }, {
        opacity: 0.55 + random() * 0.45,
        scale: 0.8 + random() * 0.75,
        rotate: 120 + random() * 200,
        duration: Math.max(0.6, duration - 0.6),
        ease: "power1.inOut",
      }, 0.6 + random() * 0.3);
    }
  }

  window.__buildFireSparkles = function buildFireSparkles(timeline, root, vars, duration) {
    root.style.setProperty("--left-color", String(vars.leftColor));
    const left = root.querySelector(".card-left");
    const right = root.querySelector(".card-right");
    if (left) {
      left.querySelector(".label").textContent = String(vars.leftTitle);
      timeline.fromTo(left, {
        autoAlpha: 0,
        x: -70,
        scale: 0.94,
      }, {
        autoAlpha: 1,
        x: 0,
        scale: 1,
        duration: 0.6,
        ease: "power3.out",
      }, 0);
      createFlames(timeline, root, vars, duration);
    }
    if (right) {
      right.querySelector(".label").textContent = String(vars.rightTitle);
      timeline.fromTo(right, {
        autoAlpha: 0,
        x: 70,
        scale: 0.94,
      }, {
        autoAlpha: 1,
        x: 0,
        scale: 1,
        duration: 0.6,
        ease: "power3.out",
      }, 0.2);
      createSparkles(timeline, root, vars, duration);
    }
    timeline.to({}, { duration: Math.max(0, duration - 0.1) }, 0);
  };
})();
