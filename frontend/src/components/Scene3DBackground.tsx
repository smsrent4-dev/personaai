import { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * Ambient animated 3D background: a slowly rotating network of nodes
 * connected by lines — procedurally generated (no .glb/.gltf asset was
 * ever supplied to bundle, and this sandbox has no network to fetch
 * one from a CDN). Pure three.js, not react-three-fiber.
 *
 * CONFIRMED BROKEN, then fixed: the first version crashed the entire
 * Login page in a real browser with "WebGL: context lost" /
 * "gl.getShaderPrecisionFormat(...).precision" is null, thrown inside
 * <Scene3DBackground> with no error boundary above it to stop the
 * crash from taking the whole page down. Root cause: React's
 * <StrictMode> (enabled in main.tsx) double-invokes effects in dev —
 * mount, cleanup, mount again — so two WebGLRenderer instances got
 * created back-to-back. The first render's GL context wasn't being
 * proactively released on cleanup (just `.dispose()`, which doesn't
 * synchronously guarantee the browser/GPU frees the underlying
 * context), so the second mount's context creation raced or tripped
 * the browser's per-page WebGL context limit, and Three.js's own
 * internal shader-precision probe — which doesn't null-check its own
 * result — threw on the lost context.
 *
 * Fixed with defense in depth, not just the StrictMode case, since
 * "the GPU/browser refuses a context" can also legitimately happen on
 * real low-end devices or exhausted VMs, not only in dev:
 *   1. Feature-detect WebGL before ever constructing a THREE.WebGLRenderer.
 *   2. The whole setup + animation loop is wrapped in try/catch — nothing
 *      in here can throw up into React and take the page down; worst
 *      case, the background silently doesn't render.
 *   3. webglcontextlost/restored listeners: pause the render loop while
 *      lost (rather than repeatedly hitting a dead context every frame)
 *      and resume automatically if the browser restores it.
 *   4. Cleanup calls `renderer.forceContextLoss()` before `.dispose()` —
 *      the actual fix for the StrictMode double-mount race: this
 *      synchronously and proactively releases the GL context instead of
 *      leaving its release to GC/driver timing.
 *
 * Also wrapped in a small local ErrorBoundary at the JSX call sites
 * (LoginPage/RegisterPage) as a second, independent layer — if
 * anything about this component ever misbehaves in a way not covered
 * above, a decorative background must never be able to break the
 * ability to log in.
 */
export default function Scene3DBackground() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    if (!isWebGLAvailable()) {
      return;
    }

    let frameId: number | null = null;
    let disposed = false;
    let contextLost = false;

    let renderer: THREE.WebGLRenderer | null = null;
    let pointsGeometry: THREE.BufferGeometry | null = null;
    let pointsMaterial: THREE.PointsMaterial | null = null;
    let lineGeometry: THREE.BufferGeometry | null = null;
    let lineMaterial: THREE.LineBasicMaterial | null = null;

    function handleContextLost(event: Event) {
      event.preventDefault(); // required by the WebGL spec to allow restoration
      contextLost = true;
    }
    function handleContextRestored() {
      contextLost = false;
    }

    try {
      const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(55, container.clientWidth / container.clientHeight, 0.1, 100);
      camera.position.z = 13;

      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setSize(container.clientWidth, container.clientHeight);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.domElement.addEventListener("webglcontextlost", handleContextLost, false);
      renderer.domElement.addEventListener("webglcontextrestored", handleContextRestored, false);
      container.appendChild(renderer.domElement);

      // --- Node network: N random points inside a sphere, connected to
      // their nearest few neighbors within a distance threshold.
      const NODE_COUNT = 90;
      const RADIUS = 8;
      const positions = new Float32Array(NODE_COUNT * 3);
      for (let i = 0; i < NODE_COUNT; i++) {
        const direction = new THREE.Vector3(
          Math.random() - 0.5,
          Math.random() - 0.5,
          Math.random() - 0.5
        ).normalize();
        const r = RADIUS * Math.cbrt(Math.random());
        positions.set([direction.x * r, direction.y * r, direction.z * r], i * 3);
      }

      pointsGeometry = new THREE.BufferGeometry();
      pointsGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      pointsMaterial = new THREE.PointsMaterial({
        color: 0x8b5cf6,
        size: 0.09,
        transparent: true,
        opacity: 0.85,
        sizeAttenuation: true,
      });
      const points = new THREE.Points(pointsGeometry, pointsMaterial);

      const linePositions: number[] = [];
      const MAX_LINK_DISTANCE = 2.6;
      for (let i = 0; i < NODE_COUNT; i++) {
        const ax = positions[i * 3];
        const ay = positions[i * 3 + 1];
        const az = positions[i * 3 + 2];
        for (let j = i + 1; j < NODE_COUNT; j++) {
          const bx = positions[j * 3];
          const by = positions[j * 3 + 1];
          const bz = positions[j * 3 + 2];
          const dist = Math.hypot(ax - bx, ay - by, az - bz);
          if (dist < MAX_LINK_DISTANCE) {
            linePositions.push(ax, ay, az, bx, by, bz);
          }
        }
      }
      lineGeometry = new THREE.BufferGeometry();
      lineGeometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(linePositions), 3));
      lineMaterial = new THREE.LineBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: 0.15 });
      const lines = new THREE.LineSegments(lineGeometry, lineMaterial);

      const group = new THREE.Group();
      group.add(points, lines);
      scene.add(group);

      let elapsed = 0;
      const clock = new THREE.Clock();

      function animate() {
        if (disposed) return;
        frameId = requestAnimationFrame(animate);
        if (contextLost || !renderer) return; // don't touch a dead context every frame
        try {
          if (!prefersReducedMotion) {
            elapsed += clock.getDelta();
            group.rotation.y = elapsed * 0.06;
            group.rotation.x = Math.sin(elapsed * 0.05) * 0.15;
          }
          renderer.render(scene, camera);
        } catch {
          // A render-time failure (e.g. context lost between the check
          // above and this call) stops the loop rather than spamming
          // errors every frame — see module docstring point 2.
          disposed = true;
          if (frameId !== null) cancelAnimationFrame(frameId);
        }
      }
      animate();

      function handleResize() {
        if (!container || !renderer) return;
        camera.aspect = container.clientWidth / container.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(container.clientWidth, container.clientHeight);
      }
      window.addEventListener("resize", handleResize);

      return () => {
        disposed = true;
        window.removeEventListener("resize", handleResize);
        if (frameId !== null) cancelAnimationFrame(frameId);

        pointsGeometry?.dispose();
        pointsMaterial?.dispose();
        lineGeometry?.dispose();
        lineMaterial?.dispose();

        if (renderer) {
          renderer.domElement.removeEventListener("webglcontextlost", handleContextLost);
          renderer.domElement.removeEventListener("webglcontextrestored", handleContextRestored);
          // Proactively release the GL context instead of leaving it to
          // GC/driver timing — the actual fix for the StrictMode
          // double-mount race described in the module docstring.
          renderer.forceContextLoss();
          renderer.dispose();
          if (renderer.domElement.parentElement === container) {
            container.removeChild(renderer.domElement);
          }
        }
      };
    } catch {
      // Setup itself failed (no usable WebGL despite the feature-detect
      // above, an out-of-memory context, etc.) — clean up whatever
      // partially got created and give up quietly. A decorative
      // background failing to render is never worth surfacing as an
      // error on a login page.
      if (renderer) {
        try {
          renderer.forceContextLoss();
          renderer.dispose();
        } catch {
          /* already broken; nothing more to do */
        }
      }
      return undefined;
    }
  }, []);

  return (
    <div
      ref={containerRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 -z-10 opacity-70"
      style={{
        maskImage: "radial-gradient(ellipse at center, black 40%, transparent 75%)",
        WebkitMaskImage: "radial-gradient(ellipse at center, black 40%, transparent 75%)",
      }}
    />
  );
}

function isWebGLAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}
