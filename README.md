# Local Image Studio

[English](README.md) | [日本語](README.ja.md)

Local Image Studio is an experimental, local-only macOS interface for image generation with MFLUX. It provides a native SwiftUI library and editor for FLUX.2 Klein and Krea 2 Turbo, plus SeedVR2 upscaling.

This repository currently represents a **developer preview for Apple Silicon**, not a notarized end-user release. It expects models and an MFLUX runtime to already exist on the Mac and never downloads models from the app.

The app is available in English and Japanese. It follows the macOS language preference for the app and falls back to English.

## Requirements

- Apple Silicon Mac running macOS 13 or later
- Python 3.10 or later
- MFLUX 0.19.1 with MLX 0.32.2 at `~/.local/share/uv/tools/mflux/bin/python`
- Locally cached model weights for the models you want to use

Set `LIS_MFLUX_PYTHON` before launching if the MFLUX Python executable lives elsewhere.

## Build and install

From the repository root:

```sh
./build_v2_app.sh
```

The script compiles an arm64 app, creates its icon, applies an ad-hoc signature, and installs it at `~/Applications/Local Image Studio.app`. If an existing app is present, the first replacement is preserved as `~/Applications/Local Image Studio v1.app`.

To verify or package the build without changing `~/Applications`, run `./build_v2_app.sh --build-only`. The app is left under `build/Local Image Studio.app`.

Because the preview is not Developer ID signed or notarized, macOS may require you to approve the first launch in System Settings.

## Run tests

Create a Python environment and install the small test dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
./tests/run_swift_state_tests.sh
```

The inference and telemetry scripts require the configured MFLUX environment and local model caches. Ordinary unit tests use fake workers and do not download model data.

## Data and privacy

- The backend binds only to `127.0.0.1` and requires a random per-launch token.
- Hugging Face and Transformers offline modes are enabled for inference workers.
- Generated images are stored in `~/Pictures/Local Image Studio/`.
- Metadata is stored in `~/Library/Application Support/Local Image Studio/history.sqlite3`.
- LoRAs can be added under `~/Library/Application Support/Local Image Studio/LoRAs/`.

Active projects are `.lisproject` packages. Archiving stores lossless WebP images inside a ZIP container; restoring recreates PNG files at their recorded paths.

## Current release status

Use a pre-release label such as `v2.0.0-preview.1`. The app is arm64-only and locally signed. A general release should additionally use Developer ID signing and Apple notarization.

## License

Local Image Studio is available under the [MIT License](LICENSE). MFLUX-derived compatibility files retain their upstream MIT notice in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Model weights are not distributed by this repository and remain subject to their respective licenses and terms.
