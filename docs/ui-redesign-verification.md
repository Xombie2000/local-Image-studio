# macOS redesign verification

Branch: `ui-redesign`. The working tree was clean before branch creation. Existing tags are unchanged.

## Architecture and changed Swift files

- `macos/ContentView.swift`: native split-view workspace, collapsible right inspector, SwiftUI toolbar, viewport-based canvas, full-width multiline composer, native menus, compact metrics, project-filtered lineage and larger clipped thumbnails. Success notices are inline; destructive confirmation and actual errors remain native alerts.
- `macos/StudioStore.swift`: independent model selection and preferences, exact helper ID in generation requests, recent helper metrics, depth-first history presentation, project selection after moves, and a shared job observer for generation/upscale presentation. Upscale requests explicitly forward the source image's project ID.
- `macos/Models.swift`: model purpose and helper discovery response, pure canvas sizing, upscale request payload.
- `macos/LocalImageStudioApp.swift`: remove the competing AppKit toolbar implementation, keep the native window/menu lifecycle, add Export (⌘E) and Inspector (⌘⌥I). Existing ⌘G/⌘S shortcuts remain; the composer also supports ⌘Return.

The macOS 13 deployment target is retained. `NavigationSplitView` supplies the sidebar; `HSplitView` provides a native resizable inspector without raising the target for the newer `.inspector` API.

## Canvas

A `GeometryReader` outside the scrolling content measures the actual center viewport. Fit uses `min((viewportWidth - 40) / imageWidth, (viewportHeight - 40) / imageHeight)` and allows scaling above 1. The resulting frame preserves aspect ratio and centers with 20-point margins. Window, sidebar, inspector and composer changes automatically invalidate this geometry. Native image resolution does not cap Fit size. Zoom changes the layout frame, so oversized images scroll correctly. 100% maps source pixels to display pixels using the screen backing scale. Selecting another image returns to Fit.

## Model discovery and preferences

Image choices come from the existing backend model registry/cache checks. The bootstrap response adds a generation/upscale purpose. Installed FLUX.2 Klein 4B and 9B appear; SeedVR2 remains in model management and Upscale only. Selection is passed as the existing `model_id`; inference routing is unchanged.

Prompt helpers are discovered through LM Studio `GET http://127.0.0.1:1234/v1/models`. The observed preferred ID is **`qwen/qwen3-4b-2507`**. Other observed candidates include `qwen3.6-35b-a3b-mlx`, Gemma, Bonsai and Muse. Off bypasses the completion request. Explicit metadata is used when available; known image, embedding, speech and reranker IDs are excluded. This server supplies ID-only records, so remaining IDs are candidates whose compatibility is ultimately established by a successful chat completion. An unavailable or incompatible explicit selection uses the original prompt and a non-modal status, without silently switching models.

The server's v1 list does not expose quantization; the UI shows its exact ID rather than inventing a 6-bit suffix. The discovered Qwen 4B 2507 family is the initial preference when no helper preference exists. Existing automatic helper regression behavior is retained for legacy API clients that omit explicit selection.

`UserDefaults` persists `generationModelID` and `promptHelperModelID` separately. Viewing historical metadata does not overwrite the remembered generation choice. Existing strength and retention preferences remain.

## Metrics and actions

The image bar shows model, resolution and time; the inspector includes steps/sec and peak memory. Helper status shows output tokens/sec, total request latency and output token count. Throughput is the existing completion-token count divided by total request time, rather than a claimed server decode-only speed. For reasoning models, LM Studio's completion token accounting may include reasoning tokens.

Edit, Variation and Upscale remain in the canvas action strip; Export is in the toolbar. Fork, Regenerate, Save As, Copy Image, Reveal in Finder, Move to Project and Delete are in the ellipsis menu. Existing project context menus remain. Improved prompt review and strength/model refresh are in the helper options menu.

## Live checks performed

- Built the canonical sources with `build_v2_app.sh`, installed and launched the rebuilt application repeatedly.
- Toolbar selection exercised both installed image models. Persisted backend records verified `flux2_klein_4b` and `flux2_klein_9b`, not just dropdown labels.
- Qwen 4B generated the cat prompt and retained both `exactly eight wheels` and `no visible weapons` in the vehicle prompt.
- Observed Qwen 4B metrics: cat **27 tok/s · 5.6 s · 150 tok**; vehicle **101 tok/s · 1.3 s · 136 tok**. UI values matched persisted backend metrics.
- Helper Off generated the landscape with original and effective prompts identical and no helper model recorded.
- The alternate Qwen 35B helper completed an Edit request; its exact model ID and metrics were verified in persisted output.
- Real square 512×512, portrait 768×1344 and landscape 1344×768 generations were reviewed in Fit mode. Window zoom/restore and sidebar/inspector toggles were exercised.
- Edit created a reference-backed child. Variation created a child with a different seed. Project creation and secondary-menu Move succeeded.
- SeedVR2 7B FP16 2× upscale created a 1024×1024 child from a 512×512 source in the same named project. The repeated successful run recorded 25.75 GB peak and 8 bytes backend active memory after cleanup. The first UI run exposed an omitted project ID; that UI request bug was fixed and covered by a Swift regression check.
- Restart verified image/helper preferences and persisted upscale/history metadata.
- Native Export (⌘E) wrote a PNG whose bytes match its source. Copy Image completed.

## Automated checks

- Existing v2 prompt regressions plus six discovery/selection regressions: 16 tests discovered, 15 pass and one opt-in live test skipped in offline mode.
- The existing opt-in live prompt suite was run separately: all 10 pass, including the original Qwen 35B acceptance cases at normal and strong strength.
- Parent-project backend suite: all 9 pass after correcting its stale schema assertion from 2 to the already-existing version 3. That one-line test change is in `../tests/test_v2_backend.py`, outside the v2 Git repository; the database schema itself is unchanged.
- Existing standalone SeedVR2 integration test passes: real 1024×1024 generation → 2048×2048 upscale, unchanged source, parent and FP16 metadata verified.
- Existing memory telemetry script completed real inference successfully. Worker RSS peaked around 10.1 GB and settled near 1.15 GB; the UI upscale run separately reported 8 bytes active MLX memory after cleanup. Original tracked test fixtures were restored.
- SQL INSERT validation passes for both generation and upscale statements.
- `tests/run_swift_state_tests.sh` builds and runs the Swift state executable in two processes. It tests viewport fit across source resolutions/aspect ratios, model-purpose filtering, independent selections, New Image state, unavailable helper state, upscale project forwarding, and preference restoration in a separate process.

## Visual review and polish

Actual app screenshots were reviewed for selected square/portrait/landscape images, inspector open/closed, lineage, and resized windows. The helper dropdown was inspected through accessibility; the screenshot API could not capture the native popup menu itself. The restrained polish pass fixed the competing toolbar, landscape thumbnail overflow, filtered history counts and modal success notices. All backgrounds and typography follow system appearance; visual review used the current dark appearance.

## Protected implementation

No changes to `mflux_worker.py`, MFLUX patches, SeedVR2 inference/cleanup, FLUX inference, SQLite schema, or persisted lineage semantics. Existing helper system instructions, truncation/failure behavior, token budgets and regression cases remain intact. The only backend changes are model discovery metadata and explicit helper selection routing.

## Final review

After the Mac was unlocked, the final installed build was launched and reviewed. Actual screenshots confirmed the 2048×2048 Fit canvas, normal empty workspace, generation inspector, clipped landscape thumbnails, and project lineage. The project history count correctly changes to 2 for the verification project. 100%, zoom in/out and Fit were exercised; returning to Fit recenters the entire image. Copy Image now confirms inline with no modal. The preferred helper was restored to `qwen/qwen3-4b-2507`; the saved image model remains FLUX.2 Klein 9B. Existing 4:3/3:4 presets and trackpad magnification remain in the source. Trackpad magnification itself was not physically exercised by the automation API.

No additional visual changes were needed. The final acceptance gate is satisfied. No release tag is created.
