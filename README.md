# Local Image Studio

[English](README.md) | [日本語](README.ja.md)

Local Image Studio is a native macOS image-generation workspace built for Apple Silicon. A SwiftUI front end manages a local Python inference service powered by [MFLUX](https://github.com/filipstrand/mflux) and Apple's [MLX](https://github.com/ml-explore/mlx). Generation, prompt enhancement, metadata, and image storage stay on the Mac; no cloud image-generation service is required.

![Local Image Studio showing its image library, editor, and local model controls](docs/verification/macos-polish/residency.png)

> **Developer preview:** the app is arm64-only, ad-hoc signed, and not notarized. It is intended for developers who are comfortable configuring local Python environments and model caches.

## Highlights

- Local generation with FLUX.2 Klein 4B, FLUX.2 Klein 9B, and Krea 2 Turbo through MFLUX/MLX
- Generation, FLUX reference editing, variations, regeneration, export, and reusable LoRAs
- SeedVR2 7B FP16 upscaling with 2× and 4× output options
- Project-based image library with history, generation lineage, metadata, archive, and restore workflows
- Optional local prompt enhancement using models served by LM Studio or oMLX
- English and Japanese interface localization

## Architecture

```text
SwiftUI application
       │ authenticated HTTP on 127.0.0.1
       ▼
local Python service (backend_v2.py)
       │ private stdin/stdout protocol
       ▼
persistent MFLUX worker → MLX → Apple Silicon GPU
```

The backend listens only on the loopback interface and requires a random token generated for each launch. Generation workers enable Hugging Face and Transformers offline modes. LM Studio (`127.0.0.1:1234`) and oMLX (`127.0.0.1:8000`) are contacted only when the optional local prompt-enhancement feature is used.

## Requirements

- Apple Silicon Mac running macOS 13 or later
- Apple Command Line Tools or Xcode with a mutually compatible Swift compiler and macOS SDK
- Python 3.10 or later
- MFLUX 0.19.1 with MLX 0.32.2; the default executable is `~/.local/share/uv/tools/mflux/bin/python`
- Locally cached weights for each generation model you choose to use

Set `LIS_MFLUX_PYTHON` before launching if the MFLUX Python executable is elsewhere. Set `LIS_SWIFTC` when the compatible Swift compiler is not `/usr/bin/swiftc`.

Model weights are not bundled. Generation does not automatically download FLUX or Krea weights. SeedVR2 is the one exception: its Models screen offers an explicit **Install SeedVR2 7B (~14 GB)** action, which downloads the checkpoint only after the user chooses it.

## Build from a clean clone

```sh
git clone https://github.com/Xombie2000/local-Image-studio.git
cd local-Image-studio
./build_v2_app.sh --build-only
```

The build-only command creates `build/Local Image Studio.app` without changing `~/Applications`. To build and install the preview locally, run:

```sh
./build_v2_app.sh
```

The install command preserves an existing app as `~/Applications/Local Image Studio v1.app` on the first replacement, then installs `~/Applications/Local Image Studio.app`. Because this preview is not Developer ID signed or notarized, macOS may require approval in System Settings on first launch.

## Run tests

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
./tests/run_swift_state_tests.sh
```

The ordinary unit tests use temporary storage and fake workers, so they do not load or download model data. The inference and telemetry scripts under `tests/` are opt-in integration checks and require the configured MFLUX environment and local model caches.

## Data and privacy

- Generated images: `~/Pictures/Local Image Studio/`
- Metadata: `~/Library/Application Support/Local Image Studio/history.sqlite3`
- LoRAs: `~/Library/Application Support/Local Image Studio/LoRAs/`
- Model weights: the shared local Hugging Face cache

Active projects are `.lisproject` packages. Archiving stores lossless WebP images inside a ZIP container; restoring recreates PNG files at their recorded paths. The repository contains no model weights, generated-image library, or user database.

## Repository layout

- `macos/` — SwiftUI application, models, store, localization, and property-list resources
- `backend_v2.py` — local API, SQLite history, projects, jobs, and prompt-helper routing
- `mflux_worker.py` — persistent MFLUX generation and SeedVR2 worker
- `build_v2_app.sh` — command-line build, bundle, icon, signing, and optional install flow
- `tests/` — Python regression tests, Swift state tests, and opt-in local inference checks
- `docs/` — implementation notes, compatibility patches, and verification evidence

## Model and dependency licenses

The source in this repository is MIT licensed, but that does not grant rights to third-party model weights. In particular, FLUX.2 Klein 9B uses the FLUX Non-Commercial License, and Krea 2 Turbo uses the Krea 2 Community License. Review the applicable terms before downloading or using any model, especially for commercial or production work. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the upstream links and license summary.

## Release status

The current target is a developer preview such as `v2.0.0-preview.1`. A general end-user release should additionally use Developer ID signing, Apple notarization, and a documented distribution/update process.

## License

Local Image Studio source code is available under the [MIT License](LICENSE). MFLUX-derived compatibility files retain their upstream MIT notice in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
