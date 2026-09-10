# Changelog

## Unreleased

- Discover prompt-helper models from both LM Studio and oMLX, label them by provider, and route each request to the selected local server.

## 2.0.0-preview.1

- Replaced the web wrapper with a native SwiftUI workspace.
- Added local model selection for FLUX.2 Klein 4B, FLUX.2 Klein 9B, and Krea 2 Turbo.
- Added SeedVR2 upscaling, project packages, image history, variants, and reference editing.
- Made prompt enhancement explicit, reversible, and failure-safe.
- Added local-only backend lifecycle management and model-memory retention controls.
- Added a native English/Japanese interface that follows the macOS app language.

This preview targets Apple Silicon and expects an existing compatible MFLUX installation and local model cache. It is ad-hoc signed and not notarized.
