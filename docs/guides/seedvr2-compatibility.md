# SeedVR2 7B Compatibility Guide

## Overview

This document explains why the MFLUX SeedVR2 compatibility patch is required,
how to verify it after an environment rebuild, and how to reapply it if needed.

## The Problem: Why a Compatibility Patch Is Required

SeedVR2 7B is an upscaling model that uses a fundamentally different architecture
from the standard FLUX.2 models:

### Architecture Differences

| Aspect | FLUX.2 Klein | SeedVR2 7B |
|--------|-------------|------------|
| Model type | Standard diffusion transformer | Video-like 3D transformer |
| Attention | Standard self-attention | Windowed multi-modal attention (MMAttention) |
| Position encoding | 2D RoPE | 3D RoPE (spatial + temporal) |
| Scheduler | Standard Euler | Custom SeedVR2EulerScheduler |
| VAE | 2D encoder/decoder | 3D encoder/decoder with tiling |
| Input | Text prompt only | Text + source image (latent conditioning) |

### Specific Compatibility Requirements

The SeedVR2 transformer depends on these exact MLX/MFLUX behaviors:

1. **`mx.fast.scaled_dot_product_attention(q, k, v, scale=...)`**
   - Used in `attention.py` line 105 for the core attention computation
   - Requires MLX 0.32.x API (signature may differ in other versions)
   - The `scale` parameter must accept a float scalar

2. **Window partitioning (`WindowPartitioner`)**
   - Partitions spatial dimensions into windows for memory efficiency
   - Uses `mx.split()`, `mx.cumsum()`, and index-based reordering
   - Requires exact MLX tensor shape semantics

3. **3D RoPE embeddings (`RoPEModule`)**
   - Extends 2D rotary position encoding to handle video-like temporal dimensions
   - Uses specific MLX broadcasting rules

4. **Custom scheduler (`SeedVR2EulerScheduler`)**
   - Single-step (1 inference step) Euler scheduler tuned for upscaling
   - Uses `config.time_steps` format dict with specific keys

5. **3D VAE with tiling**
   - Handles large output images by encoding/decoding in tiles
   - Uses 3D resnet blocks and mid-blocks

### What Breaks With Version Mismatch

| Scenario | Failure Mode |
|----------|-------------|
| MLX < 0.32 | `AttributeError: module 'mlx.core' has no attribute 'fast'` or missing `scaled_dot_product_attention` |
| MLX > 0.32 (future) | API signature changes in `mx.fast.scaled_dot_product_attention` |
| MFLUX < 0.19 | No SeedVR2 support at all (model class doesn't exist) |
| MFLUX > 0.19 (future) | API changes in `SeedVR2.generate_image()` signature or internal transformer structure |

## Installed Versions (Pinned)

The following versions are confirmed working together:

```
MLX:              0.32.2 (core)
MFLUX:            0.19.1
Python:           3.13.15 (Clang 22.1.3, macOS arm64)
Platform:         macOS-26.6.2-arm64-arm-64bit-Mach-O
```

Model cache files present:
- **SeedVR2 7B**: `seedvr2_ema_7b_fp16.safetensors` + `ema_vae_fp16.safetensors`
- **FLUX.2 Klein 4B**: Multi-file diffusion model (~15 GB)
- **FLUX.2 Klein 9B**: Multi-file diffusion model (~32 GB)

MFLUX Python path: `~/.local/share/uv/tools/mflux/bin/python`

## How to Verify After an Environment Rebuild

Run the verification script included in the patch directory:

```bash
/Users/ricknichols/.local/share/uv/tools/mflux/bin/python \
  v2/docs/patches/mflux-seedvr2-compat/verify_seedvr2.py
```

Or run the inline verification (from `README.md` in patch directory):

```bash
/Users/ricknichols/.local/share/uv/tools/mflux/bin/python -c "
import importlib.metadata as meta
assert meta.version('mlx') == '0.32.2'
assert meta.version('mflux') == '0.19.1'
from mflux.models.seedvr2 import SeedVR2
from mflux.models.common.config import ModelConfig
config = ModelConfig.seedvr2_7b()
from mflux.models.seedvr2.model.seedvr2_transformer.attention import MMAttention
import mlx.core as mx
B, H, L, D = 1, 20, 64, 128
q, k, v = mx.random.normal((B,H,L,D)), mx.random.normal((B,H,L,D)), mx.random.normal((B,H,L,D))
result = mx.fast.scaled_dot_product_attention(q, k, v, scale=D**-0.5)
assert result.shape == (B, H, L, D)
print('ALL CHECKS PASSED')
"
```

## How to Reapply After an MFLUX Update

If you update MFLUX and SeedVR2 breaks:

### Step 1: Identify the broken file
Run a minimal import test:
```bash
/Users/ricknichols/.local/share/uv/tools/mflux/bin/python -c "from mflux.models.seedvr2 import SeedVR2"
```

### Step 2: Compare with the patch
The patch directory contains copies of all working files. Compare:
```bash
diff -u v2/docs/patches/mflux-seedvr2-compat/attention.py \
  $(python -c "from mflux.models.seedvr2.model.seedvr2_transformer import attention; print(attention.__file__)")
```

### Step 3: Apply the patch (if needed)
If the new MFLUX version has API changes, you may need to:
1. Update the patch files with the new working versions
2. Test the full upscaling pipeline
3. Update `version-pinning.txt` with new version numbers

### Step 4: Test end-to-end
1. Open Local Image Studio.app
2. Select any existing generation (not SeedVR2)
3. Click "Upscale" → select 2x or 4x
4. Verify the upscaled image appears in the same project

## File Inventory

The patch directory contains these files (all from MFLUX 0.19.1):

| File | Purpose |
|------|---------|
| `attention.py` | MMAttention class with windowed multi-modal attention |
| `transformer.py` | SeedVR2Transformer with PatchIn/PatchOut blocks |
| `window.py` | WindowPartitioner for spatial memory management |
| `rope.py` | 3D RoPE (rotary position embeddings) |
| `seedvr2.py` | SeedVR2 model class with generate_image() |
| `seedvr2_euler_scheduler.py` | Custom single-step Euler scheduler |
| `seedvr2_latent_creator.py` | Creates initial latents and conditioning |
| `text_embeddings.py` | Pre-computed positive text embeddings |
| `vae.py` | 3D VAE with tiling support |
| `seedvr2_initializer.py` | Weight initialization and quantization |
| `seedvr2_util.py` | Image preprocessing and color correction |
| `seedvr2_weight_definition.py` | Weight tensor definitions |
| `seedvr2_weight_mapping.py` | Maps weights to architecture layers |
| `model_config.py` | ModelConfig.seedvr2_7b() definition |
| `config.py` | Base Config class for generation parameters |
| `vae_util.py` | VAE encode/decode utilities with tiling |
| `scale_factor.py` | Scale factor handling (2x, 4x) |
| `generated_image.py` | GeneratedImage output class |
| `image_util.py` | Image conversion utilities |
| `metadata_reader.py` | Reads EXIF/metadata from source images |
| `callbacks.py` | Progress callback system |

## Integration with Local Image Studio

The complete upscaling pipeline in Local Image Studio:

1. **UI**: User selects a generation → clicks "Upscale" button
2. **Frontend** (`ContentView.swift`): `UpscaleSheet` collects scale, softness, seed
3. **Store** (`StudioStore.swift`): `performUpscale(job:)` sends POST to `/api/upscale`
4. **Backend** (`backend_v2.py`): `start_upscale()` validates inputs, creates job
5. **Worker** (`mflux_worker.py`): `upscale()` action loads SeedVR2, calls `generate_image()`
6. **MFLUX**: Loads model weights → runs 1-step denoising with SeedVR2EulerScheduler
7. **Result**: Upscaled image saved to database with parent_id, project_id, metadata

### Database Schema for Upscale Generations

```sql
-- Columns added to generations table:
parent_id TEXT              -- Source generation ID (the image being upscaled)
project_id TEXT             -- Project to store the result in
upscale_source_width INTEGER  -- Source image width (e.g., 1024)
upscale_source_height INTEGER -- Source image height (e.g., 1024)
upscale_scale_factor TEXT     -- "2×" or "4×" (Unicode multiplication sign)
upscale_model_variant TEXT    -- "7B"
upscale_precision TEXT        -- "FP16"
```

### Metadata Stored for Upscale Results

- `source_generation_id`: UUID of the original generation
- `width` / `height`: Output dimensions (e.g., 2048×2048 for 2x)
- `model_id`: "seedvr2_7b"
- `model_label`: "SeedVR2 7B"
- `prompt`: "Upscale {scale} — SeedVR2 7B"
- `original_prompt`: "Upscale {scale} from source"
- `generation_time`: Wall-clock seconds for the upscale
- `peak_memory_bytes`: Peak MLX memory usage during inference
- `active_memory_bytes`: Active MLX memory after completion

## Troubleshooting

### "SeedVR2 7B model is not installed"
Open the Models view in Local Image Studio and click "Install SeedVR2 7B (~14 GB)".

### "MFLUX generation failed" or "Upscale timed out"
Check that:
- MFLUX Python is at `~/.local/share/uv/tools/mflux/bin/python`
- MLX version is 0.32.x (check with `mlx.__version__`)
- MFLUX version is 0.19.x (check with `mflux.__version__`)
- Model files exist in Hugging Face cache

### "AttributeError: module 'mlx.core' has no attribute 'fast'"
Your MLX version is too old. Upgrade to 0.32.x:
```bash
uv pip install --upgrade mlx --prefix ~/.local/share/uv/tools/mflux
```

### "TypeError: scaled_dot_product_attention() got an unexpected keyword argument"
Your MFLUX version may have API changes. Check the patch directory's `attention.py` for the expected call signature.

### "Shape mismatch" or "RuntimeError in window partitioning"
The MLX tensor shape semantics may have changed. Compare your `window.py` with the patch version.
