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
    @Published private(set) var selectedProjectId: String? {
        didSet { defaults.set(selectedProjectId ?? "", forKey: "selectedProjectID") }
    }
    @Published var workspace = WorkspaceState()
    @Published var showInspector = true
    @Published var lastHelperMetrics: PromptHelperMetrics? {
        didSet {
            defaults.set(lastHelperMetrics.flatMap { try? JSONEncoder().encode($0) }, forKey: "lastEnhanceMetrics")
        }
    }
    @Published private(set) var preEnhancementPrompt: String?
    @Published private(set) var isEnhanced = false
    @Published private(set) var isEnhancing = false
    @Published private(set) var promptFocusRequest = 0
    @Published var selectedImageModel: String {
        didSet { defaults.set(selectedImageModel, forKey: "generationModelID") }
    }
    @Published var helperModelID: String {
        didSet { defaults.set(helperModelID, forKey: "promptHelperModelID") }
    }
    var generationModels: [ModelInfo] { models.filter(\.supportsGeneration) }
    var helperUnavailable: Bool { helperModelID != "off" && !promptHelper.models.contains(helperModelID) }

    func chooseImageModel(_ id: String) {
        guard generationModels.contains(where: { $0.id == id }) else { return }
        let previousModel = workspace.modelId
        selectedImageModel = id
        workspace.modelId = id
        applyImageModelDefaults(for: id, replacingDefaultsFor: previousModel)
    }

    func chooseHelper(_ id: String) {
        helperModelID = id
        promptImprovement = id != "off"
        promptImprovementNotice = nil
    }

    private func restoreModelPreferences() {
        if helperModelID.isEmpty, let preferred = promptHelper.model {
            helperModelID = promptImprovement ? preferred : "off"
        }
        workspace.modelId = selectedImageModel
        applyImageModelDefaults(for: selectedImageModel, replacingDefaultsFor: nil)
    }

    private func applyImageModelDefaults(for modelId: String, replacingDefaultsFor previousModel: String?) {
        if modelId == "krea2_turbo" {
            workspace.steps = 8
            workspace.quantization = 8
        } else if previousModel == "krea2_turbo" {
            workspace.steps = 4
            workspace.quantization = nil
        }
    }
    @Published var activeJob: GenerationJob?
    @Published var modelStatus = ModelRuntimeStatus.unloaded
    @Published var promptHelper = PromptHelperAvailability(available: false, model: nil, notice: nil)
    @Published var isLoading = true
    @Published var errorMessage: String?
    @Published var notice: String?
    @Published var promptImprovementNotice: String?
    @Published var showModels = false
    @Published var showUpscaleSheet = false
    @Published var showAdvanced = false
    @Published var projectsExpanded = true
    @Published var historyExpanded = true
    @Published var projectEditor: ProjectEditor?
    @Published var confirmation: Confirmation?

    var promptImprovement: Bool {
        get { defaults.object(forKey: "promptImprovement") as? Bool ?? true }
        set { defaults.set(newValue, forKey: "promptImprovement"); objectWillChange.send() }
    }
    var promptStrength: String {
        get { defaults.string(forKey: "promptStrength") ?? "normal" }
        set { defaults.set(newValue, forKey: "promptStrength"); objectWillChange.send() }
    }
    var modelRetention: String {
        get { defaults.string(forKey: "modelRetention") ?? "automatic" }
        set { defaults.set(newValue, forKey: "modelRetention"); objectWillChange.send() }
    }

    let backend = BackendController.shared
    private var pollTask: Task<Void, Never>?
    private var selectionRevision = 0
    private var preparingGeneration = false

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

    private let defaults: UserDefaults
    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        selectedImageModel = defaults.string(forKey: "generationModelID") ?? "flux2_klein_4b"
        helperModelID = defaults.string(forKey: "promptHelperModelID") ?? ""
        selectedProjectId = defaults.string(forKey: "selectedProjectID").flatMap { $0.isEmpty ? nil : $0 }
        lastHelperMetrics = defaults.data(forKey: "lastEnhanceMetrics").flatMap { try? JSONDecoder().decode(PromptHelperMetrics.self, from: $0) }
        workspace.modelId = selectedImageModel
        if selectedImageModel == "krea2_turbo" {
            workspace.steps = 8
            workspace.quantization = 8
        }
        workspace.projectId = selectedProjectId
    }

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
            restoreModelPreferences()
            restoreProjectSelection()
            if let active = bootstrap.activeJob {
                activeJob = active
                poll(jobId: active.id)
            }
            workspace.modelId = selectedImageModel
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
            reconcileProjectSelection()
        } catch { errorMessage = error.localizedDescription }
    }

    func newImage() {
        selectionRevision += 1
        clearEnhancement()
        promptFocusRequest += 1
        promptImprovementNotice = nil
        let carried = workspace
        selectedGeneration = nil
        workspace = WorkspaceState(
            mode: .newImage,
            originalPrompt: "",
            modelId: selectedImageModel,
            width: carried.width,
            height: carried.height,
            steps: carried.steps,
            quantization: carried.quantization,
            // A fresh canvas should produce a fresh composition by default.
            // Regenerate and an explicitly disabled Random seed toggle remain
            // the paths for deterministic reuse of an existing seed.
            randomSeed: true,
            seed: carried.seed,
            variantCount: carried.variantCount,
            parentId: nil,
            projectId: selectedProjectId,
            referenceGenerationId: nil,
            referenceData: nil,
            referencePath: nil,
            referenceName: nil,
            loraId: carried.loraId,
            loraScale: carried.loraScale
        )
    }

    func select(_ generation: Generation) {
        selectionRevision += 1
        clearEnhancement()
        promptImprovementNotice = nil
        selectedGeneration = generation
        // All Images intentionally permits a selection from any project.
        if selectedProjectId != nil { selectedProjectId = generation.projectId }
        workspace = WorkspaceState(
            mode: .viewing,
            originalPrompt: generation.originalPrompt,
            modelId: generation.isUpscale ? selectedImageModel : generation.modelId,
            width: generation.width,
            height: generation.height,
            steps: generation.steps,
            quantization: generation.quantization,
            // Selecting an image seeds the next ordinary Generate randomly.
            // Explicit Fork/Regenerate actions below opt back into its exact seed.
            randomSeed: true,
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

    func selectProject(_ id: String?) {
        guard id == nil || projects.contains(where: { $0.id == id }) else {
            recoverMissingProject()
            return
        }
        selectionRevision += 1
        selectedProjectId = id
        if let selected = selectedGeneration,
           let current = generations.first(where: { $0.id == selected.id }),
           id == nil || current.projectId == id {
            select(current)
        } else if let first = generations.first(where: { id == nil || $0.projectId == id }) {
            select(first)
        } else {
            newImage()
        }
    }

    // Generation Settings changes the draft destination through the same active
    // project state. Preserve the user's prompt, but discard the old image source.
    func chooseDraftProject(_ id: String?) {
        guard id == nil || projects.contains(where: { $0.id == id && !$0.archived }) else {
            recoverMissingProject()
            return
        }
        let prompt = workspace.originalPrompt
        selectedProjectId = id
        newImage()
        workspace.originalPrompt = prompt
    }

    func restoreProjectSelection() { selectProject(selectedProjectId) }

    func newImage(in project: ProjectInfo) {
        guard let current = projects.first(where: { $0.id == project.id }), !current.archived else { return }
        selectedProjectId = current.id
        newImage()
    }

    private func clearEnhancement() {
        preEnhancementPrompt = nil
        isEnhanced = false
        promptImprovementNotice = nil
    }

    func enhancePrompt() async {
        guard activeJob == nil, !preparingGeneration, !isEnhancing, helperModelID != "off", !helperModelID.isEmpty else { return }
        let original = workspace.originalPrompt
        guard !original.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        let revision = selectionRevision
        isEnhancing = true
        promptImprovementNotice = nil
        defer { isEnhancing = false }
        do {
            let response: PromptEnhancementResponse = try await backend.post("/api/prompt/enhance", json: [
                "prompt": original, "model_id": helperModelID, "strength": promptStrength
            ])
            lastHelperMetrics = response.promptHelper.hasDisplayMetrics ? response.promptHelper : nil
            guard revision == selectionRevision else { return }
            guard workspace.originalPrompt == original else {
                promptImprovementNotice = "Your prompt changed while enhancing. It was kept; click Enhance to try again."
                return
            }
            applyEnhancement(response, original: original)
        } catch {
            lastHelperMetrics = nil
            guard revision == selectionRevision else { return }
            promptImprovementNotice = "Enhancement failed: \(error.localizedDescription) Your prompt was kept; you can retry or Generate."
        }
    }

    func applyEnhancement(_ response: PromptEnhancementResponse, original: String) {
        guard response.enhanced else {
            promptImprovementNotice = response.notice ?? "Enhancement unavailable. Your prompt was kept; you can retry or Generate."
            return
        }
        preEnhancementPrompt = original
        workspace.originalPrompt = response.prompt
        isEnhanced = true
        promptImprovementNotice = nil
        promptFocusRequest += 1
    }

    func revertPrompt() {
        guard let original = preEnhancementPrompt else { return }
        workspace.originalPrompt = original
        clearEnhancement()
        promptFocusRequest += 1
    }

    private func recoverMissingProject() {
        let prompt = workspace.originalPrompt
        selectedProjectId = nil
        newImage()
        workspace.originalPrompt = prompt
        notice = "The selected project is no longer available. Your prompt was kept. Choose a project before generating again."
    }

    // Called after library reloads, moves, deletion and request preflight. Never
    // leave an old generation or deleted destination in an active project.
    func reconcileProjectSelection() {
        if let id = selectedProjectId, !projects.contains(where: { $0.id == id }) {
            recoverMissingProject()
            return
        }
        if let selected = selectedGeneration {
            if let current = generations.first(where: { $0.id == selected.id }),
               selectedProjectId == nil || current.projectId == selectedProjectId {
                selectedGeneration = current
                workspace.projectId = current.projectId
            } else {
                let prompt = workspace.originalPrompt
                newImage()
                workspace.originalPrompt = prompt
            }
        }
        if let id = workspace.projectId, !projects.contains(where: { $0.id == id }) {
            recoverMissingProject()
        } else if let id = selectedProjectId, workspace.projectId != id {
            chooseDraftProject(id)
        }
    }

    // Returns false on disappearance/archival; never silently retarget this click
    // to All Images. The backend still validates races after this fresh snapshot.
    func validateGenerationDestination(projects currentProjects: [ProjectInfo], generations currentGenerations: [Generation]) -> Bool {
        let target = selectedProjectId ?? workspace.projectId
        projects = currentProjects
        generations = currentGenerations
        if let target, !projects.contains(where: { $0.id == target }) {
            recoverMissingProject()
            return false
        }
        reconcileProjectSelection()
        if let target, projects.first(where: { $0.id == target })?.archived == true {
            notice = "Restore the selected project before generating into it. Your prompt was kept."
            return false
        }
        return true
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
        showInspector = true
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
        workspace.randomSeed = true
        showInspector = true
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
        Task { await generate() }
    }

    func generate() async {
        guard activeJob == nil, !preparingGeneration, !isEnhancing else { return }
        let prompt = workspace.originalPrompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty else { errorMessage = workspace.mode == .edit ? "Describe what should change." : "Enter a prompt before generating."; return }
        preparingGeneration = true
        defer { preparingGeneration = false }
        let revision = selectionRevision
        do {
            let snapshot: BootstrapResponse = try await backend.get("/api/bootstrap")
            guard revision == selectionRevision else { return }
            guard validateGenerationDestination(projects: snapshot.projects, generations: snapshot.generations) else { return }
            promptImprovementNotice = nil
            let job: GenerationJob = try await backend.post("/api/generate", json: generationPayload())
            activeJob = job
            poll(jobId: job.id, followSelection: selectionRevision == revision)
        } catch {
            if error.localizedDescription == "Project not found." {
                // A project can disappear between preflight and submission.
                await refresh()
                notice = "The destination project disappeared before generation could start. Your prompt was kept; choose a project and try again."
            } else { errorMessage = error.localizedDescription }
        }
    }

    func generationPayload() -> [String: Any] {
        let prompt = workspace.originalPrompt
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
            "prompt_is_final": true,
            "prompt_improvement": false,
            "prompt_helper_model": helperModelID.isEmpty ? "off" : helperModelID,
            "prompt_improvement_strength": promptStrength,
            "model_retention": modelRetention,
            "lora_scale": workspace.loraScale,
        ]
        if let parentId = workspace.parentId { payload["parent_id"] = parentId }
        if let projectId = selectedProjectId ?? workspace.projectId { payload["project_id"] = projectId }
        if let reference = workspace.referenceGenerationId { payload["reference_generation_id"] = reference }
        if let data = workspace.referenceData { payload["reference_data"] = data }
        if let path = workspace.referencePath { payload["reference_path"] = path }
        if let lora = workspace.loraId { payload["lora_id"] = lora }
        return payload
    }

    private func poll(jobId: String, followSelection: Bool = true) {
        pollTask?.cancel()
        let revision = selectionRevision
        pollTask = Task {
            while !Task.isCancelled {
                do {
                    try await Task.sleep(nanoseconds: 700_000_000)
                    let job: GenerationJob = try await backend.get("/api/jobs/\(jobId)")
                    activeJob = job
                    if let status = job.modelStatus { modelStatus = status }
                    let followsWorkspace = followSelection && revision == selectionRevision
                    if followsWorkspace {
                        if let original = job.originalPrompt { workspace.originalPrompt = original }
                    }
                    promptImprovementNotice = job.promptNotice
                    if job.state == "complete" {
                        let results = job.generations ?? job.generation.map { [$0] } ?? []
                        generations.insert(contentsOf: results.reversed(), at: 0)
                        if followsWorkspace, let first = results.first { select(first) }
                        // Keep the fallback status visible after selecting the result.
                        promptImprovementNotice = job.promptNotice
                        activeJob = nil
                        await refreshProjects()
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

    func requestDeleteGeneration(_ target: Generation? = nil) {
        guard activeJob == nil, let generation = target ?? selectedGeneration else { return }
        confirmation = Confirmation(
            title: "Delete Image?",
            message: "Delete “\(generation.originalPrompt.prefix(100))”? This removes its image file and metadata. Child images remain and are reattached to its parent.",
            destructive: true
        ) { [weak self] in self?.deleteGeneration(generation) }
    }

    private func deleteGeneration(_ generation: Generation) {
        Task {
            do {
                let _: OKResponse = try await backend.delete("/api/generations/\(generation.id)")
                generations.removeAll { $0.id == generation.id }
                if selectedGeneration?.id == generation.id || workspace.parentId == generation.id || workspace.referenceGenerationId == generation.id {
                    newImage()
                }
                // Reload the backend's reattached lineage and project counts.
                await refresh()
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
                    activateCreatedProject(project)
                }
                projectEditor = nil
            } catch { errorMessage = error.localizedDescription }
        }
    }

    func activateCreatedProject(_ project: ProjectInfo) {
        projects.removeAll { $0.id == project.id }
        projects.append(project)
        projects.sort { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        // Only invoked with the successfully persisted backend response.
        selectProject(project.id)
    }

    func moveSelected(to projectId: String?) {
        guard let generation = selectedGeneration else { return }
        Task {
            do {
                let value: Any = projectId ?? NSNull()
                let moved: Generation = try await backend.post("/api/generations/\(generation.id)/move", json: ["project_id": value])
                if let index = generations.firstIndex(where: { $0.id == moved.id }) { generations[index] = moved }
                selectedProjectId = projectId
                select(moved)
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
        guard activeJob == nil, let project = projects.first(where: { $0.id == project.id }) else { return }
        confirmation = Confirmation(
            title: "Delete “\(project.name)”?",
            message: "This removes the project container. Its \(project.generationCount) image\(project.generationCount == 1 ? "" : "s") will be kept in All Images and the main Local Image Studio folder.",
            destructive: true
        ) { [weak self] in self?.deleteProject(project) }
    }

    private func deleteProject(_ project: ProjectInfo) {
        Task {
            do {
                let _: OKResponse = try await backend.delete("/api/projects/\(project.id)")
                projects.removeAll { $0.id == project.id }
                if selectedProjectId == project.id || selectedGeneration?.projectId == project.id || workspace.projectId == project.id {
                    selectedProjectId = nil
                    newImage()
                }
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
            generations = bootstrap.generations
            reconcileProjectSelection()
        } catch {}
    }

    func showUpscaleNotice() {
        guard selectedGeneration != nil else { return }
        showUpscaleSheet = true
    }

    func performUpscale(job: UpscaleJob) async {
        guard activeJob == nil else { return }
        showUpscaleSheet = false
        errorMessage = nil
        do {
            // The same job observer drives generation and upscale presentation.
            // SeedVR2's backend, lineage, metadata and cleanup remain unchanged.
            let response: GenerationJob = try await backend.post("/api/upscale", json: job.requestPayload)
            activeJob = response
            poll(jobId: response.id)
        } catch { errorMessage = error.localizedDescription }
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

    var visibleHistory: [Generation] {
        let items = generations.filter { selectedProjectId == nil || $0.projectId == selectedProjectId }
        let ids = Set(items.map(\.id))
        var result: [Generation] = []
        var seen = Set<String>()
        func append(_ item: Generation) {
            guard seen.insert(item.id).inserted else { return }
            result.append(item)
            for child in items.reversed() where child.parentId == item.id { append(child) }
        }
        for item in items where item.parentId == nil || !ids.contains(item.parentId!) { append(item) }
        for item in items { append(item) }
        return result
    }

    func generations(in section: HistorySection) -> [Generation] {
        generations.filter { group(for: $0) == section }
    }
}
