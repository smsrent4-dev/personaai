import { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * PersonaAI — Procedural 3D Agent Background
 *
 * Four autonomous AI agents:
 *   • Personal
 *   • Sales
 *   • Support
 *   • Opportunity
 *
 * Features:
 *   - Pure Three.js
 *   - No external 3D assets
 *   - No GLB/GLTF downloads
 *   - Procedurally generated humanoid AI agents
 *   - Floating / breathing / rotating animation
 *   - Glowing chest cores
 *   - Orbital rings
 *   - Neural connection lines
 *   - Ambient particles
 *   - Responsive camera
 *   - prefers-reduced-motion support
 *   - WebGL feature detection
 *   - WebGL context-loss protection
 *   - StrictMode-safe cleanup
 *   - Renderer.forceContextLoss()
 *
 * IMPORTANT:
 * This is intentionally a stylized futuristic 3D scene rather than
 * photorealistic human models. Realistic humanoid characters would
 * require external GLB/GLTF assets or a much heavier character system.
 */

type AgentConfig = {
  name: string;
  position: THREE.Vector3;
  scale: number;
  phase: number;
  orbitRadius: number;
  color: number;
};

type AgentRuntime = {
  root: THREE.Group;
  body: THREE.Group;
  head: THREE.Group;
  core: THREE.Mesh;
  coreLight: THREE.PointLight;
  rings: THREE.Group;
  particles: THREE.Points;
  baseY: number;
  phase: number;
  orbitRadius: number;
};

const AGENTS: AgentConfig[] = [
  {
    name: "Personal",
    position: new THREE.Vector3(-5.4, 2.2, 0.2),
    scale: 1.0,
    phase: 0,
    orbitRadius: 0.12,
    color: 0x8b5cf6,
  },
  {
    name: "Sales",
    position: new THREE.Vector3(5.1, 2.6, -0.4),
    scale: 0.95,
    phase: 2.1,
    orbitRadius: 0.16,
    color: 0x3b82f6,
  },
  {
    name: "Support",
    position: new THREE.Vector3(-5.0, -2.8, -0.2),
    scale: 0.92,
    phase: 4.0,
    orbitRadius: 0.14,
    color: 0x22c55e,
  },
  {
    name: "Opportunity",
    position: new THREE.Vector3(5.0, -2.6, 0.4),
    scale: 0.92,
    phase: 5.3,
    orbitRadius: 0.18,
    color: 0xf59e0b,
  },
];

export default function Scene3DBackground() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;

    if (!container) {
      return;
    }

    if (!isWebGLAvailable()) {
      return;
    }

    let renderer: THREE.WebGLRenderer | null = null;

    let frameId: number | null = null;

    let disposed = false;
    let contextLost = false;

    const cleanupCallbacks: Array<() => void> = [];

    try {
      const prefersReducedMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;

      const width = Math.max(container.clientWidth, 1);
      const height = Math.max(container.clientHeight, 1);

      // ------------------------------------------------------------
      // Scene
      // ------------------------------------------------------------

      const scene = new THREE.Scene();

      scene.fog = new THREE.FogExp2(0x050507, 0.025);

      // ------------------------------------------------------------
      // Camera
      // ------------------------------------------------------------

      const camera = new THREE.PerspectiveCamera(
        48,
        width / height,
        0.1,
        100,
      );

      camera.position.set(0, 0, 15);

      // ------------------------------------------------------------
      // Renderer
      // ------------------------------------------------------------

      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
        depth: true,
        stencil: false,
      });

      renderer.setSize(width, height);

      renderer.setPixelRatio(
        Math.min(window.devicePixelRatio || 1, 1.75),
      );

      renderer.setClearColor(0x000000, 0);

      renderer.domElement.style.display = "block";
      renderer.domElement.style.width = "100%";
      renderer.domElement.style.height = "100%";

      renderer.domElement.setAttribute(
        "aria-hidden",
        "true",
      );

      container.appendChild(renderer.domElement);

      // ------------------------------------------------------------
      // WebGL context protection
      // ------------------------------------------------------------

      const handleContextLost = (event: Event) => {
        event.preventDefault();

        contextLost = true;
      };

      const handleContextRestored = () => {
        if (!disposed) {
          contextLost = false;
        }
      };

      renderer.domElement.addEventListener(
        "webglcontextlost",
        handleContextLost,
        false,
      );

      renderer.domElement.addEventListener(
        "webglcontextrestored",
        handleContextRestored,
        false,
      );

      cleanupCallbacks.push(() => {
        renderer?.domElement.removeEventListener(
          "webglcontextlost",
          handleContextLost,
        );

        renderer?.domElement.removeEventListener(
          "webglcontextrestored",
          handleContextRestored,
        );
      });

      // ------------------------------------------------------------
      // Lighting
      // ------------------------------------------------------------

      const ambientLight = new THREE.AmbientLight(
        0x6b7280,
        0.65,
      );

      scene.add(ambientLight);

      const keyLight = new THREE.PointLight(
        0x8b5cf6,
        8,
        22,
        2,
      );

      keyLight.position.set(0, 1, 5);

      scene.add(keyLight);

      const blueLight = new THREE.PointLight(
        0x3b82f6,
        5,
        18,
        2,
      );

      blueLight.position.set(6, 2, 2);

      scene.add(blueLight);

      const violetLight = new THREE.PointLight(
        0x8b5cf6,
        4,
        18,
        2,
      );

      violetLight.position.set(-6, -1, 2);

      scene.add(violetLight);

      // ------------------------------------------------------------
      // Central AI Core
      // ------------------------------------------------------------

      const centralSystem = createCentralAI();

      scene.add(centralSystem.group);

      // ------------------------------------------------------------
      // Neural network connections
      // ------------------------------------------------------------

      const connectionGroup = createConnections();

      scene.add(connectionGroup);

      // ------------------------------------------------------------
      // Agents
      // ------------------------------------------------------------

      const agents: AgentRuntime[] = [];

      for (const config of AGENTS) {
        const agent = createAgent(config);

        agents.push(agent);

        scene.add(agent.root);
      }

      // ------------------------------------------------------------
      // Ambient particles
      // ------------------------------------------------------------

      const particleSystem = createAmbientParticles();

      scene.add(particleSystem);

      // ------------------------------------------------------------
      // Floor / subtle grid
      // ------------------------------------------------------------

      const grid = createEnvironmentGrid();

      scene.add(grid);

      // ------------------------------------------------------------
      // Clock
      // ------------------------------------------------------------

      const clock = new THREE.Clock();

      let elapsed = 0;

      // ------------------------------------------------------------
      // Animation
      // ------------------------------------------------------------

      const animate = () => {
        if (disposed) {
          return;
        }

        frameId = window.requestAnimationFrame(animate);

        if (contextLost || !renderer) {
          return;
        }

        try {
          const delta = Math.min(
            clock.getDelta(),
            0.05,
          );

          elapsed += delta;

          if (!prefersReducedMotion) {
            // ------------------------------------------------------
            // Central AI core
            // ------------------------------------------------------

            centralSystem.group.rotation.y =
              elapsed * 0.18;

            centralSystem.group.rotation.x =
              Math.sin(elapsed * 0.35) * 0.05;

            const corePulse =
              1 +
              Math.sin(elapsed * 2.1) * 0.06;

            centralSystem.core.scale.setScalar(
              corePulse,
            );

            centralSystem.coreLight.intensity =
              5 +
              Math.sin(elapsed * 2.1) * 1.4;

            // ------------------------------------------------------
            // Agents
            // ------------------------------------------------------

            agents.forEach((agent, index) => {
              const phase = agent.phase;

              const float =
                Math.sin(
                  elapsed * 0.75 + phase,
                ) * 0.28;

              const secondaryFloat =
                Math.sin(
                  elapsed * 1.1 + phase * 1.7,
                ) * 0.08;

              agent.root.position.y =
                agent.baseY +
                float;

              agent.root.position.x +=
                Math.sin(
                  elapsed * 0.22 + phase,
                ) *
                0.0015;

              agent.root.rotation.y =
                Math.sin(
                  elapsed * 0.45 + phase,
                ) *
                0.12;

              agent.root.rotation.z =
                Math.sin(
                  elapsed * 0.55 + phase,
                ) *
                0.025;

              // Gentle body breathing
              const breathing =
                1 +
                Math.sin(
                  elapsed * 1.2 + phase,
                ) *
                  0.018;

              agent.body.scale.y = breathing;

              // Head movement
              agent.head.rotation.y =
                Math.sin(
                  elapsed * 0.5 + phase,
                ) *
                0.12;

              agent.head.rotation.x =
                Math.sin(
                  elapsed * 0.7 + phase,
                ) *
                0.04;

              // Chest AI core
              const pulse =
                1 +
                Math.sin(
                  elapsed * 2.5 + phase,
                ) *
                  0.16;

              agent.core.scale.setScalar(
                pulse,
              );

              agent.coreLight.intensity =
                1.8 +
                Math.sin(
                  elapsed * 2.5 + phase,
                ) *
                  0.7;

              // Orbiting rings
              agent.rings.rotation.z =
                elapsed *
                  (index % 2 === 0
                    ? 0.4
                    : -0.35);

              agent.rings.rotation.x =
                Math.sin(
                  elapsed * 0.35 + phase,
                ) *
                0.25;

              // Tiny particle motion
              agent.particles.rotation.y =
                elapsed * 0.12;

              agent.particles.rotation.x =
                elapsed * 0.06;

              // Slight orbital movement
              if (agent.orbitRadius > 0) {
                agent.root.position.z =
                  Math.sin(
                    elapsed * 0.28 + phase,
                  ) *
                  agent.orbitRadius;
              }

              // Avoid unused animation drift
              agent.root.position.y +=
                secondaryFloat * 0.15;
            });

            // ------------------------------------------------------
            // Connections
            // ------------------------------------------------------

            connectionGroup.rotation.y =
              Math.sin(elapsed * 0.12) *
              0.05;

            connectionGroup.rotation.x =
              Math.sin(elapsed * 0.09) *
              0.025;

            // ------------------------------------------------------
            // Particles
            // ------------------------------------------------------

            particleSystem.rotation.y =
              elapsed * 0.025;

            particleSystem.rotation.x =
              Math.sin(elapsed * 0.06) *
              0.05;

            // ------------------------------------------------------
            // Camera breathing
            // ------------------------------------------------------

            camera.position.x =
              Math.sin(elapsed * 0.08) *
              0.18;

            camera.position.y =
              Math.cos(elapsed * 0.07) *
              0.12;

            camera.lookAt(0, 0, 0);
          }

          renderer.render(
            scene,
            camera,
          );
        } catch {
          // Rendering must NEVER be allowed to crash
          // the authentication page.

          disposed = true;

          if (frameId !== null) {
            window.cancelAnimationFrame(
              frameId,
            );

            frameId = null;
          }
        }
      };

      animate();

      // ------------------------------------------------------------
      // Resize
      // ------------------------------------------------------------

      const handleResize = () => {
        if (
          disposed ||
          !renderer ||
          !container
        ) {
          return;
        }

        try {
          const nextWidth = Math.max(
            container.clientWidth,
            1,
          );

          const nextHeight = Math.max(
            container.clientHeight,
            1,
          );

          camera.aspect =
            nextWidth / nextHeight;

          camera.updateProjectionMatrix();

          renderer.setSize(
            nextWidth,
            nextHeight,
            false,
          );

          renderer.setPixelRatio(
            Math.min(
              window.devicePixelRatio || 1,
              1.75,
            ),
          );
        } catch {
          // Decorative background only.
        }
      };

      window.addEventListener(
        "resize",
        handleResize,
        { passive: true },
      );

      cleanupCallbacks.push(() => {
        window.removeEventListener(
          "resize",
          handleResize,
        );
      });

      // ------------------------------------------------------------
      // Cleanup
      // ------------------------------------------------------------

      return () => {
        disposed = true;

        if (frameId !== null) {
          window.cancelAnimationFrame(
            frameId,
          );

          frameId = null;
        }

        cleanupCallbacks.forEach(
          (callback) => {
            try {
              callback();
            } catch {
              // Ignore cleanup failures.
            }
          },
        );

        disposeObject3D(scene);

        if (renderer) {
          try {
            renderer.forceContextLoss();
          } catch {
            // Context may already be lost.
          }

          try {
            renderer.dispose();
          } catch {
            // Renderer may already be disposed.
          }

          const canvas =
            renderer.domElement;

          if (
            canvas.parentElement ===
            container
          ) {
            try {
              container.removeChild(
                canvas,
              );
            } catch {
              // Already removed.
            }
          }

          renderer = null;
        }
      };
    } catch {
      // ------------------------------------------------------------
      // Defensive setup failure handling
      // ------------------------------------------------------------

      disposed = true;

      if (frameId !== null) {
        window.cancelAnimationFrame(
          frameId,
        );
      }

      cleanupCallbacks.forEach(
        (callback) => {
          try {
            callback();
          } catch {
            // Ignore.
          }
        },
      );

      if (renderer) {
        try {
          disposeObject3D(
            renderer.scene ?? new THREE.Scene(),
          );
        } catch {
          // Not available / already broken.
        }

        try {
          renderer.forceContextLoss();
        } catch {
          // Already lost.
        }

        try {
          renderer.dispose();
        } catch {
          // Already disposed.
        }

        if (
          renderer.domElement.parentElement ===
          container
        ) {
          try {
            container.removeChild(
              renderer.domElement,
            );
          } catch {
            // Already removed.
          }
        }

        renderer = null;
      }

      // A decorative background should silently
      // disappear if WebGL initialization fails.
      return undefined;
    }
  }, []);

  return (
    <div
      ref={containerRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
      style={{
        opacity: 0.78,
        maskImage:
          "radial-gradient(ellipse at center, black 32%, rgba(0,0,0,.92) 58%, transparent 88%)",
        WebkitMaskImage:
          "radial-gradient(ellipse at center, black 32%, rgba(0,0,0,.92) 58%, transparent 88%)",
      }}
    >
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(circle at center, rgba(124,58,237,.07), transparent 38%), radial-gradient(circle at 50% 50%, rgba(37,99,235,.045), transparent 55%)",
        }}
      />
    </div>
  );
}

/* ================================================================
   AGENT CREATION
   ================================================================ */

function createAgent(
  config: AgentConfig,
): AgentRuntime {
  const root = new THREE.Group();

  root.position.copy(
    config.position,
  );

  root.scale.setScalar(
    config.scale,
  );

  const body = new THREE.Group();

  root.add(body);

  // --------------------------------------------------------------
  // Materials
  // --------------------------------------------------------------

  const bodyMaterial =
    new THREE.MeshStandardMaterial({
      color: 0x11131a,
      metalness: 0.72,
      roughness: 0.28,
      transparent: true,
      opacity: 0.94,
    });

  const darkMaterial =
    new THREE.MeshStandardMaterial({
      color: 0x08090d,
      metalness: 0.82,
      roughness: 0.22,
    });

  const glassMaterial =
    new THREE.MeshPhysicalMaterial({
      color: 0x1a1b25,
      metalness: 0.15,
      roughness: 0.18,
      transmission: 0.18,
      transparent: true,
      opacity: 0.78,
      clearcoat: 0.8,
      clearcoatRoughness: 0.18,
    });

  const glowMaterial =
    new THREE.MeshBasicMaterial({
      color: config.color,
      transparent: true,
      opacity: 0.95,
    });

  // --------------------------------------------------------------
  // Torso
  // --------------------------------------------------------------

  const torsoGeometry =
    new THREE.SphereGeometry(
      1,
      20,
      16,
    );

  torsoGeometry.scale(
    0.92,
    1.2,
    0.55,
  );

  const torso = new THREE.Mesh(
    torsoGeometry,
    bodyMaterial,
  );

  torso.position.y = -0.65;

  body.add(torso);

  // Inner chest plate
  const chestGeometry =
    new THREE.SphereGeometry(
      0.65,
      20,
      12,
    );

  chestGeometry.scale(
    0.85,
    1.05,
    0.28,
  );

  const chest =
    new THREE.Mesh(
      chestGeometry,
      glassMaterial,
    );

  chest.position.set(
    0,
    -0.52,
    0.38,
  );

  body.add(chest);

  // --------------------------------------------------------------
  // Chest AI core
  // --------------------------------------------------------------

  const coreGeometry =
    new THREE.IcosahedronGeometry(
      0.19,
      1,
    );

  const core =
    new THREE.Mesh(
      coreGeometry,
      glowMaterial,
    );

  core.position.set(
    0,
    -0.48,
    0.72,
  );

  body.add(core);

  const coreLight =
    new THREE.PointLight(
      config.color,
      2.2,
      3.5,
           2,
    );

  coreLight.position.copy(
    core.position,
  );

  body.add(coreLight);

  // --------------------------------------------------------------
  // Neck
  // --------------------------------------------------------------

  const neckGeometry =
    new THREE.CylinderGeometry(
      0.22,
      0.25,
      0.35,
      12,
    );

  const neck =
    new THREE.Mesh(
      neckGeometry,
      darkMaterial,
    );

  neck.position.y = 0.15;

  body.add(neck);

  // --------------------------------------------------------------
  // Head
  // --------------------------------------------------------------

  const head = new THREE.Group();

  head.position.set(
    0,
    0.72,
    0,
  );

  body.add(head);

  const headGeometry =
    new THREE.SphereGeometry(
      0.62,
      24,
      20,
    );

  headGeometry.scale(
    0.86,
    1,
    0.82,
  );

  const headMesh =
    new THREE.Mesh(
      headGeometry,
      glassMaterial,
    );

  head.add(headMesh);

  // --------------------------------------------------------------
  // Face visor
  // --------------------------------------------------------------

  const visorGeometry =
    new THREE.SphereGeometry(
      0.38,
      20,
      12,
      0,
      Math.PI * 2,
      0.25,
      0.48,
    );

  visorGeometry.scale(
    1.25,
    0.55,
    0.22,
  );

  const visorMaterial =
    new THREE.MeshBasicMaterial({
      color: 0x090a0f,
      transparent: true,
      opacity: 0.94,
    });

  const visor =
    new THREE.Mesh(
      visorGeometry,
      visorMaterial,
    );

  visor.position.set(
    0,
    0.02,
    0.52,
  );

  head.add(visor);

  // --------------------------------------------------------------
  // Eyes
  // --------------------------------------------------------------

  const eyeGeometry =
    new THREE.SphereGeometry(
      0.055,
      10,
      8,
    );

  const eyeMaterial =
    new THREE.MeshBasicMaterial({
      color: config.color,
    });

  const leftEye =
    new THREE.Mesh(
      eyeGeometry,
      eyeMaterial,
    );

  const rightEye =
    new THREE.Mesh(
      eyeGeometry,
      eyeMaterial,
    );

  leftEye.position.set(
    -0.16,
    0.05,
    0.57,
  );

  rightEye.position.set(
    0.16,
    0.05,
    0.57,
  );

  head.add(leftEye);
  head.add(rightEye);

  // Eye glow
  const eyeLight =
    new THREE.PointLight(
      config.color,
      0.8,
      1.8,
      2,
    );

  eyeLight.position.set(
    0,
    0.05,
    0.62,
  );

  head.add(eyeLight);

  // --------------------------------------------------------------
  // Head crown
  // --------------------------------------------------------------

  const crownGeometry =
    new THREE.TorusGeometry(
      0.28,
      0.025,
      6,
      24,
    );

  const crown =
    new THREE.Mesh(
      crownGeometry,
      glowMaterial,
    );

  crown.rotation.x =
    Math.PI / 2;

  crown.position.y =
    0.58;

  head.add(crown);

  // --------------------------------------------------------------
  // Shoulders
  // --------------------------------------------------------------

  const shoulderGeometry =
    new THREE.SphereGeometry(
      0.4,
      16,
      12,
    );

  shoulderGeometry.scale(
    1.35,
    0.65,
    0.72,
  );

  const leftShoulder =
    new THREE.Mesh(
      shoulderGeometry,
      darkMaterial,
    );

  const rightShoulder =
    new THREE.Mesh(
      shoulderGeometry,
      darkMaterial,
    );

  leftShoulder.position.set(
    -0.78,
    -0.38,
    0,
  );

  rightShoulder.position.set(
    0.78,
    -0.38,
    0,
  );

  body.add(leftShoulder);
  body.add(rightShoulder);

  // --------------------------------------------------------------
  // Arms
  // --------------------------------------------------------------

  const armGeometry =
    new THREE.CapsuleGeometry(
      0.16,
      0.72,
      6,
      12,
    );

  const leftArm =
    new THREE.Mesh(
      armGeometry,
      bodyMaterial,
    );

  const rightArm =
    new THREE.Mesh(
      armGeometry,
      bodyMaterial,
    );

  leftArm.position.set(
    -0.98,
    -0.9,
    0,
  );

  rightArm.position.set(
    0.98,
    -0.9,
    0,
  );

  leftArm.rotation.z =
    -0.18;

  rightArm.rotation.z =
    0.18;

  body.add(leftArm);
  body.add(rightArm);

  // --------------------------------------------------------------
  // Hands
  // --------------------------------------------------------------

  const handGeometry =
    new THREE.SphereGeometry(
      0.19,
      12,
      10,
    );

  const leftHand =
    new THREE.Mesh(
      handGeometry,
      glassMaterial,
    );

  const rightHand =
    new THREE.Mesh(
      handGeometry,
      glassMaterial,
    );

  leftHand.position.set(
    -1.06,
    -1.35,
    0,
  );

  rightHand.position.set(
    1.06,
    -1.35,
    0,
  );

  body.add(leftHand);
  body.add(rightHand);

  // --------------------------------------------------------------
  // Waist
  // --------------------------------------------------------------

  const waistGeometry =
    new THREE.CylinderGeometry(
      0.42,
      0.52,
      0.38,
      16,
    );

  const waist =
    new THREE.Mesh(
      waistGeometry,
      darkMaterial,
    );

  waist.position.y =
    -1.55;

  body.add(waist);

  // --------------------------------------------------------------
  // Legs
  // --------------------------------------------------------------

  const legGeometry =
    new THREE.CapsuleGeometry(
      0.22,
      0.82,
      6,
      12,
    );

  const leftLeg =
    new THREE.Mesh(
      legGeometry,
      bodyMaterial,
    );

  const rightLeg =
    new THREE.Mesh(
      legGeometry,
      bodyMaterial,
    );

  leftLeg.position.set(
    -0.32,
    -2.12,
    0,
  );

  rightLeg.position.set(
    0.32,
    -2.12,
    0,
  );

  body.add(leftLeg);
  body.add(rightLeg);

  // --------------------------------------------------------------
  // Feet
  // --------------------------------------------------------------

  const footGeometry =
    new THREE.SphereGeometry(
      0.28,
      12,
      8,
    );

  footGeometry.scale(
    1.35,
    0.45,
    1.65,
  );

  const leftFoot =
    new THREE.Mesh(
      footGeometry,
      darkMaterial,
    );

  const rightFoot =
    new THREE.Mesh(
      footGeometry,
      darkMaterial,
    );

  leftFoot.position.set(
    -0.32,
    -2.78,
    0.14,
  );

  rightFoot.position.set(
    0.32,
    -2.78,
    0.14,
  );

  body.add(leftFoot);
  body.add(rightFoot);

  // --------------------------------------------------------------
  // Agent platform
  // --------------------------------------------------------------

  const platformGeometry =
    new THREE.CylinderGeometry(
      1.25,
      1.45,
      0.12,
      48,
    );

  const platformMaterial =
    new THREE.MeshStandardMaterial({
      color: 0x090a0f,
      metalness: 0.85,
      roughness: 0.24,
      transparent: true,
      opacity: 0.85,
    });

  const platform =
    new THREE.Mesh(
      platformGeometry,
      platformMaterial,
    );

  platform.position.y =
    -2.98;

  root.add(platform);

  // Platform glow ring
  const platformRingGeometry =
    new THREE.TorusGeometry(
      1.05,
      0.025,
      6,
      48,
    );

  const platformRing =
    new THREE.Mesh(
      platformRingGeometry,
      glowMaterial,
    );

  platformRing.rotation.x =
    Math.PI / 2;

  platformRing.position.y =
    -2.91;

  root.add(platformRing);

  // --------------------------------------------------------------
  // Orbit rings around agent
  // --------------------------------------------------------------

  const rings =
    new THREE.Group();

  const ringMaterial =
    new THREE.MeshBasicMaterial({
      color: config.color,
      transparent: true,
      opacity: 0.28,
    });

  const ring1 =
    new THREE.Mesh(
      new THREE.TorusGeometry(
        1.55,
        0.018,
        6,
        64,
      ),
      ringMaterial,
    );

  const ring2 =
    new THREE.Mesh(
      new THREE.TorusGeometry(
        1.75,
        0.012,
        6,
        64,
      ),
      ringMaterial,
    );

  ring1.rotation.x =
    Math.PI / 2;

  ring2.rotation.y =
    Math.PI / 3;

  ring2.rotation.x =
    Math.PI / 2.8;

  rings.add(ring1);
  rings.add(ring2);

  rings.position.y =
    -0.55;

  root.add(rings);

  // --------------------------------------------------------------
  // Small orbit particles
  // --------------------------------------------------------------

  const particleCount = 16;

  const particlePositions =
    new Float32Array(
      particleCount * 3,
    );

  for (
    let i = 0;
    i < particleCount;
    i++
  ) {
    const angle =
      (i / particleCount) *
      Math.PI *
      2;

    const radius =
      1.5 +
      Math.random() * 0.55;

    particlePositions[i * 3] =
      Math.cos(angle) * radius;

    particlePositions[
      i * 3 + 1
    ] =
      (Math.random() - 0.5) *
      0.8;

    particlePositions[
      i * 3 + 2
    ] =
      Math.sin(angle) * radius;
  }

  const particleGeometry =
    new THREE.BufferGeometry();

  particleGeometry.setAttribute(
    "position",
    new THREE.BufferAttribute(
      particlePositions,
      3,
    ),
  );

  const particleMaterial =
    new THREE.PointsMaterial({
      color: config.color,
      size: 0.035,
      transparent: true,
      opacity: 0.65,
      sizeAttenuation: true,
    });

  const particles =
    new THREE.Points(
      particleGeometry,
      particleMaterial,
    );

  particles.position.y =
    -0.55;

  root.add(particles);

  return {
    root,
    body,
    head,
    core,
    coreLight,
    rings,
    particles,
    baseY: config.position.y,
    phase: config.phase,
    orbitRadius: config.orbitRadius,
  };
}

/* ================================================================
   CENTRAL AI SYSTEM
   ================================================================ */

function createCentralAI() {
  const group =
    new THREE.Group();

  // --------------------------------------------------------------
  // Main core
  // --------------------------------------------------------------

  const coreGeometry =
    new THREE.IcosahedronGeometry(
      0.85,
      2,
    );

  const coreMaterial =
    new THREE.MeshPhysicalMaterial({
      color: 0x7c3aed,
      emissive: 0x5b21b6,
      emissiveIntensity: 1.7,
      metalness: 0.35,
      roughness: 0.12,
      transparent: true,
      opacity: 0.92,
      clearcoat: 1,
      clearcoatRoughness: 0.08,
    });

  const core =
    new THREE.Mesh(
      coreGeometry,
      coreMaterial,
    );

  group.add(core);

  // --------------------------------------------------------------
  // Inner core
  // --------------------------------------------------------------

  const innerGeometry =
    new THREE.IcosahedronGeometry(
      0.42,
      1,
    );

  const innerMaterial =
    new THREE.MeshBasicMaterial({
      color: 0xa78bfa,
      transparent: true,
      opacity: 0.9,
    });

  const inner =
    new THREE.Mesh(
      innerGeometry,
      innerMaterial,
    );

  group.add(inner);

  // --------------------------------------------------------------
  // Outer rings
  // --------------------------------------------------------------

  const ringMaterial =
    new THREE.MeshBasicMaterial({
      color: 0x8b5cf6,
      transparent: true,
      opacity: 0.28,
    });

  const ring1 =
    new THREE.Mesh(
      new THREE.TorusGeometry(
        1.3,
        0.025,
        8,
        72,
      ),
      ringMaterial,
    );

  const ring2 =
    new THREE.Mesh(
      new THREE.TorusGeometry(
        1.65,
        0.016,
        8,
        72,
      ),
      ringMaterial,
    );

  const ring3 =
    new THREE.Mesh(
      new THREE.TorusGeometry(
        2.0,
        0.009,
        8,
        72,
      ),
      ringMaterial,
    );

  ring1.rotation.x =
    Math.PI / 2;

  ring2.rotation.x =
    Math.PI / 3;

  ring3.rotation.x =
    Math.PI / 2.4;

  ring2.rotation.z =
    Math.PI / 5;

  ring3.rotation.y =
    Math.PI / 4;

  group.add(ring1);
  group.add(ring2);
  group.add(ring3);

  // --------------------------------------------------------------
  // Core light
  // --------------------------------------------------------------

  const coreLight =
    new THREE.PointLight(
      0x8b5cf6,
      6,
      8,
      2,
    );

  group.add(coreLight);

  return {
    group,
    core,
    coreLight,
  };
}

/* ================================================================
   CONNECTIONS
   ================================================================ */

function createConnections() {
  const group =
    new THREE.Group();

  const points = [
    [-5.4, 2.2, 0.2],
    [5.1, 2.6, -0.4],
    [-5.0, -2.8, -0.2],
    [5.0, -2.6, 0.4],
  ];

  const center = [0, 0, 0];

  const positions: number[] = [];

  for (const point of points) {
    positions.push(
      point[0],
      point[1],
      point[2],
      center[0],
      center[1],
      center[2],
    );
  }

  // Cross-connections between agents
  const crossPairs = [
    [0, 1],
    [0, 2],
    [1, 3],
    [2, 3],
  ];

  for (const [a, b] of crossPairs) {
    positions.push(
      points[a][0],
      points[a][1],
      points[a][2],
      points[b][0],
      points[b][1],
      points[b][2],
    );
  }

  const geometry =
    new THREE.BufferGeometry();

  geometry.setAttribute(
    "position",
    new THREE.BufferAttribute(
      new Float32Array(positions),
      3,
    ),
  );

  const material =
    new THREE.LineBasicMaterial({
      color: 0x6366f1,
      transparent: true,
      opacity: 0.09,
    });

  const lines =
    new THREE.LineSegments(
      geometry,
      material,
    );

  group.add(lines);

  // Moving data pulses
  const pulsePositions =
    new Float32Array(
      12 * 3,
    );

  for (
    let i = 0;
    i < 12;
    i++
  ) {
    pulsePositions[
      i * 3
    ] =
      (Math.random() - 0.5) *
      9;

    pulsePositions[
      i * 3 + 1
    ] =
      (Math.random() - 0.5) *
      6;

    pulsePositions[
      i * 3 + 2
    ] =
      (Math.random() - 0.5) *
      2;
  }

  const pulseGeometry =
    new THREE.BufferGeometry();

  pulseGeometry.setAttribute(
    "position",
    new THREE.BufferAttribute(
      pulsePositions,
      3,
    ),
  );

  const pulseMaterial =
    new THREE.PointsMaterial({
      color: 0xa78bfa,
      size: 0.045,
      transparent: true,
      opacity: 0.75,
    });

  const pulses =
    new THREE.Points(
      pulseGeometry,
      pulseMaterial,
    );

  group.add(pulses);

  return group;
}

/* ================================================================
   AMBIENT PARTICLES
   ================================================================ */

function createAmbientParticles() {
  const count = 180;

  const positions =
    new Float32Array(
      count * 3,
    );

  for (
    let i = 0;
    i < count;
    i++
  ) {
    const radius =
      5 +
      Math.random() * 8;

    const theta =
      Math.random() *
      Math.PI *
      2;

    const phi =
      Math.acos(
        2 * Math.random() - 1,
      );

    positions[i * 3] =
      radius *
      Math.sin(phi) *
      Math.cos(theta);

    positions[
      i * 3 + 1
    ] =
      radius *
      Math.sin(phi) *
      Math.sin(theta);

    positions[
      i * 3 + 2
    ] =
      radius *
      Math.cos(phi);
  }

  const geometry =
    new THREE.BufferGeometry();

  geometry.setAttribute(
    "position",
    new THREE.BufferAttribute(
      positions,
      3,
    ),
  );

  const material =
    new THREE.PointsMaterial({
      color: 0x6366f1,
      size: 0.035,
      transparent: true,
      opacity: 0.45,
      sizeAttenuation: true,
    });

  return new THREE.Points(
    geometry,
    material,
  );
}

/* ================================================================
   ENVIRONMENT GRID
   ================================================================ */

function createEnvironmentGrid() {
  const group =
    new THREE.Group();

  const gridMaterial =
    new THREE.LineBasicMaterial({
      color: 0x6366f1,
      transparent: true,
      opacity: 0.035,
    });

  const size = 24;
  const divisions = 24;

  const step =
    size / divisions;

  const positions: number[] = [];

  for (
    let i = 0;
    i <= divisions;
    i++
  ) {
    const p =
      -size / 2 +
      i * step;

    positions.push(
      -size / 2,
      -3.05,
      p,
      size / 2,
      -3.05,
      p,
    );

    positions.push(
      p,
      -3.05,
      -size / 2,
      p,
      -3.05,
      size / 2,
    );
  }

  const geometry =
    new THREE.BufferGeometry();

  geometry.setAttribute(
    "position",
    new THREE.BufferAttribute(
      new Float32Array(positions),
      3,
    ),
  );

  const grid =
    new THREE.LineSegments(
      geometry,
      gridMaterial,
    );

  grid.position.z = -2;

  group.add(grid);

  return group;
}

/* ================================================================
   DISPOSAL
   ================================================================ */

function disposeObject3D(
  object: THREE.Object3D,
) {
  object.traverse((child) => {
    const mesh =
      child as THREE.Mesh;

    if (mesh.geometry) {
      try {
        mesh.geometry.dispose();
      } catch {
        // Ignore.
      }
    }

    const material =
      mesh.material;

    if (Array.isArray(material)) {
      material.forEach(
        disposeMaterial,
      );
    } else if (material) {
      disposeMaterial(material);
    }
  });
}

function disposeMaterial(
  material: THREE.Material,
) {
  try {
    material.dispose();
  } catch {
    // Ignore.
  }
}

/* ================================================================
   WEBGL DETECTION
   ================================================================ */

function isWebGLAvailable(): boolean {
  try {
    const canvas =
      document.createElement(
        "canvas",
      );

    const webgl2 =
      canvas.getContext(
        "webgl2",
        {
          failIfMajorPerformanceCaveat:
            false,
          antialias: false,
        },
      );

    if (webgl2) {
      return true;
    }

    const webgl =
      canvas.getContext(
        "webgl",
        {
          failIfMajorPerformanceCaveat:
            false,
          antialias: false,
        },
      );

    return !!webgl;
  } catch {
    return false;
  }
}
