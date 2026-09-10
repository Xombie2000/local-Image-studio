import AppKit
import Foundation

@main
struct StudioStateTests {
    @MainActor static func main() throws {
        let viewport = CGSize(width: 800, height: 600)
        let small = CanvasSizing.fit(image: CGSize(width: 512, height: 512), viewport: viewport)
        let large = CanvasSizing.fit(image: CGSize(width: 2048, height: 2048), viewport: viewport)
        precondition(small == large && small == CGSize(width: 560, height: 560))
        for size in [CGSize(width: 512, height: 1024), CGSize(width: 2048, height: 1024)] {
            for canvas in [viewport, CGSize(width: 360, height: 300), CGSize(width: 1000, height: 800)] {
                let fit = CanvasSizing.fit(image: size, viewport: canvas)
                precondition(fit.width <= canvas.width - 40 && fit.height <= canvas.height - 40)
                precondition(abs(fit.width / fit.height - size.width / size.height) < 0.0001)
            }
        }
        let upscale = UpscaleJob(sourceGenerationId: "source", projectId: "source-project")
        precondition(upscale.requestPayload["project_id"] as? String == "source-project")
        precondition(upscale.requestPayload["source_generation_id"] as? String == "source")
        precondition(UpscaleJob(sourceGenerationId: "ungrouped").requestPayload["project_id"] == nil)
        precondition(HelperPresentation.name(for: "qwen/qwen3-4b-2507") == "Qwen3 4B Instruct")
        precondition(HelperPresentation.name(for: "lms::qwen/qwen3-4b-2507") == "LMS — Qwen3 4B Instruct")
        precondition(HelperPresentation.name(for: "omlx::qwen/custom:thinking") == "oMLX — Custom:Thinking")
        precondition(!HelperPresentation.name(for: "qwen/qwen3-4b-2507").contains("6-bit"))
        precondition(HelperPresentation.name(for: "organization/custom-model") == "Custom Model")
        let missingMetrics = PromptHelperMetrics(model: "qwen/qwen3-4b-2507", tokensPerSecond: 0, timeToFirstToken: nil, tokenCount: 0, totalTime: nil)
        precondition(!missingMetrics.hasDisplayMetrics)
        let validMetrics = PromptHelperMetrics(model: "qwen/qwen3-4b-2507", tokensPerSecond: 185, timeToFirstToken: nil, tokenCount: 126, totalTime: 1.3)
        precondition(validMetrics.displayParts == ["185 tok/s", "1.3 s", "126 tokens"])
        precondition(PromptEditorSizing.height(for: "short") == 38)
        precondition(PromptEditorSizing.height(for: "1\n2\n3\n4\n5\n6") == 72)
        let suite = "LocalImageStudio.RedesignStateTests"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        let store = StudioStore(defaults: defaults)
        let decoder = JSONDecoder()
        store.models = try decoder.decode([ModelInfo].self, from: Data("""
        [{"id":"flux2_klein_4b","label":"4B","purpose":"generation","tagline":"Fast","status":"Installed"},
         {"id":"flux2_klein_9b","label":"9B","purpose":"generation","tagline":"Quality","status":"Installed"},
         {"id":"krea2_turbo","label":"Krea 2 Turbo","purpose":"generation","tagline":"12B · q8","status":"Installed"},
         {"id":"seedvr2_7b","label":"SeedVR2","purpose":"upscale","tagline":"Upscale","status":"Installed"}]
        """.utf8))
        precondition(store.generationModels.count == 3)
        store.chooseImageModel("krea2_turbo")
        precondition(store.workspace.modelId == "krea2_turbo")
        precondition(store.workspace.steps == 8 && store.workspace.quantization == 8)
        store.chooseImageModel("flux2_klein_4b")
        precondition(store.workspace.steps == 4 && store.workspace.quantization == nil)
        store.chooseImageModel("flux2_klein_9b")
        store.chooseImageModel("seedvr2_7b")
        precondition(store.workspace.modelId == "flux2_klein_9b")
        store.chooseHelper("off")
        precondition(!store.promptImprovement)
        store.chooseHelper("server/exact-chat-id")
        precondition(store.promptImprovement && store.helperUnavailable)
        store.promptHelper = PromptHelperAvailability(models: ["lms::server/exact-chat-id", "omlx::server/exact-chat-id"], available: true, model: "lms::server/exact-chat-id", notice: nil)
        store.restoreModelPreferences()
        precondition(store.helperModelID == "lms::server/exact-chat-id" && !store.helperUnavailable)
        store.chooseImageModel("krea2_turbo")
        store.select(generation("krea-image", project: nil, model: "krea2_turbo"))
        store.editSelected()
        precondition(store.workspace.mode == .edit)
        precondition(store.workspace.modelId == "flux2_klein_4b")
        precondition(store.workspace.referenceGenerationId == "krea-image")
        precondition(store.workspace.steps == 4 && store.workspace.quantization == nil)
        precondition(store.selectedImageModel == "krea2_turbo")
        precondition(store.notice?.contains("Krea 2 Turbo remains selected") == true)
        store.chooseImageModel("flux2_klein_9b")
        store.newImage()
        precondition(store.workspace.modelId == "flux2_klein_9b")
        checkEnhancement(store)
        checkProjects(store)
        store.chooseImageModel("krea2_turbo")
        defaults.synchronize()
        let restored = StudioStore(defaults: defaults)
        precondition(restored.selectedImageModel == "krea2_turbo")
        precondition(restored.workspace.modelId == "krea2_turbo")
        precondition(restored.workspace.steps == 8 && restored.workspace.quantization == 8)
        precondition(restored.helperModelID == "lms::server/exact-chat-id")
        restored.projects = [project("A"), project("B")]
        restored.generations = [generation("image-A", project: "A")]
        restored.restoreProjectSelection()
        precondition(restored.selectedProjectId == "B" && restored.selectedGeneration == nil)
        precondition(restored.workspace.projectId == "B")
        restored.selectProject(nil)
        let allImages = StudioStore(defaults: defaults)
        allImages.projects = restored.projects
        allImages.generations = restored.generations
        allImages.restoreProjectSelection()
        precondition(allImages.selectedProjectId == nil && allImages.selectedGeneration?.id == "image-A")
        restored.selectProject("A")
        let deletedAtRestart = StudioStore(defaults: defaults)
        deletedAtRestart.projects = [project("B")]
        deletedAtRestart.restoreProjectSelection()
        precondition(deletedAtRestart.selectedProjectId == nil && deletedAtRestart.selectedGeneration == nil)
        defaults.removePersistentDomain(forName: suite)
        print("PASS: model and project preferences restored; All Images and deleted-project recovery")
        print("PASS: fit geometry, purpose filtering, independent selection and New Image state")
    }

    static func project(_ id: String) -> ProjectInfo {
        ProjectInfo(id: id, name: id, archived: false, generationCount: id == "A" ? 1 : 0, createdAt: "", updatedAt: "")
    }

    static func generation(_ id: String, project: String?, model: String = "flux2_klein_4b") -> Generation {
        Generation(id: id, parentId: nil, projectId: project, originalPrompt: "cat", improvedPrompt: "cat",
                   promptImprovementModel: nil, promptImprovementStrength: nil,
                   promptHelper: PromptHelperMetrics(model: nil, tokensPerSecond: nil, timeToFirstToken: nil, tokenCount: nil, totalTime: nil),
                   modelId: model, model: model == "krea2_turbo" ? "Krea 2 Turbo" : "FLUX 4B", quantization: nil, quantizationLabel: "None", seed: 42,
                   width: 512, height: 512, steps: 4, generationTime: 1, secondsPerImage: 1, stepsPerSecond: 4,
                   peakMemoryBytes: nil, gpuUtilization: nil, referenceUsed: false, referenceSourceId: nil,
                   referenceImagePath: nil, loraName: nil, loraScale: nil, variantGroupId: nil, variantIndex: 1,
                   variantCount: 1, generationGroupId: nil, createdAt: "", imagePath: "/tmp/test.png", thumbnailPath: nil,
                   filename: "test.png", archived: false, upscaleSourceWidth: 0, upscaleSourceHeight: 0,
                   upscaleScaleFactor: nil, upscaleModelVariant: nil, upscalePrecision: nil)
    }

    @MainActor static func checkProjects(_ store: StudioStore) {
        let a = project("A"), b = project("B")
        let image = generation("image-A", project: "A")
        store.projects = [a, b]
        store.generations = [image]
        for _ in 0..<3 {
            store.selectProject("A")
            precondition(store.selectedGeneration?.projectId == "A")
            store.selectProject("B")
            precondition(store.selectedGeneration == nil && store.visibleHistory.isEmpty)
            precondition(store.workspace.mode == .newImage && store.workspace.projectId == "B")
            precondition(store.workspace.parentId == nil && store.workspace.referenceGenerationId == nil)
            store.workspace.originalPrompt = "A military attack drone from 2100"
            precondition(store.generationPayload()["project_id"] as? String == "B")
            precondition(store.generationPayload()["parent_id"] == nil)
        }
        store.selectProject("A")
        store.selectProject(nil)
        precondition(store.selectedProjectId == nil && store.selectedGeneration?.id == image.id)
        precondition(store.visibleHistory.count == 1)
        store.newImage()
        precondition(store.generationPayload()["project_id"] == nil)
        store.select(image)
        precondition(store.selectedProjectId == nil) // All Images remains global.
        precondition(store.workspace.randomSeed && store.workspace.seed == image.seed)
        store.forkSelected()
        precondition(!store.workspace.randomSeed && store.workspace.seed == image.seed)
        store.select(image)
        store.newImage()
        precondition(store.workspace.randomSeed)
        store.select(image)
        store.chooseDraftProject("B")
        precondition(store.selectedGeneration == nil && store.selectedProjectId == "B")
        precondition(store.workspace.originalPrompt == "cat" && store.workspace.parentId == nil)
        precondition(store.workspace.randomSeed)
        store.selectProject("A")
        store.newImage(in: b)
        precondition(store.selectedProjectId == "B" && store.selectedGeneration == nil)
        precondition(store.workspace.projectId == "B" && store.workspace.parentId == nil)
        precondition(store.workspace.randomSeed)
        store.selectProject("A")
        store.activateCreatedProject(project("backend-canonical-id"))
        precondition(store.selectedProjectId == "backend-canonical-id" && store.selectedGeneration == nil)
        precondition(store.generationPayload()["project_id"] as? String == "backend-canonical-id")
        store.workspace.originalPrompt = "keep my draft"
        precondition(!store.validateGenerationDestination(projects: [a, b], generations: [image]))
        precondition(store.selectedProjectId == nil && store.workspace.projectId == nil)
        precondition(store.workspace.originalPrompt == "keep my draft" && store.notice != nil)
        store.selectProject("A")
        store.projects = [b]
        store.generations = [generation(image.id, project: nil)]
        store.reconcileProjectSelection()
        precondition(store.selectedProjectId == nil && store.selectedGeneration == nil && store.workspace.parentId == nil)
        store.projects = [a, b]
        store.selectProject("A")
        store.selectProject("B") // Empty selection is restored by the next process.
        print("PASS: A → empty B → A, request destination, creation, deletion, draft target and All Images")
    }

    @MainActor static func checkEnhancement(_ store: StudioStore) {
        let raw = "  a cat sitting on a fence\nKeep punctuation: 日本語.  "
        let metrics = PromptHelperMetrics(model: "exact-helper-id", tokensPerSecond: 20, timeToFirstToken: nil, tokenCount: 40, totalTime: 2)
        let success = PromptEnhancementResponse(prompt: "A cat on a weathered fence.", enhanced: true, notice: nil, promptHelper: metrics)
        let failure = PromptEnhancementResponse(prompt: "must not replace editor", enhanced: false, notice: "Helper unavailable", promptHelper: metrics)
        func checkPayload(_ text: String) {
            let payload = store.generationPayload()
            precondition(payload["prompt"] as? String == text)
            precondition(payload["prompt_improvement"] as? Bool == false)
            precondition(payload["prompt_is_final"] as? Bool == true)
            precondition(payload["improved_prompt_override"] == nil)
        }
        store.workspace.originalPrompt = raw
        checkPayload(raw)
        store.applyEnhancement(success, original: raw)
        precondition(store.workspace.originalPrompt == success.prompt && store.preEnhancementPrompt == raw && store.isEnhanced)
        precondition(store.activeJob == nil)
        checkPayload(success.prompt)
        store.workspace.originalPrompt += "\nNo lettering.  "
        checkPayload(store.workspace.originalPrompt)
        store.revertPrompt()
        precondition(store.workspace.originalPrompt == raw && store.preEnhancementPrompt == nil && !store.isEnhanced)
        checkPayload(raw)
        store.applyEnhancement(failure, original: raw)
        precondition(store.workspace.originalPrompt == raw && store.errorMessage == nil && store.promptImprovementNotice != nil)
        checkPayload(raw)
        store.chooseHelper("off")
        checkPayload(raw)
        store.chooseHelper("lms::server/exact-chat-id")
        store.applyEnhancement(success, original: raw)
        let secondOriginal = store.workspace.originalPrompt + " manually edited"
        store.workspace.originalPrompt = secondOriginal
        store.applyEnhancement(success, original: secondOriginal)
        store.revertPrompt()
        precondition(store.workspace.originalPrompt == secondOriginal)
        store.applyEnhancement(success, original: secondOriginal)
        store.newImage()
        precondition(store.preEnhancementPrompt == nil && !store.isEnhanced)
        store.applyEnhancement(success, original: "another original")
        store.select(generation("image", project: nil))
        precondition(store.preEnhancementPrompt == nil && !store.isEnhanced)
        store.projects = [project("temporary")]
        store.applyEnhancement(success, original: "old project")
        store.selectProject("temporary")
        precondition(store.preEnhancementPrompt == nil && !store.isEnhanced)
        store.selectProject(nil)
        store.projects = []
        store.newImage()
        print("PASS: exact visible prompt payload, enhance/edit/revert/Off/failure, repeated Enhance, and workspace isolation")
    }
}
