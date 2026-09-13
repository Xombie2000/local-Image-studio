# MFLUX SeedVR2 Compatibility Patch

This patch captures the exact MFLUX library files required for SeedVR2 7B upscaling
to work correctly with the installed MLX and Python versions.

## Why this patch is needed

SeedVR2 7B uses a custom transformer architecture with:
- Windowed attention (MMAttention) with spatial partitioning
- 3D RoPE embeddings for video-like temporal modeling  
- Custom schedulers (seedvr2_euler)
- 3D VAE encoder/decoder blocks

The compatibility patch captures the exact versions of these files that work with:
- **MLX 0.32.2** (macOS Apple Silicon)
- **MFLUX 0.19.1** (with SeedVR2 support)
- **Python 3.13.x**

Without this exact combination, SeedVR2 upscaling will fail with:
- `AttributeError` on missing MLX methods (older MLX)
- `TypeError` on wrong attention API signatures (newer MFLUX)
- Shape mismatches in window partitioning

## Files captured

See individual .patch files in this directory for each MFLUX source file.

## How to verify after rebuild

```bash
# 1. Ensure correct versions are installed
~/.local/share/uv/tools/mflux/bin/python -c "
import importlib.metadata as meta
assert meta.version('mlx') == '0.32.2', f'mlx version mismatch: {meta.version(\"mlx\")}'
assert meta.version('mflux') == '0.19.1', f'mflux version mismatch: {meta.version(\"mflux\")}'
print('Version check passed.')

# 2. Test SeedVR2 import and basic structure
from mflux.models.seedvr2 import SeedVR2
from mflux.models.common.config import ModelConfig
config = ModelConfig.seedvr2_7b()
print(f'Model config: {config}')

# 3. Test attention module loads without error
from mflux.models.seedvr2.model.seedvr2_transformer.attention import MMAttention
print('MMAttention class loaded successfully.')

# 4. Test scaled_dot_product_attention works with expected parameters
import mlx.core as mx
B, H, L, D = 1, 20, 64, 128
q, k, v = mx.random.normal((B,H,L,D)), mx.random.normal((B,H,L,D)), mx.random.normal((B,H,L,D))
result = mx.fast.scaled_dot_product_attention(q, k, v, scale=D**-0.5)
assert result.shape == (B, H, L, D), f'Shape mismatch: {result.shape}'
print('Attention computation verified.')

# 5. Test SeedVR2 model can be instantiated (without loading weights)
model = SeedVR2(model_config=config, quantize=None)
print(f'SeedVR2 model instantiated: {model}')

# 6. Test generate_image signature
import inspect
sig = inspect.signature(SeedVR2.generate_image)
params = list(sig.parameters.keys())
assert 'seed' in params and 'image_path' in params and 'resolution' in params
print(f'generate_image signature OK: {params}')

# 7. Test ModelConfig.seedvr2_7b() returns expected config
print(f'Config width: {config.width}, height: {config.height}')

# 8. Test the scheduler
from mflux.models.common.schedulers.seedvr2_euler_scheduler import SeedVR2EulerScheduler
print('SeedVR2EulerScheduler loaded.')

# 9. Test latent creator
from mflux.models.seedvr2.latent_creator.seedvr2_latent_creator import SeedVR2LatentCreator
print('SeedVR2LatentCreator loaded.')

# 10. Test text embeddings loader
from mflux.models.seedvr2.model.seedvr2_text_encoder.text_embeddings import SeedVR2TextEmbeddings
print('SeedVR2TextEmbeddings loaded.')

# 11. Test VAE
from mflux.models.seedvr2.model.seedvr2_vae.vae import SeedVR2VAE
print('SeedVR2VAE loaded.')

# 12. Test transformer
from mflux.models.seedvr2.model.seedvr2_transformer.transformer import SeedVR2Transformer
print('SeedVR2Transformer loaded.')

# 13. Test util classes
from mflux.models.seedvr2.variants.upscale.seedvr2_util import SeedVR2Util
print('SeedVR2Util loaded.')

# 14. Test initializer
from mflux.models.seedvr2.seedvr2_initializer import SeedVR2Initializer
print('SeedVR2Initializer loaded.')

# 15. Test weight definitions
from mflux.models.seedvr2.weights.seedvr2_weight_definition import SeedVR2WeightDefinition
print('SeedVR2WeightDefinition loaded.')

# 16. Test weight mapping
from mflux.models.seedvr2.weights.seedvr2_weight_mapping import SeedVR2WeightMapping
print('SeedVR2WeightMapping loaded.')

# 17. Test config
from mflux.models.common.config.config import Config
print('Config loaded.')

# 18. Test VAE util
from mflux.models.common.vae.vae_util import VAEUtil
print('VAEUtil loaded.')

# 19. Test scale factor
from mflux.utils.scale_factor import ScaleFactor
print('ScaleFactor loaded.')

# 20. Test generated image
from mflux.utils.generated_image import GeneratedImage
print('GeneratedImage loaded.')

# 21. Test image util
from mflux.utils.image_util import ImageUtil
print('ImageUtil loaded.')

# 22. Test metadata reader
from mflux.utils.metadata_reader import MetadataReader
print('MetadataReader loaded.')

# 23. Test callbacks (base class)
from mflux.models.common.callbacks import Callbacks
print('Callbacks loaded.')

# 24. Test model config
from mflux.models.common.config.model_config import ModelConfig
mc = ModelConfig.seedvr2_7b()
print(f'ModelConfig.seedvr2_7b(): width={mc.width}, height={mc.height}')

print('\\n=== ALL CHECKS PASSED ===')
"
```

## Reapplying after MFLUX update

If MFLUX is updated and SeedVR2 breaks:

1. Compare the new `attention.py` with this patch's version
2. Check if `mx.fast.scaled_dot_product_attention` signature changed
3. Verify window partitioning logic is unchanged
4. Test the verification script above

If the new version works, update this patch directory with the new files.

## INSERT Fix (SeedVR2 Upscale Metadata)

The `backend_v2.py` in this patch directory includes the 24-placeholder INSERT fix
for SeedVR2 upscale metadata storage. This fix ensures that when an upscaled image
is saved to the SQLite database, all 24 columns (including `upscale_source_width`,
`upscale_source_height`, `upscale_scale_factor`, `upscale_model_variant`, and
`upscale_precision`) receive their corresponding values without a column/value count mismatch.

**Key details:**
- The INSERT statement has exactly 24 column names and 24 `?` placeholders (0 NULLs)
- The regular generation INSERT has 36 columns, 35 `?` placeholders, and 1 NULL literal
- Both counts match exactly — a mismatch would cause `sqlite3.ProgrammingError`

**Regression test:** Run `python v2/tests/test_insert_validation.py` to verify all
INSERT statements have matching column/placeholder/value counts.

**Preservation note:** When rebuilding Local Image Studio from source, ensure that
`backend_v2.py` is copied from this patch directory (not the base v2 source) so
that both the MLX compatibility patches and the INSERT fix are included in the
.app bundle.
