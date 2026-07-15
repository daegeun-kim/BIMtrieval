/**
 * One-time IFC -> Fragments preparation tool (spec_v006 §9.2, Task 11 Phase 4).
 *
 * Usage (from frontend/):
 *   npm run prepare:model -- --input "<path to .ifc>" --model-id 1 [--force] [--check-guid <IFC GlobalId>]
 *
 * Behavior:
 *  - reads a local IFC file (never modifies it);
 *  - computes its SHA-256 fingerprint (the same scheme ingestion stores in
 *    ifc_source_models.file_fingerprint, so the backend derives the same name);
 *  - converts to Fragments with the SAME @thatopen/fragments version family the
 *    viewer uses;
 *  - writes atomically (tmp file + rename) to
 *      <repo>/model_assets/{model-id}/{fingerprint}.frag
 *    refusing to overwrite an existing validated artifact unless --force;
 *  - validates the artifact after conversion by re-loading it single-threaded
 *    and sampling identity mappings (optionally checking a known GlobalId);
 *  - writes a small sidecar .meta.json with format/library versions.
 *
 * It never touches PostgreSQL, never imports backend/ingestion code, and is
 * never executed by `npm run dev` or any backend request.
 */
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

import * as FRAGS from "@thatopen/fragments";

const require = createRequire(import.meta.url);

const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..");
const ASSET_ROOT = path.join(REPO_ROOT, "model_assets");
const ARTIFACT_SUFFIX = ".frag";

interface Args {
  input: string;
  modelId: number;
  force: boolean;
  checkGuid: string | null;
  outputRoot: string;
}

function parseArgs(argv: string[]): Args {
  const get = (flag: string): string | null => {
    const i = argv.indexOf(flag);
    return i >= 0 && argv[i + 1] ? argv[i + 1]! : null;
  };
  const input = get("--input");
  const modelIdRaw = get("--model-id");
  if (!input || !modelIdRaw) {
    console.error(
      'Usage: npm run prepare:model -- --input "<file.ifc>" --model-id <n> [--force] [--check-guid <GlobalId>] [--output-root <dir>]',
    );
    process.exit(2);
  }
  const modelId = Number(modelIdRaw);
  if (!Number.isInteger(modelId) || modelId <= 0) {
    console.error(`--model-id must be a positive integer, got ${modelIdRaw}`);
    process.exit(2);
  }
  return {
    input: path.resolve(input),
    modelId,
    force: argv.includes("--force"),
    checkGuid: get("--check-guid"),
    outputRoot: path.resolve(get("--output-root") ?? ASSET_ROOT),
  };
}

/** Containment guard: the resolved output must stay under the asset root. */
function containedJoin(root: string, ...segments: string[]): string {
  const joined = path.resolve(root, ...segments);
  const rel = path.relative(path.resolve(root), joined);
  if (rel.startsWith("..") || path.isAbsolute(rel)) {
    throw new Error("output path escapes the asset root — refusing");
  }
  return joined;
}

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

async function convert(ifcBytes: Uint8Array): Promise<Uint8Array> {
  const importer = new FRAGS.IfcImporter();
  // Use the locally installed web-ifc WASM (same version family as the viewer);
  // no network access during conversion. web-ifc blocks package.json resolution
  // through its exports map, so resolve the entry module and take its directory.
  const wasmDir = path.dirname(require.resolve("web-ifc"));
  importer.wasm = { absolute: true, path: wasmDir + path.sep };

  let lastShown = -1;
  const fragmentBytes = await importer.process({
    bytes: ifcBytes,
    progressCallback: (progress: number) => {
      const pct = Math.floor(progress * 100);
      if (pct >= lastShown + 10) {
        lastShown = pct;
        console.log(`  conversion ${pct}%`);
      }
    },
  });
  return new Uint8Array(fragmentBytes as ArrayBuffer | Uint8Array as ArrayBuffer);
}

/** Re-load the artifact single-threaded and sample identity mappings. */
async function validateArtifact(bytes: Uint8Array, checkGuid: string | null): Promise<void> {
  if (bytes.byteLength < 128) throw new Error("artifact suspiciously small — validation failed");

  // Single-threaded model avoids the browser worker in Node.
  const AnyFrags = FRAGS as unknown as Record<string, unknown>;
  const Single = AnyFrags["SingleThreadedFragmentsModel"] as
    | (new (id: string, bytes: Uint8Array) => {
        getItemsWithGeometry?: () => Promise<unknown[]>;
        getGuidsByLocalIds?: (ids: number[]) => Promise<(string | null)[]>;
        getLocalIdsByGuids?: (guids: string[]) => Promise<(number | null)[]>;
        getItemsByQuery?: unknown;
        dispose?: () => void;
      })
    | undefined;

  if (!Single) {
    console.warn("  ! SingleThreadedFragmentsModel unavailable — structural validation only");
    return;
  }
  const model = new Single("validation", bytes);
  try {
    if (checkGuid && model.getLocalIdsByGuids) {
      const [localId] = await model.getLocalIdsByGuids([checkGuid]);
      if (typeof localId !== "number") {
        throw new Error(`identity validation failed: GlobalId ${checkGuid} not found in artifact`);
      }
      console.log(`  identity check OK: ${checkGuid} -> localId ${localId}`);
      if (model.getGuidsByLocalIds) {
        const [roundTrip] = await model.getGuidsByLocalIds([localId]);
        if (roundTrip !== checkGuid) throw new Error("identity round-trip mismatch");
        console.log("  identity round-trip OK");
      }
    } else {
      console.log("  no --check-guid given; skipped GlobalId identity sample");
    }
  } finally {
    model.dispose?.();
  }
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const t0 = Date.now();

  console.log(`Reading IFC: ${path.basename(args.input)}`);
  const ifcBytes = new Uint8Array(await readFile(args.input));
  const fingerprint = sha256(ifcBytes);
  console.log(`  size ${(ifcBytes.byteLength / 1e6).toFixed(1)} MB, sha256 ${fingerprint}`);

  const outDir = containedJoin(args.outputRoot, String(args.modelId));
  const outPath = containedJoin(args.outputRoot, String(args.modelId), `${fingerprint}${ARTIFACT_SUFFIX}`);
  const tmpPath = `${outPath}.tmp-${process.pid}`;

  if (existsSync(outPath) && !args.force) {
    const s = await stat(outPath);
    console.log(`Artifact already exists (${(s.size / 1e6).toFixed(1)} MB): ${path.relative(REPO_ROOT, outPath)}`);
    console.log("Use --force to reconvert. Nothing to do.");
    return;
  }

  console.log("Converting IFC -> Fragments (single process)…");
  let fragBytes: Uint8Array;
  try {
    fragBytes = await convert(ifcBytes);
  } catch (err) {
    await rm(tmpPath, { force: true });
    throw err;
  }
  console.log(`  fragments size ${(fragBytes.byteLength / 1e6).toFixed(1)} MB`);

  console.log("Validating artifact…");
  await validateArtifact(fragBytes, args.checkGuid);

  await mkdir(outDir, { recursive: true });
  await writeFile(tmpPath, fragBytes);
  await rename(tmpPath, outPath);

  const meta = {
    source_file_name: path.basename(args.input),
    source_fingerprint: fingerprint,
    source_model_id: args.modelId,
    artifact_bytes: fragBytes.byteLength,
    fragments_version: readPkgVersion("@thatopen/fragments"),
    web_ifc_version: readPkgVersion("web-ifc"),
    created_at: new Date().toISOString(),
  };
  await writeFile(`${outPath}.meta.json`, JSON.stringify(meta, null, 2));

  console.log(`Done in ${((Date.now() - t0) / 1000).toFixed(1)}s -> ${path.relative(REPO_ROOT, outPath)}`);
}

function readPkgVersion(name: string): string {
  // Some packages (web-ifc) block `<pkg>/package.json` via their exports map;
  // walk up from the resolved entry file instead.
  try {
    let dir = path.dirname(require.resolve(name));
    for (let i = 0; i < 4; i++) {
      const candidate = path.join(dir, "package.json");
      if (existsSync(candidate)) {
        const pkg = JSON.parse(readFileSyncUtf8(candidate)) as { name?: string; version?: string };
        if (pkg.name === name && pkg.version) return pkg.version;
      }
      dir = path.dirname(dir);
    }
  } catch {
    // fall through
  }
  return "unknown";
}

function readFileSyncUtf8(p: string): string {
  // small local helper to keep imports tidy

  const { readFileSync } = require("node:fs") as typeof import("node:fs");
  return readFileSync(p, "utf8");
}

main().catch(async (err) => {
  console.error(`FAILED: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
