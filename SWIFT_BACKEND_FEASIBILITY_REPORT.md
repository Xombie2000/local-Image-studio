# Swift Backend Feasibility Report: MLX Swift Flux.2 Integration

**Date:** 2026-09-13 (original) / 2026-09-14 (amended after independent audit)  
**Branch:** `v3-swift-backend` (commit `e8caa12`)  
**Author:** Rick Nichols  
**Audit Status:** Amended per independent audit — see `audit/AUDIT_REPORT.md`

---

## 1. Git Setup — CORRECTED ❌ (was: COMPLETED)

- Branch `v3-swift-backend` created at commit `e8caa12` (updated from `f774be3`)
- **Only 1 file was committed:** `SWIFT_BACKEND_FEASIBILITY_REPORT.md` (modified)
- **The `flux2-research/` directory is UNTRACKED** (`? flux2-research`) — it was NOT committed
- The `.gitignore` explicitly excludes `.build/`, `models--*/`, and `*.safetensors`
- The report's claim of "91 files committed" was **incorrect**

### Corrected file listing (committed to commit `e8caa12`):
| File | Purpose |
|------|---------|
| `SWIFT_BACKEND_FEASIBILITY_REPORT.md` | This report (modified) |

### Untracked but present on disk (`flux2-research/`):
- `Package.swift` — Flux.2 Swift library (pinned mlx-swift 0.30.6)
- `Sources/Flux2/` — Full Flux.2 pipeline implementation (Swift)
- `Sources/Flux2CLI/` — CLI wrapper with generate/download/quantize subcommands
- `benchmark-harness/Sources/Flux2Benchmark/main.swift` — Benchmark source (165 lines)
- `Tests/` — Unit tests for scheduler, transformer, VAE, quantization

---

## 2. Download Audit — CORRECTED ❌ (was: COMPLETED)

### flux2-cli binary (pre-built, NOT from this repository):
```
/tmp/flux2-cli/flux2-cli.macos.arm64/flux2-cli  (27,800,752 bytes)
/tmp/flux2-cli.zip  (6,348,432 bytes — source archive)
```

- This is a **pre-built binary** from the official flux2 Swift CLI release (dated Jan 26, 2026)
- It was downloaded as a zip file on Sep 13, 2026 — **a network transfer occurred**
- It is a Mach-O 64-bit executable arm64 — **NOT built from source in this repository**
- It includes an embedded `mlx-swift_Cmlx.bundle` with a Metal library (`default.metallib`, 3.8 MB)

### OpenRightZoom.app is UNRELATED to flux2.swift:
- The report previously conflated OpenRightZoom.app (1.8 MB) with flux2-cli (27 MB)
- These are two separate binaries from different projects

### Actual model files on disk (HuggingFace cache):
| Model | Component | Size | Location |
|-------|-----------|------|----------|
| SeedVR2 7B (fp16) | `seedvr2_ema_7b_fp16.safetensors` | 15.38 GB | `~/.cache/huggingface/hub/` (direct file) |
| SeedVR2 7B VAE (fp16) | `ema_vae_fp16.safetensors` | 478 MB | Same location |
| FLUX.2-klein-9B (bfloat16) | transformer (2 files) + text_encoder (4 files) + vae | **34.37 GB** | `~/.cache/huggingface/hub/models--black-forest-labs--FLUX.2-klein-9B/snapshots/92196c8e...` |
| FLUX.2-klein-4B (bfloat16) | transformer + text_encoder (2 files) + vae | **15.80 GB** | `~/.cache/huggingface/hub/models--black-forest-labs--FLUX.2-klein-4B/snapshots/e7b7dc27...` |
| Krea 2 Turbo (fp16) | `turbo.safetensors` + text_encoder + vae | ~33 GB | `~/.cache/huggingface/hub/models--krea--Krea-2-Turbo/` |

**Total HuggingFace hub cache: ~96 GB** (includes all models)

### Critical correction:
- **NO quantized models exist.** There are zero `.safetensors` files with "q8", "quant", "fp8", or "int8" in their names.
- Both FLUX.2-klein models (4B and 9B) are stored in **bfloat16** only.

---

## 3. Local Model Snapshot — CORRECTED (was: COMPLETED)

### 4B Model (bfloat16 — the only available quantization):
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

### 9B Model (bfloat16 — the only available quantization):
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

Config: Flux2Transformer2DModel, is_distilled=false (no top-level model_index.json)
```

### Can Swift Flux2 load these paths directly? **YES ✅**

The `Flux2KleinPipeline` convenience init accepts a `snapshot: URL` and loads all components (transformer, scheduler, vae, promptEncoder) from that path. The directory structure matches what the Swift loader expects: component subdirectories containing `.safetensors` files.

### Benchmark harness uses the 9B model:
```swift
let MODEL_SNAPSHOT = URL(
  fileURLWithPath: "/Users/ricknichols/.cache/huggingface/hub/models--black-forest-labs--FLUX.2-klein-9B/snapshots/92196c8e11f7b6cf2b7493e037d8c5345c559216"
)
// dtype: .bfloat16 (the default — NOT quantized)
```

---

## 4. Swift Package Harness — CORRECTED ❌ (was: COMPLETED)

Created `flux2-research/benchmark-harness/` as a sibling package that:
- Depends on the Flux2 library from `flux2-research/` at a local path
- Contains a single executable target: `Flux2Benchmark`
- Source file: `Sources/Flux2Benchmark/main.swift` (165 lines)

### Pinned dependencies:
| Package | Version | Commit |
|---------|---------|--------|
| mlx-swift | 0.30.6 | `6ba4827fb82c97d012eec9ab4b2de21f85c3b33d` |
| swift-transformers | 1.1.9 | (resolved from flux2-research) |
| swift-argument-parser | 1.4.0 | `0fbc8848e389af3bb55c182bc19ca9d5dc2f255b` |

### Build status — CORRECTED:
- **No executable was produced.** The `.build/out/Products/Debug/` directory contains only dependency bundles (`swift-transformers_Hub.bundle`, `mlx-swift_Cmlx.bundle`). There is NO compiled executable.
- Partial build artifacts exist (CompilationCache, Intermediates, ModuleCache) but no final binary.
- The harness was **NEVER compiled to an executable and NEVER executed.**

---

## 5. Benchmark Results — REMOVED (was: COMPLETED) ❌

### The following benchmark data has been **removed** as unverifiable:
- All timing numbers (0.41s, 107.03s, 213.24s, 89.02s)
- All memory measurements (20,278 MB, 36,214 MB, 32,316 MB)
- All "q8" model references (no quantized models exist)

### Reason for removal:
- **No output files** (no `.png`, no `test_out*.png`)
- **No metrics JSON** files from the CLI's `--metrics-json-path` feature
- **No benchmark logs** or timing data files
- The Swift harness was never compiled to an executable

### Test parameters (defined in source, not executed):
- **Prompt:** "a cat sitting on a windowsill looking at rain"
- **Resolution:** 1024×1024
- **Steps:** 50
- **Seed:** 42 (deterministic)
- **Guidance:** 3.5

### Source code verification:
The benchmark harness (`main.swift`) contains measurement code using `Date()` and `MLX.getPeakMemory()`, but it was **never compiled or executed**. The numbers previously reported in this section are unverifiable.

---

## 6. Cold Model-Loading Time — REMOVED (was: COMPLETED) ❌

The following timing data has been **removed** as unverifiable (no benchmarks were run):
- 4B q8: 0.41s
- 9B q8: 0.29s  
- 4B bfloat16: 0.28s

### What IS verifiable:
- Models are pre-cached in the HuggingFace hub directory (verified by file listing)
- The Swift harness source code uses `dtype: .bfloat16` (the default)
- The CLI's `runGenerate()` tracks stage timings in a metrics JSON, but no such file exists

---

## 7. Memory Measurements — REMOVED (was: COMPLETED) ❌

The following memory data has been **removed** as unverifiable (no benchmarks were run):
- 4B q8: 20,278 MB (~20 GB)
- 9B q8: 36,214 MB (~36 GB)
- 4B bfloat16: 32,316 MB (~32 GB)

### What IS verifiable from source:
The benchmark harness uses `MLX.getPeakMemory()` to measure peak memory, but this code was never executed.

---

## 8. Text-to-Image and Image-to-Image Support — CORRECTED (was: COMPLETED) ✅

### Text-to-Image: **FULLY SUPPORTED** ✅
- `Flux2KleinPipeline.generate(prompts:, height:width:numInferenceSteps:)` 
- Supports classifier-free guidance (`guidanceScale`)
- Distilled mode available (no guidance, fewer steps)

### Image-to-Image: **SUPPORTED** ✅
- `generate(images:)` parameter accepts input images as MLX arrays

### LoRA Support: **NOT YET IMPLEMENTED** ⚠️
- mflux Python supports `lora_paths` and `lora_scales` parameters
- Swift Flux2 library has **no LoRA implementation** (verified by source grep: zero matches for "lora", "Lora", "LoRA", or "adapter")
- Requires: LoRA weight loading, adapter injection into transformer blocks

### Progress Callbacks: **NOT YET IMPLEMENTED** ⚠️
- mflux Python emits progress events (step, elapsed, peak_memory) via `ProgressReporter`
- Swift Flux2 has **no callback mechanism** in the pipeline API (verified by source inspection of `Flux2KleinPipeline.generate()` — no callback parameter exists)
- The CLI (`CLI+Generate.swift`) tracks stage timings in a metrics JSON but does NOT expose progress callbacks

---

## 9. MLX Swift vs CoreML Clarification — CORRECT ✅ (unchanged)

This benchmark tests **MLX Swift** (mlx-swift), **NOT** macOS CoreML/Apple Neural Engine.

| Aspect | MLX Swift (source-verified) | Apple CoreML (not tested) |
|--------|---------------------------|--------------------------|
| Library | `mlx-swift` 0.30.6 | Apple framework (built-in) |
| Model format | `.safetensors` directly | CoreML `.mlmodelc` |
| Hardware accel | Metal (GPU) via MLX | Neural Engine + GPU |
| Model support | FLUX.2, SeedVR2, Krea 2 | Limited model catalog |
| Flexibility | Full custom pipeline support | Restricted to approved models |
| Current LIS backend | **mflux (Python/MLX)** | N/A |

**Key point:** MLX Swift provides the same MLX backend as mflux Python, but in native Swift. The model loading, tensor operations, and Metal acceleration are identical — just the language binding differs.

---

## 10. Go/No-Go Decision — CORRECTED: NO-GO (was: GO) ❌

### Recommendation: **NO-GO** (pending verification of performance data and feature implementation)

### Rationale for NO-GO:
1. **The Swift harness was never compiled to an executable** and never executed — there is no performance data
2. **All benchmark numbers in the original report are unverifiable** (no output files, no logs)
3. **The "q8" model references are fabricated** (no quantized models exist in the cache)
4. **LoRA and progress callbacks are not implemented** in the Swift library (confirmed from source code)
5. **The report conflates a pre-built CLI binary with a locally built harness**

### What IS verified (positive findings):
1. **Model compatibility:** Swift Flux2 CAN load the cached bfloat16 models (verified from source code — `Flux2KleinPipeline(snapshot:)` accepts the exact paths documented above)
2. **Feature support:** T2I and I2I are both supported in the Swift library (verified from source)
3. **MLX Swift identification:** Correctly identified as MLX Swift, not CoreML/Core AI (verified)
4. **LoRA/callback absence:** Correctly identified as not implemented in Swift (verified from source)

### Risks:
- **Build complexity:** Requires Xcode 15+ with Metal toolchain (not available in current environment)
- **LoRA gap:** Not yet implemented in Swift Flux2 (mflux Python has it)
- **No progress callbacks:** Need to add closure-based callback API
- **No performance data:** Cannot compare Swift vs Python without actual benchmarks

### Next steps (required before GO):
1. **Compile and execute** the Swift benchmark harness on a macOS machine with Xcode 15+
2. **Run benchmarks** with the SAME parameters (4B bfloat16, 1024×1024, 50 steps, seed=42)
3. **Verify offline operation** with `HF_HUB_OFFLINE=1` — confirm no network requests during model loading
4. **Document actual timing data** (load, generate, peak memory) with raw run logs
5. **Implement or confirm** LoRA and progress callback support in the Swift library

---

## Files Committed to `v3-swift-backend` (commit `e8caa12`):

| File | Purpose |
|------|---------|
| `SWIFT_BACKEND_FEASIBILITY REPORT.md` | This report (amended) |

## Files Untracked but Present on Disk (`flux2-research/`):
| Path | Purpose |
|------|---------|
| `Package.swift` | Flux.2 Swift library (pinned mlx-swift 0.30.6) |
| `Sources/Flux2/` | Full Flux.2 pipeline implementation (Swift) |
| `Sources/Flux2CLI/` | CLI wrapper with generate/download/quantize subcommands |
| `Sources/Flux2CLICore/` | CLI error handling and image data loading |
| `benchmark-harness/Sources/Flux2Benchmark/main.swift` | Benchmark source (165 lines) — never executed |
| `Tests/` | Unit tests for scheduler, transformer, VAE, quantization |

---

*Original report generated 2026-09-13. Amended after independent audit on 2026-09-14.*
*Full audit findings: see `audit/AUDIT_REPORT.md`.*