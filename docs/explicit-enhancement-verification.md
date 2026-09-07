# Explicit prompt enhancement and project actions

Verified September 7, 2026, on `ui-redesign`, based on `ab4f0a1`. The canonical `build_v2_app.sh` completed, installed `~/Applications/Local Image Studio.app`, and the installed app was launched and exercised through native macOS controls. Code signing verification passed.

## Behavior

- Each normal project has a restrained trailing New Image action on hover or selection. It resolves the persisted project record, activates that UUID, clears selected image/source/Inspector and temporary enhancement state, and focuses the empty prompt. It neither creates a project nor starts generation. The context menu exposes the same action.
- Project trash uses a native destructive confirmation naming the project and its image count. Existing backend semantics are preserved: deleting a project removes its container and keeps images in All Images. Deleting the active project clears the active UUID and image workspace before refreshing.
- History trash targets that row, including an unselected row, with native confirmation. Existing backend deletion removes its file/metadata and reattaches children to its parent. The store immediately removes the row, clears any workspace referencing it, then reloads lineage and counts.
- The workflow is **Enhance → Review/Edit → Generate**. Enhance sends the current editor text and selected helper ID to a separate endpoint. A successful answer replaces the editor, enables Revert to Original, and updates friendly helper metrics. It creates no image job. The editor remains editable.
- Generate reads the editor string verbatim, sends `prompt_is_final: true` and `prompt_improvement: false`, and sends no hidden override. The backend final-prompt contract preserves whitespace and disables both legacy rewriting paths, even if a caller supplies contradictory flags. Legacy callers retain their existing behavior. There is no hidden enhanced-prompt field in WorkspaceState.
- Revert restores the exact string captured immediately before the latest successful Enhance. Repeated enhancement replaces this single snapshot. Project/image selection and New Image clear transient state. An in-flight response cannot overwrite another workspace or intervening edits.
- Failures keep the prompt untouched, show an inline notice, and leave Generate available. Footer metrics belong to the latest Enhance request and are persisted separately from image-generation history. Failed requests clear unavailable metrics.

## Files and regression coverage

Swift changes: `macos/ContentView.swift`, `macos/StudioStore.swift`, and `macos/Models.swift`. Backend changes are limited to the optional enhancement endpoint and final-prompt request contract in `backend_v2.py`.

`tests/StudioStateTests.swift` covers exact editor payloads, Unicode/newlines/trailing whitespace, enhancement/manual edits/revert/repeated enhancement, Off, failure, workspace isolation, and cross-project New Image. Existing project selection, model persistence across processes, All Images, and Fit tests remain green.

`tests/test_explicit_enhancement.py` covers the standalone enhancement operation, selected helper/metrics, safe failure, absence of image jobs, and disabling both hidden rewrite paths. `tests/test_project_requests.py` adds HTTP-to-SQLite exact-string checks, project preservation semantics, image lineage reattachment, and unavailable enhancement without generation.

Automated results:

- Swift state runner: passed, including separate-process preferences restoration.
- v2 unittest discovery: 24 passed; the opt-in live case was subsequently run separately.
- Live helper suite: all 10 passed, including four real LM Studio constraint checks (62.7 seconds).
- Parent-project backend suite: all 9 passed.
- Standalone SQL INSERT validation: both INSERT statements passed.
- SeedVR2 integration: passed real 1024→2048 FP16 upscale, lineage/project metadata, unchanged source, and memory metadata.
- Existing memory telemetry regression: completed with exit 0; 209 RSS samples captured, dropping from a peak of about 11.6 GiB to a stable 1.14 GiB after the upscale. This existing script reports measurements rather than asserting a memory threshold.

Inference, SeedVR2 compatibility patches/cleanup, schema, helper discovery, model-selection persistence, Inspector architecture, and Fit implementation were not modified.

## Native UI and exact prompt evidence

The editor value was read back from the native accessibility text after manual editing, then compared with the completed generation API response and the actual SQLite row. This catches native smart punctuation and whitespace rather than assuming pasted input equals the editor. Each linked JSON includes the visible string, effective backend string, generation ID, absent generation-time helper model, and successful SQLite equality assertion.

| Scenario | Native result | Evidence |
| --- | --- | --- |
| Cat → Enhance → manual edit → Generate | Enhanced text appeared without a new image; editor changed to a white-painted fence and added a newline/trailing spaces; exact 790-character equality | [Cat](verification/explicit-enhancement/cat-prompt-equality.json) |
| Vehicle → Enhance → manual edit → Generate | “exactly eight wheels” and “no visible weapons” remained visible; lighting manually changed; exact 768-character equality | [Vehicle](verification/explicit-enhancement/vehicle-prompt-equality.json) |
| Enhance → Revert → Generate | Exact 43-character original restored, including leading spaces, newline, and trailing spaces | [Revert](verification/explicit-enhancement/revert-prompt-equality.json) |
| Helper Off → Generate | Enhance disabled; exact 39-character equality | [Off](verification/explicit-enhancement/off-prompt-equality.json) |
| Helper unavailable → Enhance → Generate | Inline failure, no modal or automatic generation, prompt unchanged; direct Generate succeeded with helper unavailable; exact 31-character equality | [Failure](verification/explicit-enhancement/failure-prompt-equality.json) |

The local helper server was verified running on port 1234 before outage preparation. It was already stopped when the failure test resumed. The unavailable-server path was exercised, then the server was started again on port 1234 and the live helper suite passed.

Project/action checks:

- The selected project's trailing New Image control cleared canvas, selected image and Inspector, retained the canonical Project Selection Verification UUID (`245a27b1-c4f0-4947-b23d-42a1eb9a3948`), and focused the prompt. Subsequent cat/vehicle/revert generations belonged to that project.
- With Test's drone selected, Project Selection Verification's context-menu New Image activated the other project and produced an empty focused workspace. The shared handler's direct A→B trailing-action behavior is also covered by Swift state assertions.
- A disposable UX Action Check project was created. Native Off generation produced a 512×512 image; native SeedVR2 produced its 1024×1024 FP16 child in 12.48 seconds. Child trash removed only the child; normal-image trash then emptied History, canvas and Inspector while retaining the project. API verification found no dangling parent IDs.
- A second image populated UX Action Check. Project trash showed its exact name and count of 1, with the preservation explanation. After confirmation, the project disappeared, the workspace entered All Images / No Project, and its image (`0583283f-ff0c-447d-858c-24286e6607d5`) remained with a null project ID. Subsequent ungrouped generation succeeded without “Project not found”.
- Switching projects after successful Enhance removed the Enhanced/Revert state and loaded the destination image's prompt.
- Actual Size, Fit, Inspector hide/show, and a dragged pane divider were exercised. The image remained contained and the three-pane layout continued to work.

## Screenshot review

[Enhanced cat](verification/explicit-enhancement/enhanced-cat.png), [selected project/history controls and SeedVR2 lineage](verification/explicit-enhancement/upscale-controls.png), [native project confirmation](verification/explicit-enhancement/delete-project.png), [inline failure](verification/explicit-enhancement/helper-failure.png), and [wider fitted canvas](verification/explicit-enhancement/fit-wide-canvas.png) were captured from the rebuilt app and visually inspected.

Enhance is a small native secondary action; Generate remains prominent. Revert is subtle, helper metrics are readable, and selection-only row controls avoid persistent sidebar clutter. No further visual correction was required.

Remaining verification limitation: the automation API does not expose a sustained native pointer hover, so unselected-row hover appearance could not be reliably held and captured. Selected-row trailing actions were exercised natively; cross-project behavior was verified via the shared context-menu action and direct store regression. No functional failure was found. Existing SQLite ResourceWarnings appeared in Python tests; all assertions passed.

Test images/evidence remain available for review. The explicitly disposable child, original, and project were deleted through the tested native controls. No merge or release tag was performed.

## Follow-up: fresh-image seed behavior

The similarity report after this pass traced to workspace state rather than inference: selecting a generation set its seed to fixed, and New Image carried that setting into later work. Several stored cat generations therefore used seed `42`; later unrelated test images also shared a carried seed.

Ordinary generation now starts in random-seed mode both after selecting an image and after invoking any New Image action. The explicit Fork/Regenerate paths and manually disabling Random seed still preserve deterministic reproduction. Swift state coverage checks both sides of that contract, and the rebuilt app showed Random seed enabled after opening Generation Settings from a selected image.
