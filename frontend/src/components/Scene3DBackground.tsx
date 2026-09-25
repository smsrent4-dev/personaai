import { useEffect, useRef } from "react";
import * as THREE from "three";

type AgentName = "PERSONAL" | "SALES" | "SUPPORT" | "OPPORTUNITY";

interface AgentNode {
  name: AgentName;
  angle: number;
  radius: number;
  color: number;
  position: THREE.Vector3;
  mesh: THREE.Mesh;
  glow: THREE.Mesh;
  pulse: number;
}

interface DataPacket {
  line: THREE.Line;
  start: THREE.Vector3;
  end: THREE.Vector3;
  progress: number;
  speed: number;
  point: THREE.Vector3;
  tail: THREE.Vector3;
}

interface Panel {
  group: THREE.Group;
  phase: number;
  baseY: number;
  baseScale: number;
}

const COLORS = {
  cyan: 0x35d9ff,
  blue: 0x4c7dff,
  violet: 0x8b5cf6,
  purple: 0xa855f7,
  white: 0xeaf6ff,
  green: 0x39ff9a,
  amber: 0xffc857,
  dark: 0x050812,
};

const AGENTS: Array<{
  name: AgentName;
  color: number;
}> = [
  {
    name: "PERSONAL",
    color: COLORS.cyan,
  },
  {
    name: "SALES",
    color: COLORS.violet,
  },
  {
    name: "SUPPORT",
    color: COLORS.blue,
  },
  {
    name: "OPPORTUNITY",
    color: COLORS.green,
  },
];

function isWebGLAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");

    const context =
      canvas.getContext("webgl2") ||
      canvas.getContext("webgl") ||
      canvas.getContext("experimental-webgl");

    return Boolean(context);
  } catch {
    return false;
  }
}

function disposeMaterial(material: THREE.Material): void {
  const materialWithMaps = material as THREE.Material & {
    map?: THREE.Texture | null;
    alphaMap?: THREE.Texture | null;
    normalMap?: THREE.Texture | null;
    roughnessMap?: THREE.Texture | null;
    metalnessMap?: THREE.Texture | null;
    emissiveMap?: THREE.Texture | null;
  };

  const textures = [
    materialWithMaps.map,
    materialWithMaps.alphaMap,
    materialWithMaps.normalMap,
    materialWithMaps.roughnessMap,
    materialWithMaps.metalnessMap,
    materialWithMaps.emissiveMap,
  ];

  const uniqueTextures = new Set<THREE.Texture>();

  for (const texture of textures) {
    if (texture) {
      uniqueTextures.add(texture);
    }
  }

  for (const texture of uniqueTextures) {
    texture.dispose();
  }

  material.dispose();
}

function disposeObject3D(root: THREE.Object3D): void {
  root.traverse((object) => {
    const drawable = object as THREE.Mesh;

    if (drawable.geometry) {
      drawable.geometry.dispose();
    }

    const material = drawable.material;

    if (Array.isArray(material)) {
      for (const item of material) {
        disposeMaterial(item);
      }
    } else if (material) {
      disposeMaterial(material);
    }
  });
}

function makeLine(
  points: THREE.Vector3[],
  color: number,
  opacity = 0.45
): THREE.Line {
  const geometry = new THREE.BufferGeometry().setFromPoints(points);

  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthWrite: false,
  });

  return new THREE.Line(geometry, material);
}

function makeLineSegments(
  positions: number[],
  color: number,
  opacity = 0.35
): THREE.LineSegments {
  const geometry = new THREE.BufferGeometry();

  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3)
  );

  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthWrite: false,
  });

  return new THREE.LineSegments(geometry, material);
}

function makeGlowSphere(
  radius: number,
  color: number,
  opacity: number
): THREE.Mesh {
  const geometry = new THREE.SphereGeometry(radius, 24, 24);

  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });

  return new THREE.Mesh(geometry, material);
}

function createPanel(
  color: number,
  width = 2.8,
  height = 1.55
): THREE.Group {
  const group = new THREE.Group();

  const backgroundGeometry = new THREE.PlaneGeometry(
    width,
    height
  );

  const background = new THREE.Mesh(
    backgroundGeometry,
    new THREE.MeshBasicMaterial({
      color: COLORS.dark,
      transparent: true,
      opacity: 0.45,
      depthWrite: false,
      side: THREE.DoubleSide,
    })
  );

  group.add(background);

  const borderGeometry = new THREE.EdgesGeometry(
    backgroundGeometry
  );

  const border = new THREE.LineSegments(
    borderGeometry,
    new THREE.LineBasicMaterial({
      color,
      transparent: true,
      opacity: 0.6,
      depthWrite: false,
    })
  );

  group.add(border);

  // Header line.
  const header = new THREE.Mesh(
    new THREE.PlaneGeometry(width * 0.56, 0.035),
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.8,
      depthWrite: false,
    })
  );

  header.position.set(
    -width * 0.18,
    height * 0.28,
    0.015
  );

  group.add(header);

  // System indicators.
  for (let i = 0; i < 5; i += 1) {
    const indicator = new THREE.Mesh(
      new THREE.PlaneGeometry(0.12, 0.12),
      new THREE.MeshBasicMaterial({
        color: i === 0 ? COLORS.green : color,
        transparent: true,
        opacity: i === 0 ? 0.9 : 0.45,
        depthWrite: false,
      })
    );

    indicator.position.set(
      -width * 0.36 + i * 0.2,
      height * 0.42,
      0.02
    );

    group.add(indicator);
  }

  // Data bars.
  const barWidths = [
    0.42,
    0.72,
    0.54,
    0.88,
    0.62,
  ];

  barWidths.forEach((barWidth, index) => {
    const bar = new THREE.Mesh(
      new THREE.PlaneGeometry(
        barWidth,
        0.045
      ),
      new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: 0.3 + index * 0.08,
        depthWrite: false,
      })
    );

    bar.position.set(
      -width * 0.22 + barWidth / 2,
      height * 0.12 - index * 0.16,
      0.02
    );

    group.add(bar);
  });

  // Mini graph.
  const graphPoints: THREE.Vector3[] = [];

  for (let i = 0; i < 7; i += 1) {
    const x =
      -width * 0.38 +
      i * (width * 0.11);

    const y =
      -height * 0.28 +
      Math.sin(i * 1.35) * 0.08 +
      (i % 3) * 0.035;

    graphPoints.push(
      new THREE.Vector3(x, y, 0.03)
    );
  }

  group.add(
    makeLine(
      graphPoints,
      color,
      0.55
    )
  );

  return group;
}

function createRadar(color: number): THREE.Group {
  const group = new THREE.Group();

  const radii = [1.8, 2.45, 3.1];

  radii.forEach((radius, index) => {
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(
        radius - 0.008,
        radius,
        96
      ),
      new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity:
          0.12 - index * 0.025,
        side: THREE.DoubleSide,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      })
    );

    ring.rotation.x = Math.PI / 2;

    group.add(ring);
  });

  const divisions = 16;
  const positions: number[] = [];

  for (let i = 0; i < divisions; i += 1) {
    const angle =
      (i / divisions) *
      Math.PI *
      2;

    const x1 =
      Math.cos(angle) * 1.8;

    const z1 =
      Math.sin(angle) * 1.8;

    const x2 =
      Math.cos(angle) * 3.1;

    const z2 =
      Math.sin(angle) * 3.1;

    positions.push(
      x1,
      0,
      z1,
      x2,
      0,
      z2
    );
  }

  group.add(
    makeLineSegments(
      positions,
      color,
      0.12
    )
  );

  return group;
}

function createCentralCore(): THREE.Group {
  const group = new THREE.Group();

  // Outer atmospheric halo.
  const halo = new THREE.Mesh(
    new THREE.SphereGeometry(
      1.65,
      24,
      24
    ),
    new THREE.MeshBasicMaterial({
      color: COLORS.blue,
      transparent: true,
      opacity: 0.035,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
  );

  group.add(halo);

  // Outer wireframe cage.
  const outerCage = new THREE.Mesh(
    new THREE.IcosahedronGeometry(
      1.45,
      1
    ),
    new THREE.MeshBasicMaterial({
      color: COLORS.cyan,
      wireframe: true,
      transparent: true,
      opacity: 0.3,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
  );

  group.add(outerCage);

  // Inner wireframe cage.
  const innerCage = new THREE.Mesh(
    new THREE.DodecahedronGeometry(
      1.05,
      1
    ),
    new THREE.MeshBasicMaterial({
      color: COLORS.violet,
      wireframe: true,
      transparent: true,
      opacity: 0.4,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
  );

  group.add(innerCage);

  // Reactor body.
  const reactor = new THREE.Mesh(
    new THREE.IcosahedronGeometry(
      0.72,
      3
    ),
    new THREE.MeshBasicMaterial({
      color: COLORS.cyan,
      transparent: true,
      opacity: 0.65,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
  );

  group.add(reactor);

  // Bright central core.
  const core = new THREE.Mesh(
    new THREE.SphereGeometry(
      0.38,
      32,
      32
    ),
    new THREE.MeshBasicMaterial({
      color: COLORS.white,
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
  );

  group.add(core);

  // Glow layers.
  group.add(
    makeGlowSphere(
      0.58,
      COLORS.cyan,
      0.08
    )
  );

  group.add(
    makeGlowSphere(
      0.82,
      COLORS.violet,
      0.035
    )
  );

  // Energy rings.
  const ringSpecs = [
    {
      radius: 1.75,
      tube: 0.018,
      color: COLORS.cyan,
    },
    {
      radius: 1.45,
      tube: 0.012,
      color: COLORS.violet,
    },
    {
      radius: 1.12,
      tube: 0.009,
      color: COLORS.blue,
    },
  ];

  ringSpecs.forEach(
    (spec, index) => {
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(
          spec.radius,
          spec.tube,
          8,
          128
        ),
        new THREE.MeshBasicMaterial({
          color: spec.color,
          transparent: true,
          opacity: 0.6,
          depthWrite: false,
          blending:
            THREE.AdditiveBlending,
        })
      );

      ring.rotation.set(
        index === 0 ? 0.3 : 1.0,
        index === 1 ? 0.8 : 0.2,
        index * 0.6
      );

      group.add(ring);
    }
  );

  return group;
}

function createScanArc(
  radius: number,
  color: number,
  startAngle: number,
  length: number
): THREE.Mesh {
  return new THREE.Mesh(
    new THREE.RingGeometry(
      radius - 0.018,
      radius,
      128,
      1,
      startAngle,
      length
    ),
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.65,
      side: THREE.DoubleSide,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
  );
}

function createEnvironmentGrid(): THREE.Group {
  const group = new THREE.Group();

  const size = 28;
  const divisions = 28;

  const positions: number[] = [];

  for (
    let i = 0;
    i <= divisions;
    i += 1
  ) {
    const value =
      -size / 2 +
      (i / divisions) * size;

    positions.push(
      value,
      -3.3,
      -size / 2
    );

    positions.push(
      value,
      -3.3,
      size / 2
    );

    positions.push(
      -size / 2,
      -3.3,
      value
    );

    positions.push(
      size / 2,
      -3.3,
      value
    );
  }

  group.add(
    makeLineSegments(
      positions,
      COLORS.blue,
      0.065
    )
  );

  return group;
}

function createConnection(
  start: THREE.Vector3,
  end: THREE.Vector3,
  color: number
): THREE.Line {
  const middle = new THREE.Vector3()
    .addVectors(start, end)
    .multiplyScalar(0.5);

  middle.y += 0.65;

  const curve =
    new THREE.QuadraticBezierCurve3(
      start,
      middle,
      end
    );

  const points =
    curve.getPoints(32);

  return makeLine(
    points,
    color,
    0.28
  );
}

function createDataPacket(
  start: THREE.Vector3,
  end: THREE.Vector3,
  color: number,
  index: number
): DataPacket {
  const geometry =
    new THREE.BufferGeometry().setFromPoints(
      [
        new THREE.Vector3(),
        new THREE.Vector3(
          0.055,
          0,
          0
        ),
      ]
    );

  const material =
    new THREE.LineBasicMaterial({
      color,
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

  const line = new THREE.Line(
    geometry,
    material
  );

  return {
    line,
    start,
    end,
    progress:
      (index * 0.23) % 1,
    speed:
      0.0008 +
      (index % 3) * 0.00025,
    point: new THREE.Vector3(),
    tail: new THREE.Vector3(),
  };
}

export default function Scene3DBackground() {
  const mountRef =
    useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const mount = mountRef.current;

    if (!mount) {
      return;
    }

    if (!isWebGLAvailable()) {
      return;
    }

    let renderer:
      | THREE.WebGLRenderer
      | null = null;

    let scene:
      | THREE.Scene
      | null = null;

    let camera:
      | THREE.PerspectiveCamera
      | null = null;

    let animationFrame = 0;
    let destroyed = false;
    let contextLost = false;

    const cleanupCallbacks:
      Array<() => void> = [];

    try {
      /*
       * ============================================================
       * SCENE
       * ============================================================
       */

      scene = new THREE.Scene();

      scene.fog = new THREE.FogExp2(
        0x05060b,
        0.028
      );

      camera =
        new THREE.PerspectiveCamera(
          48,
          1,
          0.1,
          100
        );

      camera.position.set(
        0,
        1.2,
        12
      );

      /*
       * ============================================================
       * RENDERER
       * ============================================================
       */

      renderer =
        new THREE.WebGLRenderer({
          antialias: true,
          alpha: true,
          powerPreference:
            "high-performance",
          depth: false,
          stencil: false,
          preserveDrawingBuffer: false,
        });

      renderer.setPixelRatio(
        Math.min(
          window.devicePixelRatio || 1,
          1.65
        )
      );

      renderer.setClearColor(
        0x000000,
        0
      );

      renderer.outputColorSpace =
        THREE.SRGBColorSpace;

      renderer.domElement.style.width =
        "100%";

      renderer.domElement.style.height =
        "100%";

      renderer.domElement.style.display =
        "block";

      renderer.domElement.style.pointerEvents =
        "none";

      mount.appendChild(
        renderer.domElement
      );

      /*
       * ============================================================
       * WEBGL CONTEXT SAFETY
       * ============================================================
       */

      const canvas =
        renderer.domElement;

      const handleContextLost = (
        event: Event
      ) => {
        event.preventDefault();
        contextLost = true;
      };

      const handleContextRestored =
        () => {
          contextLost = false;
        };

      canvas.addEventListener(
        "webglcontextlost",
        handleContextLost,
        false
      );

      canvas.addEventListener(
        "webglcontextrestored",
        handleContextRestored,
        false
      );

      cleanupCallbacks.push(() => {
        canvas.removeEventListener(
          "webglcontextlost",
          handleContextLost
        );

        canvas.removeEventListener(
          "webglcontextrestored",
          handleContextRestored
        );
      });

      /*
       * ============================================================
       * LIGHTING
       * ============================================================
       */

      const ambientLight =
        new THREE.AmbientLight(
          0x3854a8,
          0.7
        );

      scene.add(ambientLight);

      const cyanLight =
        new THREE.PointLight(
          COLORS.cyan,
          8,
          18,
          2
        );

      cyanLight.position.set(
        0,
        1,
        1
      );

      scene.add(cyanLight);

      const violetLight =
        new THREE.PointLight(
          COLORS.violet,
          7,
          16,
          2
        );

      violetLight.position.set(
        -4,
        1.5,
        -2
      );

      scene.add(violetLight);

      const blueLight =
        new THREE.PointLight(
          COLORS.blue,
          6,
          18,
          2
        );

      blueLight.position.set(
        4,
        0.5,
        -3
      );

      scene.add(blueLight);

      /*
       * ============================================================
       * WORLD
       * ============================================================
       */

      const world =
        new THREE.Group();

      scene.add(world);

      /*
       * ============================================================
       * CENTRAL AI CORE
       * ============================================================
       */

      const coreSystem =
        new THREE.Group();

      coreSystem.position.y = 0.55;

      world.add(coreSystem);

      const core =
        createCentralCore();

      coreSystem.add(core);

      /*
       * ============================================================
       * RADAR
       * ============================================================
       */

      const radar =
        createRadar(
          COLORS.cyan
        );

      radar.position.y = -0.15;

      world.add(radar);

      const largeRing =
        new THREE.Mesh(
          new THREE.TorusGeometry(
            3.85,
            0.012,
            8,
            160
          ),
          new THREE.MeshBasicMaterial({
            color: COLORS.blue,
            transparent: true,
            opacity: 0.24,
            depthWrite: false,
            blending:
              THREE.AdditiveBlending,
          })
        );

      largeRing.rotation.x =
        Math.PI / 2;

      largeRing.position.y = -0.1;

      world.add(largeRing);

      /*
       * ============================================================
       * SCANNING ARCS
       * ============================================================
       */

      const scanArcs = [
        createScanArc(
          2.0,
          COLORS.cyan,
          0.2,
          1.3
        ),
        createScanArc(
          2.7,
          COLORS.violet,
          2.2,
          0.9
        ),
        createScanArc(
          3.35,
          COLORS.blue,
          4.0,
          1.15
        ),
      ];

      scanArcs.forEach(
        (arc, index) => {
          arc.rotation.x =
            Math.PI / 2;

          arc.position.y =
            0.05 +
            index * 0.025;

          world.add(arc);
        }
      );

      /*
       * ============================================================
       * HOLOGRAPHIC ENERGY BEAM
       * ============================================================
       */

      const beam =
        new THREE.Mesh(
          new THREE.CylinderGeometry(
            0.28,
            0.55,
            7,
            32,
            1,
            true
          ),
          new THREE.MeshBasicMaterial({
            color: COLORS.cyan,
            transparent: true,
            opacity: 0.025,
            side: THREE.DoubleSide,
            depthWrite: false,
            blending:
              THREE.AdditiveBlending,
          })
        );

      beam.position.set(
        0,
        0.7,
        0
      );

      world.add(beam);

      /*
       * ============================================================
       * FOUR AI AGENTS
       * ============================================================
       */

      const agentGroup =
        new THREE.Group();

      world.add(agentGroup);

      const agents: AgentNode[] =
        [];

      const desktopRadius = 5.1;

      AGENTS.forEach(
        (agent, index) => {
          const angle =
            -Math.PI / 2 +
            (index /
              AGENTS.length) *
              Math.PI *
              2;

          const position =
            new THREE.Vector3(
              Math.cos(angle) *
                desktopRadius,
              0.35 +
                Math.sin(
                  index * 1.4
                ) *
                  0.3,
              Math.sin(angle) *
                desktopRadius
            );

          const mesh =
            new THREE.Mesh(
              new THREE.OctahedronGeometry(
                0.23,
                1
              ),
              new THREE.MeshBasicMaterial({
                color:
                  agent.color,
                wireframe: true,
                transparent: true,
                opacity: 0.85,
                depthWrite: false,
                blending:
                  THREE.AdditiveBlending,
              })
            );

          mesh.position.copy(
            position
          );

          const glow =
            makeGlowSphere(
              0.6,
              agent.color,
              0.05
            );

          glow.position.copy(
            position
          );

          agentGroup.add(mesh);
          agentGroup.add(glow);

          agents.push({
            name: agent.name,
            angle,
            radius:
              desktopRadius,
            color:
              agent.color,
            position,
            mesh,
            glow,
            pulse:
              index * 1.4,
          });
        }
      );

      /*
       * ============================================================
       * NEURAL NETWORK
       * ============================================================
       */

      const connections =
        new THREE.Group();

      world.add(connections);

      const dataPackets:
        DataPacket[] = [];

      agents.forEach(
        (agent, index) => {
          const start =
            new THREE.Vector3(
              0,
              0.55,
              0
            );

          const end =
            agent.position.clone();

          const connection =
            createConnection(
              start,
              end,
              agent.color
            );

          connections.add(
            connection
          );

          for (
            let packetIndex = 0;
            packetIndex < 2;
            packetIndex += 1
          ) {
            const packet =
              createDataPacket(
                start,
                end,
                agent.color,
                index * 2 +
                  packetIndex
              );

            connections.add(
              packet.line
            );

            dataPackets.push(
              packet
            );
          }
        }
      );

      /*
       * Agent-to-agent secondary network.
       */
      for (
        let i = 0;
        i < agents.length;
        i += 1
      ) {
        const current =
          agents[i];

        const next =
          agents[
            (i + 1) %
              agents.length
          ];

        const secondary =
          createConnection(
            current.position,
            next.position,
            COLORS.blue
          );

        const material =
          secondary.material as THREE.LineBasicMaterial;

        material.opacity =
          0.12;

        connections.add(
          secondary
        );
      }

      /*
       * ============================================================
       * HOLOGRAPHIC DATA PANELS
       * ============================================================
       */

      const panelsGroup =
        new THREE.Group();

      world.add(
        panelsGroup
      );

      const panels: Panel[] =
        [];

      const panelDefinitions = [
        {
          angle: -2.55,
          radius: 6.4,
          color: COLORS.cyan,
          scale: 0.9,
        },
        {
          angle: -0.55,
          radius: 6.5,
          color: COLORS.violet,
          scale: 0.82,
        },
        {
          angle: 0.58,
          radius: 6.3,
          color: COLORS.blue,
          scale: 0.84,
        },
        {
          angle: 2.6,
          radius: 6.2,
          color: COLORS.green,
          scale: 0.88,
        },
      ];

      panelDefinitions.forEach(
        (
          definition,
          index
        ) => {
          const panel =
            createPanel(
              definition.color
            );

          panel.scale.setScalar(
            definition.scale
          );

          panel.position.set(
            Math.cos(
              definition.angle
            ) *
              definition.radius,
            1.3 +
              Math.sin(
                index * 2.1
              ) *
                0.5,
            Math.sin(
              definition.angle
            ) *
              definition.radius
          );

          panel.lookAt(
            0,
            1.1,
            0
          );

          panelsGroup.add(
            panel
          );

          panels.push({
            group: panel,
            phase:
              index * 1.8,
            baseY:
              panel.position.y,
            baseScale:
              definition.scale,
          });
        }
      );

      /*
       * ============================================================
       * AMBIENT PARTICLES
       * ============================================================
       */

      const initialWidth =
        window.innerWidth;

      const particleCount =
        initialWidth < 768
          ? 280
          : 650;

      const particlePositions =
        new Float32Array(
          particleCount * 3
        );

      for (
        let i = 0;
        i < particleCount;
        i += 1
      ) {
        const radius =
          5 +
          Math.random() * 11;

        const angle =
          Math.random() *
          Math.PI *
          2;

        particlePositions[
          i * 3
        ] =
          Math.cos(angle) *
          radius;

        particlePositions[
          i * 3 + 1
        ] =
          -2.5 +
          Math.random() * 8;

        particlePositions[
          i * 3 + 2
        ] =
          Math.sin(angle) *
            radius -
          2;
      }

      const particleGeometry =
        new THREE.BufferGeometry();

      particleGeometry.setAttribute(
        "position",
        new THREE.BufferAttribute(
          particlePositions,
          3
        )
      );

      const particleMaterial =
        new THREE.PointsMaterial({
          color: COLORS.cyan,
          size: 0.045,
          transparent: true,
          opacity: 0.48,
          depthWrite: false,
          blending:
            THREE.AdditiveBlending,
          sizeAttenuation: true,
        });

      const particles =
        new THREE.Points(
          particleGeometry,
          particleMaterial
        );

      world.add(particles);

      /*
       * ============================================================
       * RADIAL HUD RAYS
       * ============================================================
       */

      const rayPositions: number[] =
        [];

      for (
        let i = 0;
        i < 64;
        i += 1
      ) {
        const angle =
          (i / 64) *
          Math.PI *
          2;

        const inner = 3.9;
        const outer = 7.5;

        rayPositions.push(
          Math.cos(angle) *
            inner,
          -0.02,
          Math.sin(angle) *
            inner
        );

        rayPositions.push(
          Math.cos(angle) *
            outer,
          -0.02,
          Math.sin(angle) *
            outer
        );
      }

      const rays =
        makeLineSegments(
          rayPositions,
          COLORS.blue,
          0.08
        );

      world.add(rays);

      /*
       * ============================================================
       * FLOOR RING
       * ============================================================
       */

      const floorRing =
        new THREE.Mesh(
          new THREE.RingGeometry(
            4.6,
            4.62,
            128
          ),
          new THREE.MeshBasicMaterial({
            color: COLORS.cyan,
            transparent: true,
            opacity: 0.22,
            side: THREE.DoubleSide,
            depthWrite: false,
            blending:
              THREE.AdditiveBlending,
          })
        );

      floorRing.rotation.x =
        Math.PI / 2;

      floorRing.position.y =
        -3.27;

      world.add(
        floorRing
      );

      /*
       * ============================================================
       * ENVIRONMENT GRID
       * ============================================================
       */

      const environmentGrid =
        createEnvironmentGrid();

      environmentGrid.position.z =
        -2;

      world.add(
        environmentGrid
      );

      /*
       * ============================================================
       * RESPONSIVE LAYOUT
       * ============================================================
       */

      const updateSize = () => {
        if (
          !renderer ||
          !camera ||
          !mount
        ) {
          return;
        }

        const width =
          Math.max(
            1,
            mount.clientWidth
          );

        const height =
          Math.max(
            1,
            mount.clientHeight
          );

        camera.aspect =
          width / height;

        if (width < 480) {
          camera.fov = 55;

          camera.position.set(
            0,
            1.7,
            15.5
          );

          world.scale.setScalar(
            0.78
          );

          coreSystem.position.y =
            1.2;

          panelsGroup.visible =
            false;

          environmentGrid.visible =
            false;

          rays.visible = false;
        } else if (
          width < 768
        ) {
          camera.fov = 52;

          camera.position.set(
            0,
            1.5,
            14
          );

          world.scale.setScalar(
            0.88
          );

          coreSystem.position.y =
            0.95;

          panelsGroup.visible =
            false;

          environmentGrid.visible =
            true;

          rays.visible = true;
        } else if (
          width < 1100
        ) {
          camera.fov = 49;

          camera.position.set(
            0,
            1.3,
            13
          );

          world.scale.setScalar(
            0.94
          );

          coreSystem.position.y =
            0.75;

          panelsGroup.visible =
            true;

          environmentGrid.visible =
            true;

          rays.visible = true;
        } else {
          camera.fov = 47;

          camera.position.set(
            0,
            1.1,
            12
          );

          world.scale.setScalar(
            1
          );

          coreSystem.position.y =
            0.55;

          panelsGroup.visible =
            true;

          environmentGrid.visible =
            true;

          rays.visible = true;
        }

        camera.updateProjectionMatrix();

        renderer.setPixelRatio(
          Math.min(
            window.devicePixelRatio ||
              1,
            width < 768
              ? 1.25
              : 1.65
          )
        );

        renderer.setSize(
          width,
          height,
          false
        );
      };

      updateSize();

      const resizeObserver =
        new ResizeObserver(
          updateSize
        );

      resizeObserver.observe(
        mount
      );

      cleanupCallbacks.push(
        () => {
          resizeObserver.disconnect();
        }
      );

      /*
       * ============================================================
       * MOUSE PARALLAX
       * ============================================================
       */

      let targetRotationX = 0;
      let targetRotationY = 0;

      let currentRotationX = 0;
      let currentRotationY = 0;

      const handlePointerMove = (
        event: PointerEvent
      ) => {
        if (
          window.innerWidth <
          768
        ) {
          return;
        }

        const normalizedX =
          event.clientX /
            window.innerWidth -
          0.5;

        const normalizedY =
          event.clientY /
            window.innerHeight -
          0.5;

        targetRotationY =
          normalizedX * 0.12;

        targetRotationX =
          normalizedY * 0.07;
      };

      window.addEventListener(
        "pointermove",
        handlePointerMove,
        {
          passive: true,
        }
      );

      cleanupCallbacks.push(
        () => {
          window.removeEventListener(
            "pointermove",
            handlePointerMove
          );
        }
      );

      /*
       * ============================================================
       * ANIMATION
       * ============================================================
       */

      const clock =
        new THREE.Clock();

      const prefersReducedMotion =
        window.matchMedia(
          "(prefers-reduced-motion: reduce)"
        ).matches;

      const animate = () => {
        if (destroyed) {
          return;
        }

        animationFrame =
          window.requestAnimationFrame(
            animate
          );

        if (
          contextLost ||
          !renderer ||
          !scene ||
          !camera
        ) {
          return;
        }

        const elapsed =
          clock.getElapsedTime();

        if (
          !prefersReducedMotion
        ) {
          /*
           * Camera movement.
           */
          currentRotationX +=
            (targetRotationX -
              currentRotationX) *
            0.025;

          currentRotationY +=
            (targetRotationY -
              currentRotationY) *
            0.025;

          world.rotation.x =
            currentRotationX;

          world.rotation.y =
            currentRotationY;

          /*
           * Central reactor.
           */
          core.rotation.y +=
            0.0025;

          core.rotation.x +=
            0.0012;

          const coreChildren =
            core.children;

          if (coreChildren[1]) {
            coreChildren[1].rotation.y -=
              0.004;

            coreChildren[1].rotation.z +=
              0.0015;
          }

          if (coreChildren[2]) {
            coreChildren[2].rotation.x +=
              0.003;

            coreChildren[2].rotation.y +=
              0.002;
          }

          if (coreChildren[3]) {
            const pulse =
              1 +
              Math.sin(
                elapsed * 3.4
              ) *
                0.045;

            coreChildren[3].scale.setScalar(
              pulse
            );
          }

          if (coreChildren[4]) {
            const pulse =
              1 +
              Math.sin(
                elapsed * 4.1
              ) *
                0.08;

            coreChildren[4].scale.setScalar(
              pulse
            );
          }

          /*
           * Core energy rings.
           */
          for (
            let index = 6;
            index <
            core.children.length;
            index += 1
          ) {
            const ring =
              core.children[index];

            ring.rotation.x +=
              index % 2 === 0
                ? 0.0018
                : -0.0013;

            ring.rotation.y +=
              index % 2 === 0
                ? -0.0012
                : 0.0018;
          }

          /*
           * Radar.
           */
          radar.rotation.y +=
            0.0009;

          /*
           * Outer ring.
           */
          largeRing.rotation.z +=
            0.0007;

          /*
           * Scan arcs.
           */
          scanArcs.forEach(
            (arc, index) => {
              arc.rotation.z +=
                index % 2 === 0
                  ? 0.003
                  : -0.002;

              const material =
                arc.material as THREE.MeshBasicMaterial;

              material.opacity =
                0.42 +
                Math.sin(
                  elapsed * 2 +
                    index
                ) *
                  0.18;
            }
          );

          /*
           * Beam pulse.
           */
          const beamMaterial =
            beam.material as THREE.MeshBasicMaterial;

          beamMaterial.opacity =
            0.02 +
            Math.sin(
              elapsed * 2.4
            ) *
              0.008;

          /*
           * Four AI agents.
           */
          agents.forEach(
            (agent, index) => {
              const pulse =
                1 +
                Math.sin(
                  elapsed * 2.2 +
                    agent.pulse
                ) *
                  0.2;

              agent.mesh.scale.setScalar(
                pulse
              );

              agent.mesh.rotation.x +=
                0.006 +
                index * 0.0005;

              agent.mesh.rotation.y +=
                0.009 +
                index * 0.0006;

              const glowScale =
                0.9 +
                Math.sin(
                  elapsed * 2.2 +
                    agent.pulse
                ) *
                  0.16;

              agent.glow.scale.setScalar(
                glowScale
              );

              const material =
                agent.mesh.material as THREE.MeshBasicMaterial;

              material.opacity =
                0.55 +
                Math.sin(
                  elapsed * 2.2 +
                    agent.pulse
                ) *
                  0.25;
            }
          );

          /*
           * Data packets.
           */
          dataPackets.forEach(
            (packet) => {
              packet.progress +=
                packet.speed;

              if (
                packet.progress >
                1
              ) {
                packet.progress = 0;
              }

              packet.point.lerpVectors(
                packet.start,
                packet.end,
                packet.progress
              );

              packet.tail.lerpVectors(
                packet.start,
                packet.end,
                Math.max(
                  0,
                  packet.progress -
                    0.025
                )
              );

              const positions =
                packet.line.geometry.getAttribute(
                  "position"
                ) as THREE.BufferAttribute;

              positions.setXYZ(
                0,
                packet.tail.x,
                packet.tail.y,
                packet.tail.z
              );

              positions.setXYZ(
                1,
                packet.point.x,
                packet.point.y,
                packet.point.z
              );

              positions.needsUpdate =
                true;
            }
          );

          /*
           * Holographic panels.
           */
          panels.forEach(
            (panel, index) => {
              panel.group.position.y =
                panel.baseY +
                Math.sin(
                  elapsed * 0.8 +
                    panel.phase
                ) *
                  0.08;

              panel.group.rotation.z =
                Math.sin(
                  elapsed * 0.35 +
                    panel.phase
                ) *
                  0.015;

              const scalePulse =
                1 +
                Math.sin(
                  elapsed * 1.3 +
                    index
                ) *
                  0.008;

              panel.group.scale.setScalar(
                panel.baseScale *
                  scalePulse
              );
            }
          );

          /*
           * Particles.
           */
          particles.rotation.y +=
            0.00035;

          particles.rotation.x =
            Math.sin(
              elapsed * 0.12
            ) * 0.015;

          /*
           * Floor grid.
           */
          environmentGrid.position.z =
            -2 +
            Math.sin(
              elapsed * 0.15
            ) *
              0.08;

          /*
           * Floor ring.
           */
          const floorPulse =
            1 +
            Math.sin(
              elapsed * 1.8
            ) *
              0.015;

          floorRing.scale.setScalar(
            floorPulse
          );
        }

        renderer.render(
          scene,
          camera
        );
      };

      animate();

      /*
       * ============================================================
       * CLEANUP
       * ============================================================
       */

      return () => {
        destroyed = true;

        window.cancelAnimationFrame(
          animationFrame
        );

        for (
          const callback of cleanupCallbacks
        ) {
          try {
            callback();
          } catch {
            // Defensive cleanup.
          }
        }

        try {
          if (scene) {
            disposeObject3D(
              scene
            );
          }
        } catch {
          // Defensive cleanup.
        }

        try {
          if (renderer) {
            renderer.forceContextLoss();
            renderer.dispose();

            const rendererCanvas =
              renderer.domElement;

            if (
              rendererCanvas.parentElement ===
              mount
            ) {
              mount.removeChild(
                rendererCanvas
              );
            }
          }
        } catch {
          // Defensive cleanup.
        }

        renderer = null;
        camera = null;
        scene = null;
      };
    } catch (error) {
      console.warn(
        "PersonaAI 3D background could not initialize:",
        error
      );

      destroyed = true;

      window.cancelAnimationFrame(
        animationFrame
      );

      for (
        const callback of cleanupCallbacks
      ) {
        try {
          callback();
        } catch {
          // Defensive cleanup.
        }
      }

      try {
        if (scene) {
          disposeObject3D(
            scene
          );
        }
      } catch {
        // Defensive cleanup.
      }

      try {
        if (renderer) {
          renderer.forceContextLoss();
          renderer.dispose();

          const rendererCanvas =
            renderer.domElement;

          if (
            rendererCanvas.parentElement ===
            mount
          ) {
            mount.removeChild(
              rendererCanvas
            );
          }
        }
      } catch {
        // Defensive cleanup.
      }

      renderer = null;
      camera = null;
      scene = null;

      return undefined;
    }
  }, []);

  return (
    <div
      ref={mountRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-0 overflow-hidden"
    >
      {/* Atmospheric AI lighting. */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_42%,rgba(76,125,255,0.10),transparent_28%),radial-gradient(circle_at_20%_60%,rgba(139,92,246,0.07),transparent_30%),radial-gradient(circle_at_80%_35%,rgba(53,217,255,0.06),transparent_28%)]" />

      {/* Cinematic vignette. */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_38%,rgba(3,4,9,0.48)_100%)]" />

      {/* Subtle holographic scan lines. */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.035]"
        style={{
          backgroundImage:
            "repeating-linear-gradient(to bottom, transparent 0px, transparent 3px, rgba(255,255,255,0.35) 4px)",
        }}
      />
    </div>
  );
}
