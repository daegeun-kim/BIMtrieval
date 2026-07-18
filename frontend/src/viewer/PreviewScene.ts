// Isolated single-instance preview for the component panel (tasks/task14.md §5;
// scheduling/visibility/lifetime rewritten by tasks/task18.md §10).
//
// Resource strategy: this renders ONLY the selected instance, from geometry
// buffers extracted out of the model the main viewer already has loaded
// (`ViewerAdapter.extractItemGeometry`). It never downloads or re-parses the
// artifact, and never clones the whole model — a Fragments artifact for this
// project is ~5.5 MB and thousands of items, so duplicating it for a 320px
// thumbnail would be indefensible.
//
// The instance keeps the same semantic base color it has in the main viewer, so
// the preview reads as a detail of the same drawing rather than a generic
// thumbnail.
//
// Rendering is invalidation-driven (task18 §10): the RAF chain only runs while
// there is an active reason to (a drag/wheel interaction, an in-lifetime
// auto-rotation, or a pending render) and stops otherwise — an idle preview
// does not keep re-rendering an unchanged frame. An IntersectionObserver and
// `document.visibilitychange` fully pause it when off-screen or backgrounded,
// re-arming with one correct render on return.
//
// Everything here is created lazily on open and fully disposed on close,
// selection change, model switch, and Reset App: renderer, geometries,
// materials, listeners, observers, and the render loop.
import type * as FRAGS from "@thatopen/fragments";
import * as THREE from "three";

import { BASE_MATERIALS, PREVIEW, VIEWER_CAMERA, type GeometryRole } from "./viewerTheme";

const ORBIT_SPEED = 0.005; // rad per px dragged
const ZOOM_STEP = 0.0015;
const MIN_ZOOM = 1.15; // multiples of the fit radius
const MAX_ZOOM = 6;
/** How long after the last wheel tick the preview is still considered "moving"
 * for pixel-ratio purposes — wheel has no discrete end event, unlike drag. */
const WHEEL_SETTLE_MS = 150;

export type PreviewProfile = "balanced" | "large-model";

export class PreviewScene {
  private renderer: THREE.WebGLRenderer | null = null;
  private scene: THREE.Scene | null = null;
  private camera: THREE.PerspectiveCamera | null = null;
  private group: THREE.Group | null = null;
  private frame = 0;
  private looping = false;
  private needsRender = false;
  private disposed = false;

  private radius = 1;
  private target = new THREE.Vector3();
  private theta = Math.PI * 0.25;
  private phi = Math.PI * 0.35;
  private distance = 3;

  private dragging = false;
  private last = { x: 0, y: 0 };
  private lastInteraction = 0;
  private reducedMotion = false;
  private cleanup: Array<() => void> = [];

  private profile: PreviewProfile = "balanced";
  private rotationDeadline = 0;
  private lastAutoRotateFrameAt = 0;
  private wheelSettleTimer: ReturnType<typeof setTimeout> | null = null;
  private io: IntersectionObserver | null = null;
  private visible = true;
  private hiddenDoc = typeof document !== "undefined" ? document.hidden : false;

  constructor(private readonly container: HTMLElement) {}

  /** True once a mesh is mounted — used by tests and the panel's empty state. */
  isMounted(): boolean {
    return this.group !== null && !this.disposed;
  }

  mount(meshes: FRAGS.MeshData[], role: GeometryRole, profile: PreviewProfile = "balanced"): boolean {
    if (this.disposed) return false;
    this.teardownScene();
    this.profile = profile;

    const width = Math.max(1, this.container.clientWidth);
    const height = Math.max(1, this.container.clientHeight);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(PREVIEW.pixelRatio.stationary);
    renderer.setSize(width, height, false);
    renderer.setClearAlpha(0); // transparent — the panel surface shows through
    this.container.appendChild(renderer.domElement);
    renderer.domElement.style.display = "block";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";

    const scene = new THREE.Scene();
    scene.background = PREVIEW.background;

    // Quiet, even lighting: this is a drawing detail, not a product shot.
    scene.add(new THREE.AmbientLight(0xffffff, 2.2));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1, 2, 1.5);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.7);
    fill.position.set(-1.5, -0.5, -1);
    scene.add(fill);

    const group = new THREE.Group();
    const base = BASE_MATERIALS[role];
    const material = new THREE.MeshLambertMaterial({
      color: base.color,
      transparent: false,
      side: THREE.DoubleSide,
    });

    let mounted = 0;
    for (const mesh of meshes) {
      const geometry = this.toGeometry(mesh);
      if (!geometry) continue;
      const three = new THREE.Mesh(geometry, material);
      if (mesh.transform) three.applyMatrix4(mesh.transform);
      group.add(three);
      mounted += 1;
    }
    if (mounted === 0) {
      material.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      return false;
    }
    scene.add(group);

    const camera = new THREE.PerspectiveCamera(50, width / height, 0.01, 5000);
    camera.filmGauge = VIEWER_CAMERA.filmGaugeMm;
    camera.setFocalLength(VIEWER_CAMERA.focalLengthMm);

    this.renderer = renderer;
    this.scene = scene;
    this.camera = camera;
    this.group = group;

    this.centerAndFit(group);
    this.attachInteraction(renderer.domElement);
    this.reducedMotion = prefersReducedMotion();
    this.lastInteraction = 0;
    this.rotationDeadline = now() + PREVIEW.autoRotateLifetimeMs;
    this.lastAutoRotateFrameAt = 0;

    // Visibility gating (task18 §10): pause fully off-screen or backgrounded.
    this.io = new IntersectionObserver(
      ([entry]) => {
        const wasVisible = this.visible;
        this.visible = entry?.isIntersecting ?? true;
        if (this.visible && !wasVisible) this.requestRender();
      },
      { threshold: 0 },
    );
    this.io.observe(this.container);
    const onVisibilityChange = () => {
      const wasHidden = this.hiddenDoc;
      this.hiddenDoc = document.hidden;
      if (!this.hiddenDoc && wasHidden) this.requestRender();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    this.cleanup.push(() => document.removeEventListener("visibilitychange", onVisibilityChange));

    this.requestRender();
    return true;
  }

  /** Build a BufferGeometry from a Fragments MeshData buffer. */
  private toGeometry(mesh: FRAGS.MeshData): THREE.BufferGeometry | null {
    if (!mesh.positions || mesh.positions.length === 0) return null;
    const geometry = new THREE.BufferGeometry();
    const positions =
      mesh.positions instanceof Float32Array ? mesh.positions : new Float32Array(mesh.positions);
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    if (mesh.indices && mesh.indices.length > 0) {
      geometry.setIndex(new THREE.BufferAttribute(mesh.indices as Uint32Array, 1));
    }
    // Normals are stored as packed int16; recompute instead of guessing the
    // packing, which keeps shading correct across artifact versions.
    geometry.computeVertexNormals();
    return geometry;
  }

  /** Center the instance and frame it with a guarded, slightly enlarged fit. */
  private centerAndFit(group: THREE.Group): void {
    const box = new THREE.Box3().setFromObject(group);
    if (box.isEmpty()) return;
    box.getCenter(this.target);
    const size = new THREE.Vector3();
    box.getSize(size);
    this.radius = Math.max(size.length() / 2, 0.001);
    // Slightly enlarged, never zoomed to fill: the object keeps breathing room.
    this.distance = (this.radius / Math.tan((50 * Math.PI) / 360)) * PREVIEW.fitExpand;
    this.updateCamera();
  }

  private updateCamera(): void {
    if (!this.camera) return;
    const x = this.target.x + this.distance * Math.sin(this.phi) * Math.cos(this.theta);
    const y = this.target.y + this.distance * Math.cos(this.phi);
    const z = this.target.z + this.distance * Math.sin(this.phi) * Math.sin(this.theta);
    this.camera.position.set(x, y, z);
    this.camera.lookAt(this.target);
  }

  private attachInteraction(dom: HTMLCanvasElement): void {
    const onDown = (e: PointerEvent) => {
      this.dragging = true;
      this.last = { x: e.clientX, y: e.clientY };
      this.touch();
      this.applyPixelRatio(true);
      dom.setPointerCapture?.(e.pointerId);
    };
    const onMove = (e: PointerEvent) => {
      this.touch();
      if (!this.dragging) return;
      const dx = e.clientX - this.last.x;
      const dy = e.clientY - this.last.y;
      this.last = { x: e.clientX, y: e.clientY };
      this.theta -= dx * ORBIT_SPEED;
      this.phi = clamp(this.phi - dy * ORBIT_SPEED, 0.05, Math.PI - 0.05);
      this.updateCamera();
      this.requestRender();
    };
    const onUp = (e: PointerEvent) => {
      this.dragging = false;
      this.touch();
      this.applyPixelRatio(false);
      dom.releasePointerCapture?.(e.pointerId);
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      this.touch();
      this.applyPixelRatio(true);
      if (this.wheelSettleTimer !== null) clearTimeout(this.wheelSettleTimer);
      this.wheelSettleTimer = setTimeout(() => {
        this.wheelSettleTimer = null;
        this.applyPixelRatio(false);
      }, WHEEL_SETTLE_MS);
      const next = this.distance * (1 + e.deltaY * ZOOM_STEP);
      this.distance = clamp(next, this.radius * MIN_ZOOM, this.radius * MAX_ZOOM);
      this.updateCamera();
      this.requestRender();
    };
    const onEnter = () => this.touch();

    dom.addEventListener("pointerdown", onDown);
    dom.addEventListener("pointermove", onMove);
    dom.addEventListener("pointerup", onUp);
    dom.addEventListener("pointerleave", onUp);
    dom.addEventListener("pointerenter", onEnter);
    dom.addEventListener("wheel", onWheel, { passive: false });

    this.cleanup.push(() => {
      dom.removeEventListener("pointerdown", onDown);
      dom.removeEventListener("pointermove", onMove);
      dom.removeEventListener("pointerup", onUp);
      dom.removeEventListener("pointerleave", onUp);
      dom.removeEventListener("pointerenter", onEnter);
      dom.removeEventListener("wheel", onWheel);
    });
  }

  /** Mark a fresh interaction; auto-rotation stays paused until idle again. */
  private touch(): void {
    this.lastInteraction = now();
    this.requestRender();
  }

  /** Preview renderer pixel ratio (task18 §10): 1.0 while actively dragging
   * or wheel-zooming, 1.25 otherwise (including while auto-rotating — a slow
   * ambient effect, not "motion" in the interaction sense the policy targets). */
  private applyPixelRatio(moving: boolean): void {
    if (!this.renderer) return;
    const target = moving ? PREVIEW.pixelRatio.moving : PREVIEW.pixelRatio.stationary;
    if (this.renderer.getPixelRatio() === target) return;
    this.renderer.setPixelRatio(target);
    this.requestRender();
  }

  /** Auto-rotation runs only when idle, not hovered/dragged, motion allowed,
   * visible, and within its finite lifetime (task18 §10). */
  private shouldAutoRotate(): boolean {
    if (this.reducedMotion || this.dragging) return false;
    if (!this.visible || this.hiddenDoc) return false;
    if (now() > this.rotationDeadline) return false;
    if (this.lastInteraction === 0) return true;
    return now() - this.lastInteraction > PREVIEW.resumeIdleMs;
  }

  /** Request a render and (re)start the RAF chain if it isn't already running. */
  private requestRender(): void {
    this.needsRender = true;
    if (this.looping || this.disposed || !this.renderer) return;
    if (!this.visible || this.hiddenDoc) return; // re-armed by IO/visibilitychange callbacks
    this.looping = true;
    this.frame = requestAnimationFrame(this.loop);
  }

  private loop = (): void => {
    if (this.disposed || !this.renderer || !this.scene || !this.camera) {
      this.looping = false;
      return;
    }
    if (!this.visible || this.hiddenDoc) {
      this.looping = false; // stop the chain entirely; re-armed on return
      return;
    }

    const rotating = this.shouldAutoRotate();
    if (rotating) {
      const cap =
        this.profile === "large-model" ? PREVIEW.autoRotateFpsCap.largeModel : PREVIEW.autoRotateFpsCap.balanced;
      const minIntervalMs = 1000 / cap;
      const nowTs = now();
      if (nowTs - this.lastAutoRotateFrameAt >= minIntervalMs) {
        this.theta += PREVIEW.autoRotateSpeed * 0.01;
        this.updateCamera();
        this.needsRender = true;
        this.lastAutoRotateFrameAt = nowTs;
      }
    }

    if (this.needsRender) {
      this.renderer.render(this.scene, this.camera);
      this.needsRender = false;
    }

    // Keep the chain alive only while there's an active reason to; otherwise
    // stop (task18 §10 "no-motion renders once then stops") — requestRender()
    // restarts it on the next real interaction/visibility change.
    if (this.dragging || rotating || this.needsRender) {
      this.frame = requestAnimationFrame(this.loop);
    } else {
      this.looping = false;
    }
  };

  resize(): void {
    if (!this.renderer || !this.camera) return;
    const width = Math.max(1, this.container.clientWidth);
    const height = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.setFocalLength(VIEWER_CAMERA.focalLengthMm);
    this.camera.updateProjectionMatrix();
    this.requestRender();
  }

  /** Dispose geometries/materials/renderer/listeners/observers and stop the render loop. */
  private teardownScene(): void {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.looping = false;
    if (this.wheelSettleTimer !== null) {
      clearTimeout(this.wheelSettleTimer);
      this.wheelSettleTimer = null;
    }
    this.io?.disconnect();
    this.io = null;
    this.cleanup.forEach((fn) => {
      try {
        fn();
      } catch {
        // ignore
      }
    });
    this.cleanup = [];

    if (this.group) {
      this.group.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        mesh.geometry?.dispose?.();
        const mat = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else mat?.dispose?.();
      });
      this.group.removeFromParent();
      this.group = null;
    }
    if (this.renderer) {
      try {
        this.renderer.dispose();
        this.renderer.forceContextLoss?.();
        this.renderer.domElement.remove();
      } catch {
        // ignore
      }
      this.renderer = null;
    }
    this.scene = null;
    this.camera = null;
  }

  dispose(): void {
    this.teardownScene();
    this.disposed = true;
  }
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

function now(): number {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

export function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  } catch {
    return false;
  }
}
