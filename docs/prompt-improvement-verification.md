# Prompt improvement fix — 2026-09-07

Tested against LM Studio **0.4.23+1**, `http://127.0.0.1:1234`, model
`qwen3.6-35b-a3b-mlx` (MLX, 4-bit).

## Change

- `backend_v2.py`, `LMStudioPromptHelper.improve`: use temperature 0 and a
  2,048-token completion ceiling for the existing Qwen 35B fallback selection.
  Smaller helper models retain their 220-token ceiling. No server/model settings
  or other Qwen request paths are changed.
- Validate `message.content` as non-empty text. Empty, missing, null, malformed,
  or length-truncated responses preserve the original prompt. Never substitute
  `reasoning_content`. The system prompt is unchanged, including all preservation
  constraints and the instruction to return only the improved prompt.
- `macos/StudioStore.swift`: route `job.promptNotice` into a separate published
  `promptImprovementNotice`, retain it on completion, clear it on new generation
  or selection. It no longer enters the general modal-notice state.
- `macos/ContentView.swift`: show that status beneath the prompt controls using
  `promptImprovementStatus` as its accessibility identifier.
- `tests/test_prompt_improvement.py`: nine offline tests plus an opt-in live test
  with four cases (both acceptance prompts at Normal and Strong).

## Reasoning-control investigation

LM Studio's [reasoning documentation](https://lmstudio.ai/docs/developer/rest/chat)
explains that available reasoning settings depend on the model. This installation's
`/api/v1/models` returned no reasoning capability for this Qwen model.

Each request below returned **HTTP 200**, 219 reasoning tokens, empty content,
and `finish_reason: "length"` at the original 220-token budget:

| Request control | Cat prompt latency |
| --- | ---: |
| `reasoning_effort: "none"` | 2.339 s |
| `chat_template_kwargs: {"enable_thinking": false}` | 1.892 s |
| `enable_thinking: false` | 2.141 s |

The local server log explicitly reported: “No valid custom reasoning fields found”
and said that reasoning setting `off` could not be converted to custom KVs.
No ineffective reasoning parameter was retained in the fix.

At temperature 0, **768 tokens still produced only reasoning for both prompts**.
At 1,536, both completed (cat: 1,258 total output tokens; vehicle: 1,392).
The final 2,048 ceiling leaves additional room. A later Strong UI vehicle run
actually used 1,689 tokens, confirming the need for this headroom.

## Measured helper latency

Times cover prompt completion, not image generation. These are individual local
measurements, not benchmark averages. Model load, cache state, and simultaneous
image-model residency affect latency.

| Prompt | Original 220 tokens, Normal | Fixed 2,048, Normal | Fixed 2,048, Strong | Actual installed UI, Strong |
| --- | ---: | ---: | ---: | ---: |
| Cat on fence | 1.826 s warm; 7.121 s initial load | 9.964 s | 9.201 s | 10.237 s |
| Armored vehicle | 3.756 s | 10.528 s | 12.692 s | 16.356 s |

All original-budget requests above had empty content and fell back. All fixed
acceptance calls completed with non-empty content and no fallback notice.

Normal cat output:

> a cat sitting on a weathered wooden picket fence, soft natural daylight casting gentle shadows, shallow depth of field with blurred background foliage, centered composition, highly detailed fur texture, photorealistic style

The Normal and Strong vehicle answers both retained the entire original sentence,
including **exactly eight wheels**, **matte black bodywork**, **no visible weapons**,
and **Tokyo at night**, then added camera, lighting, and material detail. Answers
were under 140 words in all four live cases.

## Verification

- `LIS_LIVE_PROMPT_TESTS=1 .../mflux/bin/python -m unittest discover -s tests -p test_prompt_improvement.py -v`
  — **10 tests passed**, 42.452 s, including four live model cases.
- Offline tests cover reasoning-only content, null/missing/invalid content,
  truncated answers, successful content and metrics, preservation instructions
  at every strength, timeout/HTTP errors, unavailable models, the small-model
  budget, and actual generation-job/storage fallback and success propagation.
  The storage test uses temporary directories and the existing `LIS_TEST_MODE`;
  it does not run image-model inference.
- Existing `tests/test_insert_validation.py` — both INSERT statements passed.
- Swift production sources compiled for arm64 macOS 13; installed app signature
  verification and `git diff --check` passed.
- Actual installed Local Image Studio: entered each acceptance prompt, clicked
  Generate, waited for real FLUX results, expanded Show Improved Prompt, checked
  the answer and helper metrics. Both succeeded without any fallback notice.
  The two generated test images remain in history.
- Failure UI: used the identical compiled Swift UI in a temporary app copy with
  separate test storage and a local HTTP fixture. The fixture returned HTTP 200,
  empty content, reasoning text, and `finish_reason: "length"`. The app displayed
  the inline status beside the prompt controls, completed using the original
  prompt, and persisted identical original/improved/generation prompt values.
  New Image worked immediately without dismissing a dialog and cleared the
  status; a subsequent successful fixture request had no stale status.
  The fixture and temporary app were stopped after testing.

The installed app received only the rebuilt executable and updated `backend_v2.py`
(plus code signing). Its existing `mflux_worker.py` and v1 `backend.py` were verified
byte-for-byte unchanged. The pre-existing working-tree changes to `mflux_worker.py`
and telemetry tests were left untouched. No schema, FLUX, SeedVR2, compatibility,
or upscale cleanup code was changed. A backup of the installed app before the fix
is at `/private/tmp/lis-prompt-check/Before Prompt Fix.app` (temporary storage).

## Limits

Thinking still runs; this is a measured token-budget fix, not a disabled-reasoning
claim. More demanding prompts may exhaust the ceiling or the existing 45-second
timeout and fall back safely. Temperature 0 uses greedy decoding but does not
promise bit-identical results across MLX runtime/cache conditions. Preservation is
instructed and was verified for the requested examples; it is not a general
semantic validator or a guarantee about the generated image.
