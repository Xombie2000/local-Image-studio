# Swift Inference Backend — Feasibility Report

**Date:** 2026-09-13  
**Author:** Research branch investigation  
**Status:** GO for next milestone (FLUX.2-klein support), NO-GO for Krea-2 Turbo

---

## 1. Branch, Worktree, and Baseline

| Item | Value |
|------|-------|
| **Branch** | `v3-swift-backend` (created from `d32acc0`) |
| **Worktree** | `/Users/ricknichols/LocalImageStudio-v3` (detached HEAD) |
| **Baseline commit** | `d32acc0 feat: prompt editor resize and enhanced AI prompt generation` |
| **Original v2 checkout** | Untouched — still at `d32acc0` on branch `v3-swift-backend` |
| **Uncommitted work** | `local-Image-studio/` (untracked copy of v2 repo) — preserved, not included in new branch |

---

## 2. Verified Backend Options

### Option A: MLX Swift + flux2.swift (GO)

**Repository:** https://github.com/mzbac/flux2.swift  
**License:** Apache-2.0  
**Status:** Precompiled CLI binary available for macOS arm64

**Supported models (in flux2.swift):**
- FLUX.2-klein-4B ✅ (tested, working)
- FLUX.2-klein-9B (architecture supported, not tested)
- FLUX.2-dev (architecture supported, not tested)

**Key findings:**
- Uses `mlx-swift` for GPU acceleration on Apple Silicon
- Precompiled binary (`flux2-cli.macos.arm64`) available — no Xcode build required
- Reads from standard HuggingFace cache (`~/.cache/huggingface/hub/models/`)
- Supports quantization (4-bit, 8-bit) for reduced memory and faster loading

**Requirements:**
- Swift 6.0+ (we have 6.4) ✅
- Apple Silicon Mac ✅
- macOS 14+ (we have 26.6.2) ✅

### Option B: Core AI (macOS 27+) — Future option

**Framework:** https://developer.apple.com/documentation/coreai  
**Availability:** macOS 27.0+ (we have SDKs for 27.0 and 27)

Core AI is Apple's new inference framework (WWDC 2026), replacing Core ML for neural networks. It provides:
- Swift API (`AIModel`, `InferenceFunction`, `NDArray`)
- Model conversion via `coreai-torch` Python package
- `.aimodel` format with ahead-of-time compilation (`coreai-build`)

**Status:** Not tested — requires full Xcode (not just Command Line Tools) for model conversion tooling.

### Option C: Core ML (existing, fallback)

**Tool:** `coremltools` 9.0 (supports macOS 26, iOS 26)  
**Status:** Traditional path for converted models. Less performant than Core AI on Apple Silicon.

---

## 3. Architecture Mismatch: Krea-2 Turbo vs FLUX.2

**Critical finding:** The default LIS model (Krea-2 Turbo) uses a **single-stream transformer** architecture, which is fundamentally different from FLUX.2's dual-stream design.

| Parameter | Krea-2 Turbo (mflux) | FLUX.2-klein-4B (flux2.swift) |
|-----------|----------------------|-------------------------------|
| **Architecture** | Single-stream (all blocks) | Dual-stream (double + single layers) |
| **Features** | 6144 | 3072 (klein-4B) / 5120 (klein-9B) |
| **Heads** | 48 | 24 (klein-4B) / 40 (klein-9B) |
| **Layers** | 28 (all single-stream) | 5 double + 20 single (klein-4B) |
| **Latent channels** | 16 | 128 (klein-4B) / 64 (klein-9B) |
| **Text encoder** | Krea2TextEncoder | Mistral3 (klein-4B) / Qwen3 (dev) |
| **VAE** | QwenVAE | Flux2VAE |

**Conclusion:** flux2.swift cannot run Krea-2 Turbo weights without a complete reimplementation of the transformer architecture. The weight formats are incompatible.

---

## 4. Files Changed in Worktree

| File/Directory | Description |
|----------------|-------------|
| `flux2-research/` | Cloned flux2.swift repo (depth 1) — research reference only |
| `SWIFT_BACKEND_FEASIBILITY_REPORT.md` | This report |
| `research-notes/` | Empty directory (created, ready for notes) |

**Model cache modifications:**
- Created `model_index.json` in FLUX.2-klein-4B snapshot (required by flux2.swift)
- Created symlink from flux2.swift cache path to existing model

---

## 5. Tests Actually Run

### Test 1: Swift flux2-cli — Cold start (FLUX.2-klein-4B)
- **Prompt:** "A studio photo of a tabby cat with green eyes, ultra realistic"
- **Seed:** 42
- **Steps:** 4
- **Resolution:** 512×512
- **Guidance:** 1.0
- **Result:** ✅ Generated 485KB PNG in ~26s (included model download)

### Test 2: Python mflux — Cold start (FLUX.2-klein-4B, quantize=8)
- **Same parameters as Test 1**
- **Result:** ✅ Generated 423KB PNG in 5.72s (1.25s load + 4.47s gen)
- **Active memory:** ~3.4 GB
- **Peak memory:** ~13.8 GB

### Test 3: Python mflux — Warm generation (FLUX.2-klein-4B, quantize=8)
- **Same parameters** (model already loaded from Test 2)
- **Result:** ✅ Generated in 4.17s (no load time)
- **Active memory:** ~3.4 GB
- **Peak memory:** ~13.7 GB

### Test 4: Swift flux2-cli — Warm generation (FLUX.2-klein-4B)
- **Same parameters** (model already cached from Test 1)
- **Result:** ✅ Generated 485KB PNG in ~5.1s (no download)

### Test 5: Visual comparison
- All three images show the same tabby cat with green eyes
- Composition, pose, and color are visually comparable across runtimes

---

## 6. Benchmark Results

| Metric | Swift flux2-cli (warm) | Python mflux (quantize=8) |
|--------|----------------------|--------------------------|
| **Cold load + gen (4 steps, 512×512)** | ~26s (incl. download) | 5.72s (1.25s load + 4.47s gen) |
| **Warm generation (4 steps, 512×512)** | ~5.1s | 4.17s |
| **Active memory** | Not measured (CLI doesn't expose) | ~3.4 GB |
| **Peak memory** | Not measured (CLI doesn't expose) | ~13.7 GB |
| **Output size** | 485 KB (PNG) | 423 KB (PNG) |
| **Resolution** | 512×512 | 512×512 |
| **Quantization** | Default (likely Q8) | Explicit Q8 (group 64) |

**Note:** Cold-start Swift time includes model download from HuggingFace. With the model pre-cached, warm Swift generation (~5.1s) is within ~20% of Python mflux (4.17s).

---

## 7. Go/No-Go Recommendation

### FLUX.2-klein-4B: **GO** ✅
- flux2.swift works with precompiled binary (no Xcode build needed)
- Output quality is visually comparable to Python mflux
- Warm generation within ~20% of Python performance
- Model already installed in cache (15GB)

### Krea-2 Turbo: **NO-GO** ❌
- Architecture mismatch (single-stream vs dual-stream transformer)
- Weight format incompatible with flux2.swift
- Would require implementing a complete Krea2Pipeline in Swift (~weeks of work)
- **Blocker:** No existing Swift implementation supports Krea-2 Turbo

### Next small milestone (if GO for FLUX.2-klein):
1. Integrate flux2.swift as an **optional** inference backend alongside mflux
2. Add model selection UI to choose between Python (mflux) and Swift (flux2.swift) backends
3. Benchmark FLUX.2-klein-9B in Swift (larger model, more memory pressure)
4. Investigate Core AI integration for macOS 27 (requires full Xcode)

### If targeting Krea-2 Turbo specifically:
- **Blocker:** Would need to port the entire Krea2Transformer from mflux Python to Swift
- This is a substantial undertaking (est. 4-8 weeks for a working prototype)
- Not recommended as the next small milestone

---

## 8. Supporting Links

| Resource | URL |
|----------|-----|
| flux2.swift (GitHub) | https://github.com/mzbac/flux2.swift |
| flux2.swift CLI release | https://github.com/mzbac/flux2.swift/releases/latest |
| MLX Swift (GitHub) | https://github.com/ml-explore/mlx-swift |
| MLX Swift Examples | https://github.com/ml-explore/mlx-swift-examples |
| Core AI framework docs | https://developer.apple.com/documentation/coreai |
| Core AI WWDC 2026 | https://developer.apple.com/videos/play/wwdc2026/324 |
| Core AI Optimization | https://apple.github.io/coreai-optimization |
| mflux (Python MLX diffusion) | https://github.com/mflux-community/mflux |
| Core ML Tools 9.0 | https://coremltools.readme.io/ |

---

*Report generated 2026-09-13. All tests run on macOS 26.6.2 (arm64) with Swift 6.4 and Command Line Tools.*
