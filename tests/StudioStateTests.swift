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
        if CommandLine.arguments.contains("--restore") {
            let store = StudioStore(defaults: defaults)
            precondition(store.selectedImageModel == "flux2_klein_9b")
            precondition(store.workspace.modelId == "flux2_klein_9b")
            precondition(store.helperModelID == "server/exact-chat-id")
            defaults.removePersistentDomain(forName: suite)
            print("PASS: model preferences restored in a separate process")
            return
        }
        defaults.removePersistentDomain(forName: suite)
        let store = StudioStore(defaults: defaults)
        let decoder = JSONDecoder()
        store.models = try decoder.decode([ModelInfo].self, from: Data("""
        [{"id":"flux2_klein_4b","label":"4B","purpose":"generation","tagline":"Fast","status":"Installed"},
         {"id":"flux2_klein_9b","label":"9B","purpose":"generation","tagline":"Quality","status":"Installed"},
         {"id":"seedvr2_7b","label":"SeedVR2","purpose":"upscale","tagline":"Upscale","status":"Installed"}]
        """.utf8))
        precondition(store.generationModels.count == 2)
        store.chooseImageModel("flux2_klein_9b")
        store.chooseImageModel("seedvr2_7b")
        precondition(store.workspace.modelId == "flux2_klein_9b")
        store.chooseHelper("off")
        precondition(!store.promptImprovement)
        store.chooseHelper("server/exact-chat-id")
        precondition(store.promptImprovement && store.helperUnavailable)
        store.newImage()
        precondition(store.workspace.modelId == "flux2_klein_9b")
        defaults.synchronize()
        print("PASS: fit geometry, purpose filtering, independent selection and New Image state")
    }
}
