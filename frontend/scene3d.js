// Hero 3D scene: a small simulated production system (racks, gateway, databases,
// data particles) with one failing database. Loads Three.js lazily; pauses when
// off-screen; renders a single still frame for users who prefer reduced motion.
(function () {
  const host = document.getElementById("scene");
  const canvas = document.getElementById("sceneCanvas");
  if (!host || !canvas) return;
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const s = document.createElement("script");
  s.src = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
  s.async = true;
  s.onload = () => build(window.THREE);
  document.head.appendChild(s);   // if the CDN fails, the HUD panels still show over the gradient

  function glowTexture(THREE) {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const g = c.getContext("2d"), r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(.25, "rgba(255,255,255,.45)"); r.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = r; g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }

  function build(THREE) {
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x0d0907, 12, 26);
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    const base = new THREE.Vector3(0, 4.2, 11.5);
    camera.position.copy(base);

    scene.add(new THREE.AmbientLight(0xb09070, 0.55));
    const key = new THREE.PointLight(0xe3c48d, 1.1, 30); key.position.set(-4, 7, 6); scene.add(key);
    const rim = new THREE.PointLight(0xc2621d, 1.4, 30); rim.position.set(5, 4, -5); scene.add(rim);

    const grid = new THREE.GridHelper(30, 30, 0x4a3426, 0x221812);
    grid.position.y = -1.6; grid.material.transparent = true; grid.material.opacity = .55; scene.add(grid);

    const GREEN = 0x22c55e, LIME = 0xe3c48d, RED = 0xf43f5e, glow = glowTexture(THREE);
    const metal = new THREE.MeshStandardMaterial({ color: 0x2a1f18, metalness: .7, roughness: .35 });
    const nodes = {}, pulses = [];

    function halo(color, size, parent) {
      const m = new THREE.SpriteMaterial({ map: glow, color, transparent: true, opacity: .55, depthWrite: false, blending: THREE.AdditiveBlending });
      const sp = new THREE.Sprite(m); sp.scale.set(size, size, 1); parent.add(sp); return sp;
    }
    function rack(name, x, y, z, color) {
      const g = new THREE.Group();
      g.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1.8, 0.9), metal));
      const led = new THREE.MeshBasicMaterial({ color });
      for (let i = 0; i < 6; i++) {
        const l = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.05, 0.02), led);
        l.position.set(0, -0.7 + i * 0.28, 0.46); g.add(l);
      }
      halo(color, 2.6, g).position.z = -0.2;
      g.position.set(x, y, z); scene.add(g); nodes[name] = { g, color };
      return g;
    }
    function database(name, x, y, z, color) {
      const g = new THREE.Group(), mat = new THREE.MeshStandardMaterial({ color: 0x2a1f18, metalness: .6, roughness: .3,
        emissive: color, emissiveIntensity: .35 });
      for (let i = 0; i < 3; i++) {
        const c = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.62, 0.32, 40), mat);
        c.position.y = i * 0.4; g.add(c);
        const ring = new THREE.Mesh(new THREE.TorusGeometry(0.63, 0.025, 8, 48), new THREE.MeshBasicMaterial({ color }));
        ring.rotation.x = Math.PI / 2; ring.position.y = i * 0.4 + 0.16; g.add(ring);
      }
      const h = halo(color, 3.2, g); h.position.y = 0.4;
      g.position.set(x, y, z); scene.add(g); nodes[name] = { g, color, mat, halo: h };
      return g;
    }

    // gateway: a glowing core inside a slowly turning ring
    const gw = new THREE.Group();
    gw.add(new THREE.Mesh(new THREE.IcosahedronGeometry(0.55, 1),
      new THREE.MeshStandardMaterial({ color: 0x2a1f18, emissive: LIME, emissiveIntensity: .6, metalness: .5, roughness: .3, flatShading: true })));
    const ringG = new THREE.Mesh(new THREE.TorusGeometry(0.95, 0.04, 8, 64), new THREE.MeshBasicMaterial({ color: LIME }));
    ringG.rotation.x = Math.PI / 2.4; gw.add(ringG);
    halo(LIME, 3.4, gw);
    gw.position.set(0, 2.6, 0); scene.add(gw); nodes.gateway = { g: gw, color: LIME };

    rack("orders", -3.2, 0.2, 0, GREEN);
    rack("payments", 3.2, 0.2, 0, GREEN);
    rack("search", -1.7, 0.2, -2.8, GREEN);
    rack("auth", 1.7, 0.2, -2.8, GREEN);
    database("db", -1.6, -1.1, 2.4, RED);      // the failing primary
    database("cache", 1.8, -1.1, 2.4, GREEN);

    // connections + data particles travelling along them
    const edges = [["gateway", "orders"], ["gateway", "payments"], ["gateway", "search"], ["gateway", "auth"],
      ["orders", "db"], ["payments", "db"], ["orders", "cache"], ["payments", "cache"]];
    const anchor = (n) => nodes[n].g.position.clone().add(new THREE.Vector3(0, n === "db" || n === "cache" ? 0.5 : 0, 0));
    const particleGeo = new THREE.SphereGeometry(0.06, 8, 8);
    edges.forEach(([a, b]) => {
      const bad = b === "db";
      const color = bad ? RED : 0xd9a25a;
      const pts = [anchor(a), anchor(b)];
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineBasicMaterial({ color, transparent: true, opacity: bad ? .55 : .3 }));
      scene.add(line);
      for (let i = 0; i < (bad ? 2 : 3); i++) {
        const p = new THREE.Mesh(particleGeo, new THREE.MeshBasicMaterial({ color: bad ? RED : 0xf3e1b9 }));
        const h = halo(bad ? RED : LIME, .5, p); h.material.opacity = .8;
        scene.add(p);
        pulses.push({ p, a: pts[0], b: pts[1], t: i / 3, speed: bad ? .12 : .35 + Math.random() * .15 });
      }
    });

    // ambient dust
    const dust = new THREE.BufferGeometry(), N = 260, arr = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) { arr[i * 3] = (Math.random() - .5) * 18; arr[i * 3 + 1] = Math.random() * 7 - 1.5; arr[i * 3 + 2] = (Math.random() - .5) * 12; }
    dust.setAttribute("position", new THREE.BufferAttribute(arr, 3));
    const dustPts = new THREE.Points(dust, new THREE.PointsMaterial({ color: 0xc9a77a, size: .035, transparent: true, opacity: .6 }));
    scene.add(dustPts);

    function resize() {
      const w = host.clientWidth, h = host.clientHeight;
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
    }
    window.addEventListener("resize", resize); resize();

    // mouse parallax (camera and HUD panels move slightly with the pointer)
    const mouse = { x: 0, y: 0 }, huds = host.querySelectorAll(".hud");
    host.addEventListener("pointermove", (e) => {
      const r = host.getBoundingClientRect();
      mouse.x = (e.clientX - r.left) / r.width - .5; mouse.y = (e.clientY - r.top) / r.height - .5;
      if (!calm) huds.forEach((h, i) => (h.style.transform = `translate(${mouse.x * (10 + i * 6)}px, ${mouse.y * (8 + i * 4)}px)`));
    });
    host.addEventListener("pointerleave", () => { mouse.x = mouse.y = 0; huds.forEach((h) => (h.style.transform = "")); });

    let visible = true, last = performance.now(), t = 0;
    if ("IntersectionObserver" in window) new IntersectionObserver((es) => (visible = es[0].isIntersecting)).observe(host);

    function frame(now) {
      const dt = Math.min(.05, (now - last) / 1000); last = now; t += dt;
      camera.position.x += (base.x + mouse.x * 2.4 - camera.position.x) * .05;
      camera.position.y += (base.y - mouse.y * 1.4 - camera.position.y) * .05;
      camera.lookAt(0, 0.4, 0);
      gw.rotation.y += dt * .5; ringG.rotation.z += dt * .8; gw.position.y = 2.6 + Math.sin(t * 1.4) * .12;
      ["orders", "payments", "search", "auth"].forEach((n, i) => (nodes[n].g.position.y = 0.2 + Math.sin(t * 1.1 + i) * .07));
      nodes.cache.g.position.y = -1.1 + Math.sin(t * 1.3 + 2) * .1;
      const db = nodes.db, beat = (Math.sin(t * 5) + 1) / 2;          // failing node pulses red
      db.g.position.y = -1.1 + Math.sin(t * 9) * .02;
      db.mat.emissiveIntensity = .35 + beat * .65; db.halo.material.opacity = .35 + beat * .5;
      pulses.forEach((q) => { q.t = (q.t + dt * q.speed) % 1; q.p.position.lerpVectors(q.a, q.b, q.t); });
      dustPts.rotation.y += dt * .02;
      renderer.render(scene, camera);
      if (!calm) requestAnimationFrame(loop);
    }
    function loop(now) { if (visible && !document.hidden) frame(now); else { last = now; requestAnimationFrame(loop); } }
    frame(performance.now());
  }
})();
