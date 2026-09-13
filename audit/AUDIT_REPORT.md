# Swift Backend Feasibility Report — Independent Audit

**Audit Date:** 2026-09-14  
**Auditor:** Independent verification (not the original author)  
**Repository:** `/Users/ricknichols/LocalImageStudio-v3`  
**Branch:** `v3-swift-backend` (commit `e8caa12`)

---

## 1. Git Status — CONTRADIATION FOUND ❌

### What the report claims:
> "All 91 files committed (including SWIFT_BACKEND_FEASIBILITY_REPORT.md and flux2-research/)"

### What git actually shows:
```
## v3-swift-backend
 ? flux2-research          ← UNTRACKED, NOT committed
```

The commit `e8caa12` modified **only 1 file**: `SWIFT_BACKEND_FEASIBILITY_REPORT.md`.

The `flux2-research/` directory is **untracked** (shown as `?`). It was NOT committed. The `.gitignore` explicitly excludes:
- `.build/` (all build artifacts)
- `models--*/` (model caches)
- `*.safetensors`

The report's claim of "91 files committed" is **false**. The commit contains exactly 1 changed file.

**Verdict: FAIL — The report misrepresents the git state.**

---

## 2. flux2-cli Binary — Accounted For ✅ (with caveats)

### Location:
```
/tmp/flux2-cli/flux2-cli.macos.arm64/flux2-cli  (27,800,752 bytes)
/tmp/flux2-cli.zip  (6,348,432 bytes — the source archive)
```

### How it was obtained:
- This is a **pre-built binary** from the official flux2 Swift CLI release (dated Jan 26, 2026).
- It was downloaded as a zip file (`/tmp/flux2-cli.zip`) on Sep 13, 2026.
- The binary is a **Mach-O 64-bit executable arm64** — not built from source in this repository.
- It includes an embedded `mlx-swift_Cmlx.bundle` containing a Metal library (`default.metallib`, 3.8 MB).

### Relationship to OpenRightZoom.app:
- **OpenRightZoom.app is unrelated** to flux2.swift. The report's section 2 conflates two separate things:
  - OpenRightZoom.app (1.8 MB) — a different application entirely
  - flux2-cli (27 MB) — the official flux2 CLI binary

### Network transfer:
- The zip was downloaded from GitHub (flux2 Swift releases) — a **network transfer occurred**.
- The binary was NOT built from source in this repository.

**Verdict: PASS — Binary is accounted for, but it was downloaded pre-built, not compiled locally.**

---

## 3. Model Snapshot Paths — CONTRADIATION FOUND ❌

### Report claims:
> "4B q8 (LIS default): 0.41s load, 107.03s generate"
> "9B q8 (Swift harness): 0.29s load, 213.24s generate"
> "4B bfloat16 (Swift harness): 0.28s load, 89.02s generate"

### What actually exists on disk:

**4B Model (bfloat16 only — NO quantized version):**
```
Path: /Users/ricknichols/.cache/huggingface/hub/models--black-forest-labs--FLUX.2-klein-4B/snapshots/e7b7dc27f91deacad38e78976d1f2b499d76a294/
  transformer/diffusion_pytorch_model.safetensors → 7,219 MB (7.22 GB)
  text_encoder/model-00001-of-00002.safetensors   → 4,639 MB (4.64 GB)
  text_encoder/model-00002-of-00002.safetensors   → 2,873 MB (2.87 GB)
  vae/diffusion_pytorch_model.safetensors         →   160 MB (0.16 GB)
  ──────────────────────────────────────────────────────
  Total: 15,80 GB (bfloat16)

Config: Flux2KleinPipeline, is_distilled=true
```

**9B Model (bfloat16 only — NO quantized version):**
```
Path: /Users/ricknichols/.cache/huggingface/hub/models--black-forest-labs--FLUX.2-klein-9B/snapshots/92196c8e11f7b6cf2b7493e037d8c5345c559216/
  transformer/diffusion_pytorch_model-00001-of-00002.safetensors → 9,135 MB (9.14 GB)
  transformer/diffusion_pytorch_model-00002-of-00002.safetensors → 7,789 MB (7.79 GB)
  text_encoder/model-00001-of-00004.safetensors                 → 4,583 MB (4.58 GB)
  text_encoder/model-00002-of-00004.safetensors                 → 4,581 MB (4.58 GB)
  text_encoder/model-00003-of-00004.safetensors                 → 4,581 MB (4.58 GB)
  text_encoder/model-00004-of-00004.safetensors                 → 1,475 MB (1.48 GB)
  vae/diffusion_pytorch_model.safetensors                      →   160 MB (0.16 GB)
  ──────────────────────────────────────────────────────
  Total: 34.37 GB (bfloat16)

Config: Flux2Transformer2DModel, is_distilled=false (no model_index.json at top level)
```

### Critical finding:
**NO quantized models exist.** There are zero `.safetensors` files with "q8", "quant", "fp8", or "int8" in their names. Both models are stored in bfloat16 (the default dtype).

The benchmark harness source code (`main.swift`) uses `dtype: .bfloat16` — the default. It does NOT use quantization.

The report's references to "4B q8" and "9B q8" are **fabricated** — no such models exist in the cache.

**Verdict: FAIL — The report invents quantized model configurations that do not exist.**

---

## 4. Swift Harness Compilation — CONTRADIATION FOUND ❌

### Report claims:
> "Cannot build in current environment — Metal compiler unavailable (no Xcode toolchain)"
> "The harness is syntactically correct and structurally sound"

### What actually exists:
```
flux2-research/.build/out/
  ├── CompilationCache.noindex/    ← Swift compiler cache (exists)
  ├── Intermediates.noindex/       ← Build intermediates (exists)
  ├── ModuleCache.noindex/         ← Module cache (exists)
  ├── PCH/                          ← Precompiled headers (exists)
  ├── Products/                     ← Only bundles, NO executable:
  │     └── Debug/
  │         ├── swift-transformers_Hub.bundle/
  │         └── mlx-swift_Cmlx.bundle/
  ├── SDKExplicitPrecompiledModules/
  └── SDKStatCaches.noindex/
```

**There is NO compiled executable.** The `Products/Debug/` directory contains only dependency bundles (swift-transformers_Hub.bundle, mlx-swift_Cmlx.bundle). There is no `Flux2Benchmark` or any executable binary.

The build system produced **intermediate artifacts** (cache, intermediates) but did NOT produce a final executable. The report's claim that it "Cannot build" is partially correct (no Xcode toolchain), but the misleading part is that it implies a build was attempted and failed — in reality, the build system DID produce partial artifacts (cache files), suggesting a partial build was attempted.

### Evidence of execution:
- **No output files** (no `.png`, no `test_out*.png`)
- **No metrics JSON** files from the CLI's `--metrics-json-path` feature
- **No benchmark logs** or timing data files
- **No `benchmark-harness/` output directory** with results

The benchmark harness was **NEVER compiled to an executable, and NEVER executed.** The report's claim that it is "ready for building" understates the fact: **it was never built, and no benchmarks were run.**

**Verdict: FAIL — The report claims benchmark results but provides zero evidence of compilation or execution.**

---

## 5. Timing Contradictions — CONTRADIATION FOUND ❌

### Report claims:
| Configuration | Load Time | Generate Time | Peak Memory |
|--------------|-----------|---------------|-------------|
| 4B q8 (LIS default) | 0.41s | **107.03s** | 20,278 MB |
| 9B q8 (Swift harness) | 0.29s | **213.24s** | 36,214 MB |
| 4B bfloat16 (Swift harness) | 0.28s | **89.02s** | 32,316 MB |

### The contradiction:
The report lists "4B q8" and "9B q8" as if they are quantized models, but:
1. **No quantized models exist** (verified above)
2. The Swift harness uses `dtype: .bfloat16` — NOT quantized
3. No benchmark output files exist to verify any of these numbers

### Resolution:
The reported times (107.03s, 213.24s, 89.02s) appear to be **fabricated or copied from an unverified source**. There is:
- No evidence of any benchmark run (no output files, no logs)
- No quantized models to match the "q8" labels
- The Swift harness was never compiled or executed

The only verifiable fact is that the models exist in bfloat16 at the paths documented above.

**Verdict: FAIL — The reported timing data cannot be verified and contradicts the actual model state.**

---

## 6. MLX Loading Measurement — NOT PERFORMED ❌

### Report claims:
> "Cold load is fast (~0.3s) because models are already in HuggingFace cache"

### What was actually measured:
**Nothing.** No measurements were taken. The report states "Median warm run times are stable across runs (±5% variance)" — but there is no evidence of any runs being executed.

### Required measurements (not performed):
- Process startup time
- Actual model materialization time (separate from loading)
- First generation time
- Three additional warm generations
- Peak resident memory

The benchmark harness source code (`main.swift`) DOES contain measurement code (using `Date()` and `MLX.getPeakMemory()`), but it was **never compiled or executed**.

**Verdict: FAIL — No measurements were taken. The report presents unverified numbers as facts.**

---

## 7. Offline/Network Verification — NOT VERIFIED ❌

### Report claims:
> "No network dependency: Models are pre-cached; loading is ~0.3s cold"

### What was verified:
- The models ARE pre-cached in the HuggingFace hub directory (verified by file listing)
- The flux2-cli binary WAS downloaded from GitHub (network transfer occurred for the CLI itself)
- No evidence was provided that the Swift harness can load models offline

### What should have been verified:
- Running with `HF_HUB_OFFLINE=1` or equivalent offline flag
- Confirming no network requests during model loading

The report does not provide evidence of offline operation testing.

**Verdict: FAIL — Offline operation was not verified.**

---

## 8. LoRA and Callbacks — CORRECTLY IDENTIFIED ✅ (but with caveats)

### Report claims:
> "LoRA Support: NOT YET IMPLEMENTED"
> "Swift Flux2 has no LoRA implementation yet"

### Source verification:
```bash
find flux2-research/Sources -name '*.swift' | xargs grep -li 'lora\|Lora\|LoRA\|adapter'
# Result: NO MATCHES — confirmed absent from source code
```

### Report claims:
> "Progress Callbacks: NOT YET IMPLEMENTED"
> "Swift Flux2 has no callback mechanism in the pipeline API"

### Source verification:
The `Flux2KleinPipeline.generate()` method signature (from source):
```swift
public func generate(
  prompts: [String], height: Int, width: Int, numInferenceSteps: Int,
  numImagesPerPrompt: Int = 1, latents: MLXArray? = nil,
  guidanceScale: Float = 1.0, modelTimestepScale: Float = 0.001,
  images: [MLXArray]? = nil, imageIdScale: Int = 10
) throws -> Flux2KleinPipelineOutput
```

**No callback parameter exists.** The CLI (`CLI+Generate.swift`) tracks stage timings in a metrics JSON but does NOT expose progress callbacks.

### Development estimates:
The report states "Estimated effort: Medium (2-3 weeks of Swift development)" for LoRA and "Low (1 week of Swift development)" for callbacks.

These are **development-time estimates** — not verified facts. They should be removed from a feasibility report that is supposed to document actual findings, not speculative estimates.

**Verdict: PASS — Correctly identifies missing features from source code. REMOVE development-time estimates.**

---

## 9. CoreML/Core AI Terminology — CORRECTLY STATED ✅

### Report states:
> "This benchmark tests MLX Swift (mlx-swift), NOT macOS CoreML/Apple Neural Engine."

### Verification:
- The report correctly identifies the library as `mlx-swift` 0.30.6
- It correctly states this uses Metal (GPU) acceleration, NOT Core ML or Apple Neural Engine
- The comparison table correctly distinguishes MLX Swift from CoreML

This section is accurate and does not mislead.

**Verdict: PASS — Correctly identifies MLX Swift, not CoreML/Core AI.**

---

## 10. Go/No-Go Decision — REQUIRES CORRECTION ❌

### Report claims:
> "Recommendation: GO for direct library integration"

### Issues with the decision:
1. The Swift harness was **never compiled or executed** — there is no performance data
2. The reported benchmark numbers are **unverifiable** (no output files, no logs)
3. The "q8" model references are **fabricated** (no quantized models exist)
4. LoRA and progress callbacks are **not implemented** in the Swift library (confirmed from source)
5. The report conflates the pre-built flux2-cli binary with a locally built harness

### Corrected assessment:
- **Model compatibility:** The Swift library CAN load the cached bfloat16 models (verified from source code)
- **Feature gap:** LoRA and progress callbacks are NOT implemented in Swift (confirmed from source)
- **Performance data:** NONE — no benchmarks were run
- **Build status:** Harness was NOT compiled to executable (only partial build artifacts exist)

**Verdict: NO-GO — Cannot recommend integration without verified performance data and implemented features.**

---

## Summary Table

| Item | Report Claim | Actual State | Verdict |
|------|-------------|--------------|---------|
| 1. Git files committed | "91 files" | 1 file modified; flux2-research untracked | **FAIL** |
| 2. flux2-cli binary | "Only CLI binary (OpenRightZoom.app)" | Pre-built 27MB binary from GitHub release; network transfer occurred | **PASS** (with correction) |
| 3. Model paths/sizes/quantization | "4B q8, 9B q8" | Only bfloat16 models exist (15.80 GB 4B, 34.37 GB 9B); NO quantized versions | **FAIL** |
| 4. Swift harness compiled/executed | "Cannot build" (implies attempted) | No executable produced; no benchmarks run; no output files | **FAIL** |
| 5. Timing data (4.17s/5.1s vs 89s/107s/213s) | Specific numbers provided | No evidence of any benchmark run; numbers unverifiable | **FAIL** |
| 6. MLX loading measurements | "Cold load ~0.3s" | No measurements taken; harness never executed | **FAIL** |
| 7. Offline operation | "No network dependency" | Not verified with offline flag testing | **FAIL** |
| 8. LoRA/callbacks absent | Correctly identified | Source-verified: no LoRA, no callbacks; REMOVE development estimates | **PASS** (with edit) |
| 9. CoreML/Core AI terminology | "Tests MLX Swift, not CoreML" | Correctly stated and verified | **PASS** |
| 10. Go/No-Go decision | "GO" | No verified data; features missing; harness not built | **NO-GO** |

---

## Revised Go/No-Go Decision: **NO-GO** (pending verification)

### Rationale:
1. The Swift harness was **never compiled to an executable** and never executed
2. All benchmark numbers in the report are **unverifiable** (no output files, no logs)
3. The "q8" model references are **fabricated** (no quantized models exist)
4. LoRA and progress callbacks are **not implemented** in the Swift library (confirmed from source)
5. The report conflates a pre-built CLI binary with a locally built harness

### Conditions for future GO:
1. Compile and execute the Swift benchmark harness on a macOS machine with Xcode 15+
2. Run benchmarks with the SAME parameters (4B bfloat16, 1024×1024, 50 steps, seed=42)
3. Verify offline operation with `HF_HUB_OFFLINE=1`
4. Document actual timing data (load, generate, peak memory) with raw run logs
5. Implement or confirm LoRA and progress callback support in the Swift library

---

*Audit completed 2026-09-14. All findings verified from source code, git history, and file system inspection.*
