# macOS polish verification

Date: 2026-09-07. Branch: `ui-redesign`. Base: `6ca69ed`.
The branch and clean working tree were checked before editing. This is a separate polish commit; no merge or release tag is created.

## Changes and files

- `macos/ContentView.swift`: “Generate with:” labels the next-generation picker. Selected-image model information remains in the canvas header and Image Info. Picker tags, availability behavior and selection routing are unchanged. Installed status and idle residency are in an information popover beside the picker. Loading retains a prominent spinner/message. The unexplained standalone “Unloaded” is removed.
- `macos/Models.swift`: presentation-only helper names, positive/finite metric formatting and bounded prompt-editor sizing.
- `macos/StudioStore.swift`: retain the most recent real helper metrics across subsequent jobs and restore them from stored generations at launch. Off, missing metrics and “Edited by user” do not erase the last measured execution.
- `macos/LocalImageStudioApp.swift`: add the standard Edit → Select All (⌘A) responder action. Long-prompt testing exposed the missing menu command; replacement editing was verified after rebuilding.
- `tests/StudioStateTests.swift`: add checks for friendly names, omitted unverified quantization, absent/zero metric suppression, real metric formatting and prompt height bounds.

The editor stays a native multiline TextEditor. Its content height is 38 points for a short prompt (approximately two lines), expanding with explicit newlines to a 72-point maximum. Wrapped or longer content scrolls. Tighter surrounding spacing reclaims approximately 39 vertical points for the canvas in the normal short-prompt layout. Generate and helper controls remain adjacent.

History retains its existing indentation, thumbnails and relationships. The relationship symbol now uses secondary contrast and a parent-image tooltip. Upscales have the primary label “Upscale 2×” and secondary label “SeedVR2.” Inspector Image, Performance and Lineage structure is preserved; helper naming and metric formatting are consistent with the composer.

## Helper display names and metrics

| Exact server ID, retained internally | Primary display name |
| --- | --- |
| `qwen/qwen3-4b-2507` | Qwen3 4B Instruct |
| `qwen3.6-35b-a3b-mlx` | Qwen3.6 35B A3B |
| `google/gemma-4-26b-a4b-qat` | Gemma 4 26B A4B |
| `ternary-bonsai-27b-mlx` | Ternary Bonsai 27B |
| `muse-glimmer-30b` | Muse Glimmer 30B |

Unknown IDs receive a simple humanized final path component. Raw IDs remain in tooltips and request tags. The observed v1 model list provides IDs without quantization metadata, so no 6-bit suffix is claimed.

The composer shows the most recent measured helper execution using existing backend `tokens_per_second`, `total_time` and `token_count`. Throughput is backend completion-token count divided by total request latency, not an independently measured decode-only rate. Missing, zero and nonfinite values are hidden. Small positive values avoid misleading rounding to zero. Image performance remains separate, in seconds, steps/sec and peak memory.

Observed actual Qwen 4B requests:

| Prompt | Visible metrics | Persisted verification |
| --- | --- | --- |
| a cat sitting on a fence | 14 tok/s · 10.5 s · 150 tokens | `60b90357-06f6-4ec1-9674-839239224ba2`, exact Qwen server ID |
| A futuristic armored vehicle with exactly eight wheels, matte black bodywork, no visible weapons, parked in Tokyo at night | 28 tok/s · 5.9 s · 167 tokens | `86543a72-adb5-4cd1-817b-cb0b8992da6b`, exact Qwen server ID; both constraints retained verbatim in improved prompt |

The vehicle was generated from the viewed cat workspace and correctly became a Variation / Fork child under the existing workflow. The output image does not clearly depict eight wheels; preservation of the helper's textual constraints is verified, not perfect visual compliance by FLUX.

## Build and regressions

- Canonical `./build_v2_app.sh`: passed; installed the rebuilt app in `~/Applications/Local Image Studio.app`. Final build was actually launched and operated. `codesign --verify --deep --strict` passed.
- v2 Python discovery: 16 tests, 15 passed and the opt-in live case skipped in offline mode.
- Separate live helper suite: all 10 passed, including cat and constrained vehicle at normal and strong strengths using the existing Qwen 35B suite. First run hit a model/server timeout; a standalone diagnostic and the full isolated retry succeeded without changing helper logic.
- Parent-project backend suite: all 9 passed. Existing unclosed SQLite connection ResourceWarnings remain in test output.
- SQL INSERT validation passed for generation and upscale statements.
- Swift state runner: both processes passed, including fit across aspect ratios/resolutions, model-purpose filtering, independent image/helper choices, Off/unavailable helper state, New Image, upscale project payload and cross-process persistence, plus the new presentation assertions. A sandboxed rerun could not persist its isolated UserDefaults domain; running with the required filesystem access passed.
- Existing SeedVR2 integration: passed real FLUX 4B 1024×1024 → SeedVR2 2048×2048; parent/project metadata, FP16 and unchanged source verified.
- Existing memory telemetry script: inference completed without an error, RSS peaked at 9672 MiB and settled at 1005 MiB. Tracked image fixtures were restored; its additional temporary output was removed. The script is diagnostic and has no hard memory threshold assertion.
- Additional native UI upscale: cat 512×512 → 1024×1024, SeedVR2 7B FP16, 13.08 seconds, 31.64 GB recorded peak; child `0c9370fb-97e2-4b6b-b3f8-275486d40f89` points to the cat source.
- `git diff --check` passed. `backend_v2.py`, `mflux_worker.py` and MFLUX compatibility patches are byte-for-byte unchanged from the base. No inference, helper logic, schema, lineage semantics or cleanup changes.

## Actual application review

The final rebuilt app was launched, not merely compiled. Generation selection was changed from 9B to 4B; restart retained 4B and the exact Qwen helper preference. The native helper menu was inspected and shows all five friendly names plus Off. Native popup-menu screenshots were unavailable through the capture API, so menu contents were verified through accessibility.

Screenshots were taken and visually inspected for toolbar clarity, residency, prompt height, helper metrics, canvas fit, lineage and Inspector balance. The single restrained visual correction pass retained native toolbar spacing and avoided repeating the helper name inside the Inspector metric line. No further layout redesign followed.

- [Helper metrics and short prompt](verification/macos-polish/helper-metrics.png): compact footer, readable toolbar, distinct image/helper performance, preserved Inspector.
- [Completed upscale and lineage](verification/macos-polish/upscale.png): selected SeedVR2 metadata is clearly distinct from “Generate with: FLUX.2 Klein 4B”; child label and thumbnail remain readable.
- [Idle residency popover](verification/macos-polish/residency.png): installed availability, explicit SeedVR2 last-job wording, existing worker memory measurement, no standalone “Unloaded.”
- [Long prompt](verification/macos-polish/long-prompt.png): eight-line content scrolls within the bounded editor; full-image Fit adjusts to the changed workspace height.

Additional screenshots reviewed during this pass covered both side panes hidden and native window zoom/resize. Fit remained centered, aspect preserving and responsive; switching between 512 and 1024 source images did not constrain the displayed size to source resolution. The unchanged pure fit routine also passed portrait/landscape and 2048-pixel source checks.

## Remaining limits

- The server does not supply reliable quantization metadata in its v1 listing; it is intentionally omitted from friendly labels.
- Visual review used the current dark appearance. Semantic system colors and typography are retained; a separate light-appearance screenshot was not taken in this pass.
- The initial live helper timeout and the vehicle image's wheel-count limitation are recorded above. Neither required or justified changing protected inference/helper logic.
- Export, Edit, Off mode and alternate image-model inference were exercised during the base redesign acceptance; this pass preserves those implementations and reruns their automated coverage rather than claiming every prior manual scenario was repeated.
