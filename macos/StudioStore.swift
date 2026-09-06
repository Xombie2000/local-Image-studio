import AppKit
import Foundation
import UniformTypeIdentifiers

@MainActor
final class StudioStore: ObservableObject {
    static let shared = StudioStore()

    @Published var generations: [Generation] = []
    @Published var projects: [ProjectInfo] = []
    @Published var models: [ModelInfo] = []
    @Published var loras: [LoRAInfo] = []
    @Published var selectedGeneration: Generation?
    @Published var selectedProjectId: String?
    @Published var workspace = WorkspaceState()
    @Published var activeJob: GenerationJob?
    @Published var modelStatus = ModelRuntimeStatus.unloaded
    @Published var promptHelper = PromptHelperAvailability(available: false, model: nil, notice: nil)
    @Published var isLoading = true
    @Published var errorMessage: String?
    @Published var notice: String?
    @Published var showModels = false
    @Published var showUpscaleSheet = false
    @Published var showImprovedPrompt = false
    @Published var showAdvanced = false
    @Published var projectsExpanded = true
    @Published var historyExpanded = true
    @Published var projectEditor: ProjectEditor?
    @Published var confirmation: Confirmation?

    var promptImprovement: Bool {
        get { UserDefaults.standard.object(forKey: "promptImprovement") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "promptImprovement"); objectWillChange.send() }
    }
    var promptStrength: String {
        get { UserDefaults.standard.string(forKey: "promptStrength") ?? "normal" }
        set { UserDefaults.standard.set(newValue, forKey: "promptStrength"); objectWillChange.send() }
    }
    var modelRetention: String {
        get { UserDefaults.standard.string(forKey: "modelRetention") ?? "automatic" }
        set { UserDefaults.standard.set(newValue, forKey: "modelRetention"); objectWillChange.send() }
    }

    let backend = BackendController.shared
    private var pollTask: Task<Void, Never>?

    struct ProjectEditor: Identifiable {
        let id = UUID()
        let projectId: String?
        var name: String
        var title: String { projectId == nil ? "New Project" : "Rename Project" }
    }

    struct Confirmation: Identifiable {
        let id = UUID()
        let title: String
        let message: String
        let destructive: Bool
        let action: @MainActor () -> Void
    }

    private init() {}

    func load() async {
        isLoading = true
        do {
            let bootstrap: BootstrapResponse = try await backend.get("/api/bootstrap")
            models = bootstrap.models
            generations = bootstrap.generations
            projects = bootstrap.projects
            loras = bootstrap.loras
            modelStatus = bootstrap.modelStatus
            promptHelper = bootstrap.promptHelper
            if let active = bootstrap.activeJob {
                activeJob = active
                poll(jobId: active.id)
            } else if let first = generations.first {
                select(first)
            } else {
                newImage()
            }
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    func refresh() async {
        do {
            let bootstrap: BootstrapResponse = try await backend.get("/api/bootstrap")
            models = bootstrap.models
            generations = bootstrap.generations
            projects = bootstrap.projects
            loras = bootstrap.loras
            modelStatus = bootstrap.modelStatus
            promptHelper = bootstrap.promptHelper
            if let selected = selectedGeneration, let updated = generations.first(where: { $0.id == selected.id }) {
                selectedGeneration = updated
            }
        } catch { errorMessage = error.localizedDescription }
    }

    func newImage() {
        let carried = workspace
        selectedGeneration = nil
        selectedProjectId = nil
        workspace = WorkspaceState(
            mode: .newImage,
            originalPrompt: "",
            improvedPrompt: "",
            modelId: carried.modelId,
            width: carried.width,
            height: carried.height,
            steps: carried.steps,
            quantization: carried.quantization,
            randomSeed: carried.randomSeed,
            seed: carried.seed,
            variantCount: carried.variantCount,
            parentId: nil,
            projectId: carried.projectId,
            referenceGenerationId: nil,
            referenceData: nil,
            referencePath: nil,
            referenceName: nil,
            loraId: carried.loraId,
            loraScale: carried.loraScale
        )
        showImprovedPrompt = false
    }

    func select(_ generation: Generation) {
        selectedGeneration = generation
        selectedProjectId = generation.projectId
        workspace = WorkspaceState(
            mode: .viewing,
            originalPrompt: generation.originalPrompt,
            improvedPrompt: generation.improvedPrompt,
            modelId: generation.modelId,
            width: generation.width,
            height: generation.height,
            steps: generation.steps,
            quantization: generation.quantization,
            randomSeed: false,
            seed: generation.seed,
            variantCount: 1,
            parentId: generation.id,
            projectId: generation.projectId,
            referenceGenerationId: nil,
            referenceData: nil,
            referencePath: nil,
            referenceName: nil,
            loraId: loras.first(where: { $0.name == generation.loraName })?.id,
            loraScale: generation.loraScale ?? 1
        )
    }

    func forkSelected() {
        guard let generation = selectedGeneration else { return }
        select(generation)
        selectedGeneration = nil
        workspace.mode = .fork
        workspace.parentId = generation.id
        workspace.randomSeed = false
        workspace.referenceGenerationId = generation.referenceSourceId
        workspace.referencePath = generation.referenceSourceId == nil ? generation.referenceImagePath : nil
        workspace.referenceName = generation.referenceImagePath.map { URL(fileURLWithPath: $0).lastPathComponent }
        notice = "Fork created. The parent remains unchanged."
    }

    func editSelected() {
        guard let generation = selectedGeneration else { return }
        select(generation)
        selectedGeneration = nil
        workspace.mode = .edit
        workspace.parentId = generation.id
        workspace.referenceGenerationId = generation.id
        workspace.referenceName = generation.filename
        workspace.originalPrompt = ""
        workspace.improvedPrompt = ""
        workspace.randomSeed = true
        notice = "Edit fork created with the source image attached."
    }

    func regenerateSelected() {
        guard let generation = selectedGeneration else { return }
        select(generation)
        selectedGeneration = nil
        workspace.mode = .fork
        workspace.parentId = generation.id
        workspace.randomSeed = false
        Task { await generate() }
    }

    func variationSelected() {
        guard let generation = selectedGeneration else { return }
        select(generation)
        selectedGeneration = nil
        workspace.mode = .fork
        workspace.parentId = generation.id
        workspace.randomSeed = true
        workspace.improvedPrompt = generation.improvedPrompt
        Task { await generate() }
    }

    func generate() async {
        guard activeJob == nil else { return }
        let prompt = workspace.originalPrompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty else { errorMessage = workspace.mode == .edit ? "Describe what should change." : "Enter a prompt before generating."; return }
        var payload: [String: Any] = [
            "prompt": prompt,
            "model_id": workspace.modelId,
            "width": workspace.width,
            "height": workspace.height,
            "steps": workspace.steps,
            "quantization": workspace.quantization.map(String.init) ?? "none",
            "random_seed": workspace.randomSeed,
            "seed": workspace.seed,
            "variant_count": workspace.variantCount,
            "prompt_improvement": promptImprovement,
            "prompt_improvement_strength": promptStrength,
            "model_retention": modelRetention,
            "lora_scale": workspace.loraScale,
        ]
        if let parentId = workspace.parentId { payload["parent_id"] = parentId }
        if let projectId = workspace.projectId { payload["project_id"] = projectId }
        if let reference = workspace.referenceGenerationId { payload["reference_generation_id"] = reference }
        if let data = workspace.referenceData { payload["reference_data"] = data }
        if let path = workspace.referencePath { payload["reference_path"] = path }
        if let lora = workspace.loraId { payload["lora_id"] = lora }
        if !workspace.improvedPrompt.isEmpty && workspace.mode != .newImage {
            payload["improved_prompt_override"] = workspace.improvedPrompt
        }
        do {
            let job: GenerationJob = try await backend.post("/api/generate", json: payload)
            activeJob = job
            poll(jobId: job.id)
        } catch { errorMessage = error.localizedDescription }
    }

    private func poll(jobId: String) {
        pollTask?.cancel()
        pollTask = Task {
            while !Task.isCancelled {
                do {
                    try await Task.sleep(nanoseconds: 700_000_000)
                    let job: GenerationJob = try await backend.get("/api/jobs/\(jobId)")
                    activeJob = job
                    if let status = job.modelStatus { modelStatus = status }
                    if let original = job.originalPrompt { workspace.originalPrompt = original }
                    if let improved = job.improvedPrompt { workspace.improvedPrompt = improved }
                    if let promptNotice = job.promptNotice { notice = promptNotice }
                    if job.state == "complete" {
                        let results = job.generations ?? job.generation.map { [$0] } ?? []
                        generations.insert(contentsOf: results.reversed(), at: 0)
                        if let first = results.first { select(first) }
                        activeJob = nil
                        await refreshStatus()
                        return
                    }
                    if job.state == "error" {
                        errorMessage = job.message
                        activeJob = nil
                        await refreshStatus()
                        return
                    }
                } catch is CancellationError { return }
                catch { errorMessage = error.localizedDescription; activeJob = nil; return }
            }
        }
    }

    func refreshStatus() async {
        do {
            let status: StatusResponse = try await backend.get("/api/status")
            modelStatus = status.modelStatus
        } catch {}
    }

    func unloadForMemoryPressure() async {
        guard activeJob == nil else { return }
        do {
            let response: UnloadResponse = try await backend.post("/api/model/unload")
            modelStatus = response.modelStatus
            notice = "Model unloaded because macOS reported memory pressure."
        } catch {}
    }

    struct UnloadResponse: Codable { let ok: Bool; let modelStatus: ModelRuntimeStatus }

    func chooseReferenceImage() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.png, .jpeg, .webP]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        if panel.runModal() == .OK, let url = panel.url { attachReference(url) }
    }

    func attachReference(_ url: URL) {
        do {
            let data = try Data(contentsOf: url)
            guard data.count <= 30 * 1024 * 1024 else { throw BackendError.message("Reference images must be smaller than 30 MB.") }
            let type = UTType(filenameExtension: url.pathExtension.lowercased())
            let mime = type == .jpeg ? "image/jpeg" : type == .webP ? "image/webp" : "image/png"
            workspace.referenceData = "data:\(mime);base64,\(data.base64EncodedString())"
            workspace.referenceGenerationId = nil
            workspace.referencePath = nil
            workspace.referenceName = url.lastPathComponent
        } catch { errorMessage = error.localizedDescription }
    }

    func clearReference() {
        workspace.referenceData = nil
        workspace.referenceGenerationId = nil
        workspace.referencePath = nil
        workspace.referenceName = nil
    }

    func copyImage() {
        guard let path = selectedGeneration?.imagePath, let image = NSImage(contentsOfFile: path) else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.writeObjects([image])
        notice = "Image copied."
    }

    func exportImage() {
        guard let generation = selectedGeneration, let image = NSImage(contentsOfFile: generation.imagePath) else { return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = generation.filename
        panel.allowedContentTypes = [.png, .jpeg]
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            if url.pathExtension.lowercased() == "jpg" || url.pathExtension.lowercased() == "jpeg" {
                guard let tiff = image.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                      let data = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.92]) else { throw BackendError.message("Could not encode JPEG.") }
                try data.write(to: url, options: .atomic)
            } else {
                try FileManager.default.copyItem(at: URL(fileURLWithPath: generation.imagePath), to: url)
            }
            notice = "Image exported."
        } catch { errorMessage = error.localizedDescription }
    }

    func revealImage() {
        guard let generation = selectedGeneration else { return }
        Task {
            do { let _: OKResponse = try await backend.post("/api/generations/\(generation.id)/reveal") }
            catch { errorMessage = error.localizedDescription }
        }
    }

    func requestDeleteGeneration() {
        guard let generation = selectedGeneration else { return }
        confirmation = Confirmation(
            title: "Delete Generation?",
            message: "This removes the image file and metadata. Forks remain and are reattached to the deleted image’s parent.",
            destructive: true
        ) { [weak self] in self?.deleteGeneration(generation) }
    }

    private func deleteGeneration(_ generation: Generation) {
        Task {
            do {
                let _: OKResponse = try await backend.delete("/api/generations/\(generation.id)")
                generations.removeAll { $0.id == generation.id }
                selectedGeneration = nil
                newImage()
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func createProject() { projectEditor = ProjectEditor(projectId: nil, name: "") }
    func editProject(_ project: ProjectInfo) { projectEditor = ProjectEditor(projectId: project.id, name: project.name) }

    func saveProjectEditor(_ editor: ProjectEditor) {
        Task {
            do {
                let project: ProjectInfo
                if let id = editor.projectId {
                    project = try await backend.post("/api/projects/\(id)/rename", json: ["name": editor.name])
                    if let index = projects.firstIndex(where: { $0.id == id }) { projects[index] = project }
                } else {
                    project = try await backend.post("/api/projects", json: ["name": editor.name])
                    projects.append(project)
                    projects.sort { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
                }
                projectEditor = nil
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func moveSelected(to projectId: String?) {
        guard let generation = selectedGeneration else { return }
        Task {
            do {
                let value: Any = projectId ?? NSNull()
                let moved: Generation = try await backend.post("/api/generations/\(generation.id)/move", json: ["project_id": value])
                if let index = generations.firstIndex(where: { $0.id == moved.id }) { generations[index] = moved }
                selectedGeneration = moved
                workspace.projectId = projectId
                await refreshProjects()
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func archiveOrRestore(_ project: ProjectInfo) {
        Task {
            do {
                let action = project.archived ? "restore" : "archive"
                let updated: ProjectInfo = try await backend.post("/api/projects/\(project.id)/\(action)")
                if let index = projects.firstIndex(where: { $0.id == updated.id }) { projects[index] = updated }
                await refresh()
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func requestDeleteProject(_ project: ProjectInfo) {
        confirmation = Confirmation(
            title: "Delete Project?",
            message: "The project container will be removed. Its generations and image files will be kept in the main Local Image Studio folder.",
            destructive: true
        ) { [weak self] in self?.deleteProject(project) }
    }

    private func deleteProject(_ project: ProjectInfo) {
        Task {
            do {
                let _: OKResponse = try await backend.delete("/api/projects/\(project.id)")
                projects.removeAll { $0.id == project.id }
                await refresh()
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func revealProject(_ project: ProjectInfo) {
        Task {
            do { let _: OKResponse = try await backend.post("/api/projects/\(project.id)/reveal") }
            catch { errorMessage = error.localizedDescription }
        }
    }

    func revealModel(_ id: String) {
        Task {
            do { let _: OKResponse = try await backend.post("/api/models/\(id)/reveal") }
            catch { errorMessage = error.localizedDescription }
        }
    }

    func openLoRAFolder() {
        Task {
            do { let _: OKResponse = try await backend.post("/api/loras/reveal") }
            catch { errorMessage = error.localizedDescription }
        }
    }

    func installSeedVR2() async {
        do {
            let _: OKResponse = try await backend.post("/api/models/seedvr2_7b/install")
            notice = "SeedVR2 7B installation started in background."
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func refreshProjects() async {
        do {
            let bootstrap: BootstrapResponse = try await backend.get("/api/bootstrap")
            projects = bootstrap.projects
        } catch {}
    }

    func showUpscaleNotice() {
        guard selectedGeneration != nil else { return }
        showUpscaleSheet = true
    }

    func performUpscale(job: UpscaleJob) async {
        guard let sourceGen = selectedGeneration else { return }
        showUpscaleSheet = false
        errorMessage = nil
        notice = "Starting SeedVR2 7B upscale…"

        do {
            var payload: [String: Any] = [
                "source_generation_id": sourceGen.id,
                "scale": job.scale,
                "softness": job.softness,
                "seed": job.seed,
            ]
            if let pid = job.projectId {
                payload["project_id"] = pid
            }

            let jobResp: UpscaleJobResponse = try await backend.post("/api/upscale", json: payload)
            let jobId = jobResp.id

            // Poll for completion
            let deadline = Date().addingTimeInterval(600)  // 10 min
            while Date() < deadline {
                try await Task.sleep(nanoseconds: 500_000_000)  // 0.5s
                if Task.isCancelled { return }
                do {
                    let jobStatus: UpscaleJobStatus = try await backend.get("/api/jobs/\(jobId)")
                    let state = jobStatus.state
                    if state == "complete" {
                        notice = "Upscale complete!"
                        await refresh()
                        return
                    } else if state == "error" {
                        errorMessage = jobStatus.message ?? "Upscale failed"
                        return
                    }
                } catch {
                    errorMessage = error.localizedDescription
                    return
                }
            }
            errorMessage = "Upscale timed out (10 minutes)."
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func group(for generation: Generation) -> HistorySection {
        let calendar = Calendar.current
        if calendar.isDateInToday(generation.date) { return .today }
        if calendar.isDateInYesterday(generation.date) { return .yesterday }
        let days = calendar.dateComponents([.day], from: calendar.startOfDay(for: generation.date), to: calendar.startOfDay(for: Date())).day ?? 999
        return days <= 7 ? .previous7Days : .older
    }

    func treeDepth(for generation: Generation) -> Int {
        var depth = 0
        var parent = generation.parentId
        var seen = Set<String>()
        while let id = parent, !seen.contains(id), depth < 4 {
            seen.insert(id)
            depth += 1
            parent = generations.first(where: { $0.id == id })?.parentId
        }
        return depth
    }

    func generations(in section: HistorySection) -> [Generation] {
        generations.filter { group(for: $0) == section }
    }
}
