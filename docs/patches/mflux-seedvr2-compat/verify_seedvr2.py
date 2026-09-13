#!/usr/bin/env python3
"""Verify MFLUX SeedVR2 compatibility after environment rebuild.

Run this script to confirm that the installed MLX and MFLUX versions
are compatible with SeedVR2 7B upscaling.

Usage:
    python v2/docs/patches/mflux-seedvr2-compat/verify_seedvr2.py
"""

import importlib.metadata as meta
import os
import sys


def check_versions():
    """Check that MLX and MFLUX versions match the pinned versions."""
    errors = []

    try:
        mlx_ver = meta.version('mlx')
    except Exception as e:
        errors.append(f"MLX not installed: {e}")
        mlx_ver = None

    try:
        mflux_ver = meta.version('mflux')
    except Exception as e:
        errors.append(f"MFLUX not installed: {e}")
        mflux_ver = None

    if mlx_ver != '0.32.2':
        errors.append(f"MLX version mismatch: expected 0.32.2, got {mlx_ver}")

    if mflux_ver != '0.19.1':
        errors.append(f"MFLUX version mismatch: expected 0.19.1, got {mflux_ver}")

    return errors


def check_imports():
    """Check that all required MFLUX modules import without error."""
    errors = []

    # Core SeedVR2 model
    try:
        from mflux.models.seedvr2 import SeedVR2
        print("  [OK] SeedVR2 model class")
    except Exception as e:
        errors.append(f"SeedVR2 import failed: {e}")

    # Model config
    try:
        from mflux.models.common.config import ModelConfig
        config = ModelConfig.seedvr2_7b()
        print(f"  [OK] ModelConfig.seedvr2_7b() → model_name={config.model_name}, precision={config.precision}")
        print(f"       transformer_overrides: {config.transformer_overrides}")
    except Exception as e:
        errors.append(f"ModelConfig.seedvr2_7b() failed: {e}")

    # Attention module
    try:
        from mflux.models.seedvr2.model.seedvr2_transformer.attention import MMAttention
        print("  [OK] MMAttention class")
    except Exception as e:
        errors.append(f"MMAttention import failed: {e}")

    # Transformer
    try:
        from mflux.models.seedvr2.model.seedvr2_transformer.transformer import SeedVR2Transformer
        print("  [OK] SeedVR2Transformer class")
    except Exception as e:
        errors.append(f"SeedVR2Transformer import failed: {e}")

    # Window partitioner
    try:
        from mflux.models.seedvr2.model.seedvr2_transformer.window import WindowPartitioner
        print("  [OK] WindowPartitioner class")
    except Exception as e:
        errors.append(f"WindowPartitioner import failed: {e}")

    # RoPE module
    try:
        from mflux.models.seedvr2.model.seedvr2_transformer.rope import RoPEModule
        print("  [OK] RoPEModule class")
    except Exception as e:
        errors.append(f"RoPEModule import failed: {e}")

    # Scheduler
    try:
        from mflux.models.common.schedulers.seedvr2_euler_scheduler import SeedVR2EulerScheduler
        print("  [OK] SeedVR2EulerScheduler class")
    except Exception as e:
        errors.append(f"SeedVR2EulerScheduler import failed: {e}")

    # Latent creator
    try:
        from mflux.models.seedvr2.latent_creator.seedvr2_latent_creator import SeedVR2LatentCreator
        print("  [OK] SeedVR2LatentCreator class")
    except Exception as e:
        errors.append(f"SeedVR2LatentCreator import failed: {e}")

    # Text embeddings
    try:
        from mflux.models.seedvr2.model.seedvr2_text_encoder.text_embeddings import SeedVR2TextEmbeddings
        print("  [OK] SeedVR2TextEmbeddings class")
    except Exception as e:
        errors.append(f"SeedVR2TextEmbeddings import failed: {e}")

    # VAE
    try:
        from mflux.models.seedvr2.model.seedvr2_vae.vae import SeedVR2VAE
        print("  [OK] SeedVR2VAE class")
    except Exception as e:
        errors.append(f"SeedVR2VAE import failed: {e}")

    # Initializer
    try:
        from mflux.models.seedvr2.seedvr2_initializer import SeedVR2Initializer
        print("  [OK] SeedVR2Initializer class")
    except Exception as e:
        errors.append(f"SeedVR2Initializer import failed: {e}")

    # Util classes
    try:
        from mflux.models.seedvr2.variants.upscale.seedvr2_util import SeedVR2Util
        print("  [OK] SeedVR2Util class")
    except Exception as e:
        errors.append(f"SeedVR2Util import failed: {e}")

    # Weight definitions
    try:
        from mflux.models.seedvr2.weights.seedvr2_weight_definition import SeedVR2WeightDefinition
        print("  [OK] SeedVR2WeightDefinition class")
    except Exception as e:
        errors.append(f"SeedVR2WeightDefinition import failed: {e}")

    # Weight mapping
    try:
        from mflux.models.seedvr2.weights.seedvr2_weight_mapping import SeedVR2WeightMapping
        print("  [OK] SeedVR2WeightMapping class")
    except Exception as e:
        errors.append(f"SeedVR2WeightMapping import failed: {e}")

    # Config classes
    try:
        from mflux.models.common.config.config import Config
        print("  [OK] Config class")
    except Exception as e:
        errors.append(f"Config import failed: {e}")

    try:
        from mflux.models.common.vae.vae_util import VAEUtil
        print("  [OK] VAEUtil class")
    except Exception as e:
        errors.append(f"VAEUtil import failed: {e}")

    # Utilities
    try:
        from mflux.utils.scale_factor import ScaleFactor
        print("  [OK] ScaleFactor class")
    except Exception as e:
        errors.append(f"ScaleFactor import failed: {e}")

    try:
        from mflux.utils.generated_image import GeneratedImage
        print("  [OK] GeneratedImage class")
    except Exception as e:
        errors.append(f"GeneratedImage import failed: {e}")

    try:
        from mflux.utils.image_util import ImageUtil
        print("  [OK] ImageUtil class")
    except Exception as e:
        errors.append(f"ImageUtil import failed: {e}")

    try:
        from mflux.utils.metadata_reader import MetadataReader
        print("  [OK] MetadataReader class")
    except Exception as e:
        errors.append(f"MetadataReader import failed: {e}")

    return errors


def check_mlx_api():
    """Check that MLX has the required API for SeedVR2."""
    errors = []

    try:
        import mlx.core as mx
    except Exception as e:
        errors.append(f"MLX core import failed: {e}")
        return errors

    # Check scaled_dot_product_attention exists
    if not hasattr(mx.fast, 'scaled_dot_product_attention'):
        errors.append("mx.fast.scaled_dot_product_attention not available")
    else:
        print("  [OK] mx.fast.scaled_dot_product_attention available")

    # Test the attention computation with expected parameters
    try:
        B, H, L, D = 1, 20, 64, 128
        q = mx.random.normal((B, H, L, D))
        k = mx.random.normal((B, H, L, D))
        v = mx.random.normal((B, H, L, D))
        result = mx.fast.scaled_dot_product_attention(q, k, v, scale=D**-0.5)
        assert result.shape == (B, H, L, D), f"Shape mismatch: {result.shape}"
        print(f"  [OK] Attention computation test passed (shape={result.shape})")
    except Exception as e:
        errors.append(f"Attention computation test failed: {e}")

    # Test other MLX operations used by SeedVR2
    try:
        import mlx.core as mx
        # Test split/cumsum used by WindowPartitioner
        arr = mx.array([1, 2, 3, 4, 5])
        splits = mx.cumsum(mx.array([1, 2])).tolist()
        parts = mx.split(arr, splits)
        print(f"  [OK] mx.split/cumsum works (split into {len(parts)} parts)")
    except Exception as e:
        errors.append(f"MLX split/cumsum test failed: {e}")

    return errors


def check_model_files():
    """Check that model files exist in the Hugging Face cache."""
    errors = []

    hf_cache = os.path.expanduser('~/.cache/huggingface')
    seedvr2_path = os.path.join(hf_cache, 'hub', 'models--numz--SeedVR2_comfyUI')

    if not os.path.exists(seedvr2_path):
        errors.append(f"SeedVR2 model cache not found at {seedvr2_path}")
    else:
        files = []
        for root, dirs, fnames in os.walk(seedvr2_path):
            for f in fnames:
                if f.endswith('.safetensors'):
                    files.append(f)

        required = {'seedvr2_ema_7b_fp16.safetensors', 'ema_vae_fp16.safetensors'}
        found = set(files)

        if required.issubset(found):
            print(f"  [OK] SeedVR2 model files present: {', '.join(sorted(found))}")
        else:
            missing = required - found
            errors.append(f"Missing SeedVR2 files: {', '.join(missing)}")

    return errors


def main():
    print("=" * 60)
    print("MFLUX SeedVR2 Compatibility Verification")
    print("=" * 60)

    all_errors = []

    # Version check
    print("\n[1/4] Checking installed versions...")
    all_errors.extend(check_versions())

    # Import check
    print("\n[2/4] Checking MFLUX module imports...")
    all_errors.extend(check_imports())

    # MLX API check
    print("\n[3/4] Checking MLX API compatibility...")
    all_errors.extend(check_mlx_api())

    # Model files check
    print("\n[4/4] Checking model cache files...")
    all_errors.extend(check_model_files())

    # Summary
    print("\n" + "=" * 60)
    if all_errors:
        print(f"FAILED: {len(all_errors)} error(s) found:")
        for err in all_errors:
            print(f"  ✗ {err}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED — SeedVR2 7B is ready for upscaling.")
        sys.exit(0)


if __name__ == '__main__':
    main()
