# Project selection regression verification

Branch: `ui-redesign`. Base: `3c73d4a`. Date: 2026-09-07.
The branch and clean working tree were confirmed before investigation. No merge or tag is created.

## Proven causes

The installed application initially had the reported “Project not found.” alert open. After dismissing it, Test was selected with zero history items, while the canvas and Inspector still showed the older SeedVR2 cat. Clicking Generate reproduced the same alert.

Two Swift state defects were responsible:

1. `ProjectRow` assigned `selectedProjectId` directly and called `select` only if the destination had an image. An empty destination never cleared `selectedGeneration` or rebuilt `workspace`. History filtered on `selectedProjectId`, whereas the canvas used `selectedGeneration` and Generate sent `workspace.projectId` and `workspace.parentId`.
2. After deletion, `refresh()` replaced the selected generation with its updated database record, but did not reconcile the active project or the workspace. Project deletion correctly moved images out of the deleted project in SQLite. The workspace still held the deleted container's UUID. Selecting empty Test then changed only the sidebar ID.

Project creation already persisted through the backend and received a canonical UUID; it was not inventing a temporary client ID. However, it did not activate the returned project or clear the previous image. The fix now does both after successful persistence.

## Exact request and database proof

Before changing canonical Swift sources, a temporary copy of the original build added credential-free request tracing. The actual UI created a disposable “Selection Reproduction” project, moved an existing test cat into it, deleted that disposable container while preserving its image, selected Test, entered the requested drone prompt and clicked Generate. This reproduced the same failure.

Captured state and request:

| Field | Value |
| --- | --- |
| Active Test / `selectedProjectId` | `4f5e3858-7baf-481c-86bc-a3cea4cc874c` |
| `workspace.projectId` and outgoing `project_id` | `2043cd2d-4d11-466e-b895-0b0d821140f7` |
| Stale selected generation and outgoing `parent_id` | `60b90357-06f6-4ec1-9674-839239224ba2` |
| Refreshed selected generation's `projectId` | `null` |
| Backend response | HTTP 400, `{"error":"Project not found."}` |

Direct SQLite queries found Test under its exact UUID, no project row for the outgoing UUID, and `project_id = NULL` on the preserved cat. `validate_v2_payload` correctly rejects that missing project. There is no schema or UUID-format defect.

The [complete captured JSON body, state and response](verification/project-selection/failing-request.json) contains no authentication headers. The temporary logging build is outside the repository and is not part of the installed final app or commit.

## Fix and invariant

- `macos/StudioStore.swift`: centralize project changes in store methods; make the active project externally read-only; persist and validate its selection on restart; reconcile library reloads/deletion/moves with the selected generation and draft destination.
- `macos/ContentView.swift`: route sidebar, All Images and Generation Settings project bindings through those methods. Layout, model controls and existing empty-canvas presentation are unchanged.

For a specific active project, the selected generation belongs to that project or is nil. Project switches preserve a valid image or select the first available destination image. Empty destinations call the existing New Image transition, clearing the image, parent, improved prompt and reference state and using the destination's canonical ID. The Inspector naturally changes from Image Info to Generation Settings.

All Images is the explicit global exception: its history includes every project, and selecting an image does not narrow the global filter. A derived draft can retain that image's project; New Image in All Images has no project. Choosing a draft's Project in Generation Settings updates the active project and clears the previous image source while retaining the entered prompt.

New Project activates only the successfully returned backend record. Generate refreshes the library before submission and validates the destination; a disappearing or archived project prevents submission and preserves the prompt with an inline explanation. The backend still validates deletion races after that snapshot. A real “Project not found.” response causes refresh/recovery, while other backend errors retain normal reporting. A selection revision prevents an older asynchronous job from replacing a workspace the user has since switched away from.

No backend, inference, model selector, helper implementation, SQLite schema, MFLUX compatibility or SeedVR2 cleanup files changed.

## Regression coverage

`tests/StudioStateTests.swift` now covers:

- A with an image → empty B: nil image selection, empty history, New Image workspace, B destination, cleared parent/reference.
- B's generation payload uses B's ID and has no stale parent.
- Repeated A → B → A selection consistency.
- Activation of the backend-returned newly created project ID and immediate request destination.
- Cross-process restoration of empty B, global All Images, and recovery from a project deleted before restart.
- Draft destination changes, canonical refresh after deletion, retained prompt and rejected missing destination.

`tests/test_project_requests.py` uses an isolated HTTP backend and temporary SQLite/image storage with the existing test worker. It verifies creation is persisted before immediate generation, the resulting file/database row has the canonical project ID, deletion/recreation produces a different ID, stale IDs still return HTTP 400, and ungrouped generation remains supported.

Results:

- Canonical `./build_v2_app.sh`: passed. Installed app launched and visually reviewed. Strict deep code-signature verification passed.
- Swift state runner: both processes passed, including the prior model, helper, fit and upscale payload regressions.
- v2 Python discovery: 19 tests, 18 passed; the opt-in live case was skipped in offline mode.
- Opt-in live prompt suite: all 10 passed, including original cat/vehicle normal and strong cases.
- Parent-project regression suite: all 9 passed.
- SQL INSERT validation: both generation and upscale statements passed.
- Existing SeedVR2 integration: real 1024×1024 FLUX generation → 2048×2048 SeedVR2 upscale passed, including lineage/project metadata and unchanged source checks.
- Existing memory telemetry diagnostic: inference completed with no error lines; RSS peaked at 10205 MiB and settled at 1007 MiB. This diagnostic has no hard memory-threshold assertion. Tracked image fixtures were restored and its temporary extra output removed.
- Protected-file diff and whitespace checks passed.

## Actual rebuilt UI verification

1. Selected a cat, created “Project Selection Verification,” and confirmed the canonical new project became active with no old image or metadata. Immediate generation succeeded: cat `4304cfc3-0447-4ebc-9f68-9a99f2ab123d`, project `245a27b1-c4f0-4947-b23d-42a1eb9a3948`.
2. Switched from that populated project to empty Test. The old image and Image Info disappeared. History showed zero, the normal New Image canvas appeared, and Generation Settings showed Project: Test.
3. Restarted the app with empty Test selected. Test restored correctly with no stale canvas or metadata.
4. Generated exactly “A military attack drone from 2100.” FLUX 4B completed a 1024×1024 image in 7.04 seconds. Result `d1aa4ae3-53d1-4158-8a1c-64b1e7f264e7` has Test's UUID and `parent_id = NULL`, confirmed through both the API and a SQLite project/generation join. No project error appeared.
5. Switched repeatedly between the verification project and Test: each showed its own image and history. All Images showed global history while selecting images from a project.
6. Created a disposable empty “Project Recovery Check,” entered a draft, and deleted only that test project externally through the local API before clicking Generate. The UI refreshed, kept the exact draft, cleared the invalid destination and showed an inline recovery message. SQLite confirmed zero generations were submitted with that draft.
7. Restarted again with populated Test selected. Its drone, history and Inspector restored consistently. Repeated the project switches and left Test selected with the drone visible.

Screenshots were taken and inspected from the actual application:

- [Empty Test after the fix](verification/project-selection/empty-test-after.png)
- [Successful Test generation](verification/project-selection/test-generation-after.png)
- [Recovered draft after project disappearance](verification/project-selection/missing-project-after.png) (the transient inline notice had dismissed by this saved capture; its exact text was verified in the live accessibility/screenshot response).

The initial stale-canvas screenshot and error accessibility state were inspected in the conversation. Subsequent saved captures had already moved to a different app state, so they are excluded rather than labeled as before-state evidence. The exact failure trace is retained above.

The requested project-state regression is resolved. The two deliberate test projects used for deletion reproduction/recovery were removed; the populated verification project remains available alongside Test for inspection.
