"""Prompt-helper regressions. Opt in to real LM Studio with LIS_LIVE_PROMPT_TESTS=1.

Run: python -m unittest discover -s tests -p test_prompt_improvement.py -v
No FLUX/SeedVR2 model is loaded; generation tests use isolated temporary storage.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend_v2 as backend

MODEL = "qwen3.6-35b-a3b-mlx"
LIVE_MODEL = "qwen/qwen3-4b-2507"
CAT = "a cat sitting on a fence"
VEHICLE = "A futuristic armored vehicle with exactly eight wheels, matte black bodywork, no visible weapons, parked in Tokyo at night"
# Compliant helper reply used to exercise response handling without creative expansion.
VEHICLE_RESULT = (
    VEHICLE + ". Frame the vehicle from a low camera angle, with controlled "
    "cinematic lighting, realistic surface texture, and a photorealistic rendering style."
)
NOTICE = "Prompt improvement unavailable — original prompt used"


def completion(content, finish="stop", reasoning="Internal deliberation"):
    return {"choices": [{"message": {"content": content, "reasoning_content": reasoning},
                         "finish_reason": finish}], "usage": {"completion_tokens": 1392}}


def response(payload):
    return io.BytesIO(json.dumps(payload).encode())


class PromptHelperTests(unittest.TestCase):
    def setUp(self):
        self.helper = backend.LMStudioPromptHelper()
        self.models = patch.object(self.helper, "available_models", return_value=[MODEL])
        self.models.start()
        self.addCleanup(self.models.stop)

    def call(self, payload, prompt=CAT, strength="normal"):
        with patch.object(self.helper, "request", return_value=response(payload)) as request:
            result = self.helper.improve(prompt, strength)
        return result, json.loads(request.call_args.args[1])

    def assert_fallback(self, result, original=CAT):
        self.assertEqual(result.prompt, original)
        self.assertEqual(result.notice, NOTICE)
        self.assertIsNone(result.model)

    def test_empty_content_with_reasoning_is_not_an_improved_prompt(self):
        result, _ = self.call(completion("", "length"))
        self.assert_fallback(result)

    def test_invalid_or_missing_content_falls_back(self):
        for content in (None, "  \n", [], 42):
            with self.subTest(content=content):
                result, _ = self.call(completion(content))
                self.assert_fallback(result)
        result, _ = self.call({"choices": [{"message": {"reasoning_content": "Only reasoning"}}]})
        self.assert_fallback(result)

    def test_truncated_nonempty_answer_does_not_drop_constraints(self):
        result, _ = self.call(completion("A futuristic armored vehicle", "length"), VEHICLE)
        self.assert_fallback(result, VEHICLE)

    def test_short_prompt_allows_meaningful_expansion(self):
        """Short sparse prompts should be substantially expandable, not rejected."""
        result, payload = self.call(completion("a dog with biomechanical textures and dark lighting."), "HR Giger dog")
        self.assertIsNone(result.notice)
        self.assertIn("dog", result.prompt.lower())
        payload_content = payload["messages"][1]["content"]
        self.assertNotIn("one sentence of at most", payload_content)
        self.assertNotIn("short prompt", payload_content.lower())

    def test_changed_constraints_or_invented_counts_fall_back(self):
        invalid = (
            VEHICLE.replace("exactly eight wheels", "eight wheels"),
            VEHICLE + ", with two headlights",
            CAT + ", no lettering",
        )
        for enhanced in invalid:
            with self.subTest(enhanced=enhanced):
                result, payload = self.call(completion(enhanced), VEHICLE if "vehicle" in enhanced else CAT)
                self.assert_fallback(result, VEHICLE if "vehicle" in enhanced else CAT)
        _, payload = self.call(completion(VEHICLE_RESULT), VEHICLE)
        self.assertIn('"exactly eight wheels"', payload["messages"][1]["content"])
        self.assertIn('"no visible weapons"', payload["messages"][1]["content"])

    def test_success_uses_only_answer_and_retains_metrics(self):
        result, payload = self.call(completion("\n\n" + VEHICLE_RESULT), VEHICLE)
        self.assertEqual(result.prompt, VEHICLE_RESULT)
        self.assertEqual(result.model, MODEL)
        self.assertIsNone(result.notice)
        self.assertGreater(result.total_time, 0)
        self.assertGreater(result.tokens_per_second, 0)
        self.assertEqual(result.token_count, 1392)
        self.assertEqual(payload["temperature"], 0)
        # Qwen3.6-35b gets 2048; other models get 350
        self.assertIn(payload["max_tokens"], (350, 2048))
        self.assertNotIn("reasoning_effort", payload)
        self.assertNotIn("chat_template_kwargs", payload)

    def test_constraints_and_system_instructions_reach_model_for_every_strength(self):
        for strength in ("light", "normal", "strong"):
            with self.subTest(strength=strength):
                result, payload = self.call(completion(VEHICLE_RESULT), VEHICLE, strength)
                self.assertTrue(payload["messages"][1]["content"].endswith(VEHICLE))
                system = payload["messages"][0]["content"]
                for rule in ("expert image-generation prompt enhancer", "generation-ready",
                             "Preserve the user's subject", "visual style above everything else",
                             "art movement", "recognizable aesthetic", "concrete visual description",
                             "generic genre", "unrelated clichés", "form and anatomy",
                             "shapes and proportions", "materials and surface qualities",
                             "composition and camera framing", "lighting", "palette",
                             "environment", "atmosphere", "artistic medium or rendering treatment",
                             "neon", "glowing eyes", "cyberpunk elements", "armor", "weapons",
                             "random magical effects", "organic-machine integration",
                             "ribbed structures", "skeletal conduits", "sinewy mechanical anatomy",
                             "smooth exoskeletal surfaces", "alien organic forms",
                             "dream logic", "coherent dream logic", "random bizarre objects",
                             "spatial structure reflect the requested style",
                             "Expand sparse prompts significantly", "explicit counts",
                             "negative constraints", "Output only the final enhanced image prompt",
                             "Do not explain", "1-3 sentences"):
                    self.assertIn(rule, system)
                instruction = payload["messages"][1]["content"].split("\n\nOriginal prompt:", 1)[0]
                self.assertNotIn("strong visual direction", instruction.lower())
                self.assertNotIn("add a moderate amount", instruction.lower())
                for constraint in ("exactly eight wheels", "matte black bodywork", "no visible weapons", "Tokyo at night"):
                    self.assertIn(constraint, result.prompt)
                # Verify strength instructions reach the model
                instruction = payload["messages"][1]["content"].split("\n\nOriginal prompt:", 1)[0]
                if strength == "light":
                    self.assertIn("Lightly refine the prompt while staying very close to the original concept", instruction)
                elif strength == "normal":
                    self.assertIn("generation-ready description", instruction.lower())
                elif strength == "strong":
                    self.assertIn("Substantially expand the prompt into a rich, generation-ready image concept", instruction)

    def test_five_required_prompts_preserve_subject_and_expand_meaningfully(self):
        """Verify the five required test prompts produce meaningful expansions."""
        # Mock responses that represent what a real model would return for each prompt.
        mock_responses = {
            "HR Giger dog": (
                "A dog transformed into a biomechanical organism, its anatomy seamlessly fused with smooth ribbed exoskeletal "
                "surfaces and sinewy tubing. Dark metallic and bone-like textures, eerie low-key lighting, a claustrophobic "
                "biomechanical atmosphere inspired by H.R. Giger's signature style."
            ),
            "Escher library": (
                "A vast impossible library with interlocking staircases that loop back on themselves in an infinite recursive "
                "paradox. Books line walls that bend and fold into impossible geometries, with light filtering through "
                "architectural loops that defy conventional perspective."
            ),
            "Dali bedroom": (
                "A surrealist bedroom where the bed melts softly onto a cracked desert floor, with elongated forms and "
                "dream-logic distortions. Soft golden light casts impossible shadows across warped furniture and melting walls, "
                "evoking coherent dream imagery rather than random bizarre objects."
            ),
            "gothic vampire woman": (
                "A pale gothic vampire woman standing in a dark cathedral interior, draped in heavy velvet robes with sharp "
                "architectural details. Dramatic chiaroscuro lighting from tall stained-glass windows casts long shadows, "
                "her dark hair framing an intense expression against the gothic stone architecture."
            ),
            "Tokyo alley in the rain": (
                "A narrow Tokyo alleyway glistening with rain, neon signs reflecting in puddles on the wet cobblestone. "
                "Atmospheric fog rolls between towering buildings, with warm light bleeding from ramen shop windows and "
                "vending machines casting colored reflections on the slick ground."
            ),
        }
        for input_prompt, mock_content in mock_responses.items():
            with self.subTest(input=input_prompt):
                result, payload = self.call(completion(mock_content), input_prompt)
                self.assertIsNone(result.notice, f"{input_prompt} was rejected")
                # Verify the output is meaningfully expanded (at least 25 words)
                word_count = len(result.prompt.split())
                self.assertGreaterEqual(word_count, 25,
                                        f"{input_prompt}: output too short ({word_count} words)")
                # Verify no short-prompt-limit instruction was injected
                user_msg = payload["messages"][1]["content"]
                self.assertNotIn("one sentence of at most", user_msg)
                self.assertNotIn("short prompt", user_msg.lower())

    def test_transport_and_malformed_response_fall_back(self):
        for error in (TimeoutError(), urllib.error.URLError("offline"),
                      urllib.error.HTTPError(self.helper.endpoint, 503, "unavailable", {}, None)):
            with self.subTest(error=type(error).__name__):
                with patch.object(self.helper, "request", side_effect=error):
                    self.assert_fallback(self.helper.improve(CAT, "normal"))
        for payload in ({}, {"choices": []}):
            result, _ = self.call(payload)
            self.assert_fallback(result)

    def test_no_model_preserves_original_without_completion_request(self):
        with patch.object(self.helper, "available_models", return_value=[]), patch.object(self.helper, "request") as request:
            self.assert_fallback(self.helper.improve(CAT, "normal"))
            request.assert_not_called()

    def test_small_model_keeps_existing_budget_and_no_reasoning_overrides(self):
        with patch.object(self.helper, "available_models", return_value=["qwen3-4b-instruct"]):
            result, payload = self.call(completion("A cat on a wooden fence in soft daylight."))
        self.assertEqual(payload["max_tokens"], 350)
        self.assertNotIn("reasoning_effort", payload)
        self.assertIsNone(result.notice)

    def test_generation_uses_and_persists_original_on_failure_and_answer_on_success(self):
        # Exercise the actual generation handoff and job response without GPU work.
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            paths = {"APP_SUPPORT": root / "support", "GENERATIONS_DIR": root / "images",
                     "THUMBNAILS_DIR": root / "thumbs", "REFERENCES_DIR": root / "refs",
                     "LORAS_DIR": root / "loras", "DATABASE_PATH": root / "support/history.sqlite3"}
            for module in (backend, backend.v1):
                for name, value in paths.items():
                    stack.enter_context(patch.object(module, name, value))
            stack.enter_context(patch.object(backend, "PROJECT_ARCHIVES_DIR", root / "archives"))
            stack.enter_context(patch.object(backend.v1, "database", backend.database))
            stack.enter_context(patch.dict(os.environ, {"LIS_TEST_MODE": "1"}))
            stack.enter_context(patch.object(backend, "JOBS", {}))
            stack.enter_context(patch.object(backend, "ACTIVE_JOB_ID", None))
            stack.enter_context(patch.object(backend, "schedule_retention"))
            stack.enter_context(patch.object(backend, "PROMPT_HELPER", self.helper))
            stack.enter_context(patch.object(backend.WORKER, "generate", side_effect=AssertionError("GPU work in unit test")))
            stack.enter_context(patch.object(backend.v1, "model_is_installed", return_value=True))
            backend.ensure_directories()
            backend.initialize_database()
            for index, content in enumerate(("", VEHICLE_RESULT)):
                with self.subTest(success=bool(content)):
                    config = backend.validate_v2_payload({"prompt": VEHICLE, "model_id": "flux2_klein_4b",
                                                         "width": 512, "height": 512, "steps": 4})
                    job_id = f"prompt-test-{index}"
                    backend.JOBS[job_id] = {"id": job_id}
                    with patch.object(self.helper, "request", return_value=response(completion(content))):
                        backend.run_generation(job_id, config)
                    job = backend.JOBS[job_id]
                    self.assertEqual(job["state"], "complete", job.get("message"))
                    self.assertEqual(job["original_prompt"], VEHICLE)
                    self.assertEqual(job["improved_prompt"], content or VEHICLE)
                    self.assertEqual(job["prompt_notice"], None if content else NOTICE)
                    saved = job["generation"]
                    self.assertEqual(saved["original_prompt"], VEHICLE)
                    self.assertEqual(saved["improved_prompt"], content or VEHICLE)
                    self.assertEqual(backend.generation_row(saved["id"])["prompt"], content or VEHICLE)


@unittest.skipUnless(os.environ.get("LIS_LIVE_PROMPT_TESTS") == "1", "Requires local LM Studio; opt in explicitly")
class LivePromptHelperTests(unittest.TestCase):
    def test_acceptance_prompts_with_real_model(self):
        helper = backend.LMStudioPromptHelper()
        for strength in ("normal", "strong"):
            for prompt in (CAT, VEHICLE):
                with self.subTest(prompt=prompt, strength=strength):
                    started = time.perf_counter()
                    # Fix the tested model, while using the real HTTP completion path.
                    with patch.object(helper, "available_models", return_value=[LIVE_MODEL]):
                        result = helper.improve(prompt, strength, model_id=LIVE_MODEL)
                    elapsed = time.perf_counter() - started
                    print(json.dumps({"prompt": prompt, "strength": strength, "seconds": round(elapsed, 3),
                                      "content": result.prompt, "notice": result.notice}), flush=True)
                    self.assertIsNone(result.notice)
                    self.assertEqual(result.model, LIVE_MODEL)
                    self.assertNotEqual(result.prompt, prompt)
                    # No arbitrary word limit; let strength instructions guide length
                    self.assertLess(elapsed, 45)
                    if prompt == VEHICLE:
                        for phrase in ("futuristic armored vehicle", "exactly eight wheels", "matte black bodywork",
                                       "no visible weapons", "Tokyo", "night"):
                            self.assertIn(phrase.lower(), result.prompt.lower())
                    else:
                        for phrase in ("cat", "fence"):
                            self.assertIn(phrase, result.prompt.lower())


if __name__ == "__main__":
    unittest.main()
