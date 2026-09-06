import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject private var store: StudioStore
    @State private var columnVisibility: NavigationSplitViewVisibility = .all

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            SidebarView()
                .navigationSplitViewColumnWidth(min: 210, ideal: 250, max: 330)
        } detail: {
            WorkspaceView()
        }
        .frame(minWidth: 940, minHeight: 680)
        .onReceive(NotificationCenter.default.publisher(for: .toggleStudioSidebar)) { _ in
            withAnimation { columnVisibility = columnVisibility == .detailOnly ? .all : .detailOnly }
        }
        .sheet(isPresented: $store.showModels) { ModelsSheet() }
        .sheet(isPresented: $store.showUpscaleSheet) {
            if let gen = store.selectedGeneration {
                UpscaleSheet(sourceGeneration: gen)
            }
        }
        .sheet(item: $store.projectEditor) { editor in ProjectEditorSheet(editor: editor) }
        .alert("Local Image Studio", isPresented: Binding(
            get: { store.errorMessage != nil },
            set: { if !$0 { store.errorMessage = nil } }
        )) { Button("OK") { store.errorMessage = nil } } message: { Text(store.errorMessage ?? "") }
        .alert("Local Image Studio", isPresented: Binding(
            get: { store.notice != nil },
            set: { if !$0 { store.notice = nil } }
        )) { Button("OK") { store.notice = nil } } message: { Text(store.notice ?? "") }
        .alert(item: $store.confirmation) { confirmation in
            Alert(
                title: Text(confirmation.title),
                message: Text(confirmation.message),
                primaryButton: confirmation.destructive ? .destructive(Text("Delete"), action: confirmation.action) : .default(Text("Continue"), action: confirmation.action),
                secondaryButton: .cancel()
            )
        }
    }
}

struct ModelStatusLabel: View {
    let status: ModelRuntimeStatus
    let job: GenerationJob?

    var body: some View {
        HStack(spacing: 6) {
            if status.status == "loading" || job?.phase == "loading" {
                ProgressView().controlSize(.small)
            } else {
                Circle()
                    .fill(status.status == "loaded" ? Color.green : Color.secondary.opacity(0.5))
                    .frame(width: 7, height: 7)
            }
            Text(label).font(.caption).foregroundStyle(.secondary)
        }
        .help(status.activeMemoryBytes.map { "Resident memory: \(formatBytes($0))" } ?? "No image model resident")
    }

    private var label: String {
        if job?.phase == "loading" {
            return job?.message ?? "Loading…"
        }
        guard status.status == "loaded", let id = status.modelId else { return "Unloaded" }
        if id == "seedvr2_7b" {
            return "SeedVR2 Loaded"
        }
        return id.contains("9b") ? "9B Loaded" : "4B Loaded"
    }
}

struct SidebarView: View {
    @EnvironmentObject private var store: StudioStore

    var body: some View {
        VStack(spacing: 0) {
            Button {
                store.newImage()
            } label: {
                Label("New Image", systemImage: "plus")
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .padding(12)
            .keyboardShortcut("n", modifiers: .command)

            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    DisclosureGroup(isExpanded: $store.projectsExpanded) {
                        VStack(spacing: 2) {
                            ForEach(store.projects) { project in ProjectRow(project: project) }
                            Button { store.createProject() } label: {
                                Label("New Project", systemImage: "plus.circle")
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .buttonStyle(.plain)
                            .foregroundStyle(.secondary)
                            .padding(.vertical, 6)
                        }
                        .padding(.top, 6)
                    } label: {
                        SidebarSectionLabel(title: "Projects", count: store.projects.count)
                    }

                    DisclosureGroup(isExpanded: $store.historyExpanded) {
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(HistorySection.allCases) { section in
                                let items = store.generations(in: section)
                                if !items.isEmpty {
                                    VStack(alignment: .leading, spacing: 3) {
                                        Text(section.rawValue)
                                            .font(.caption2.weight(.semibold))
                                            .foregroundStyle(.tertiary)
                                            .textCase(.uppercase)
                                            .padding(.leading, 4)
                                        ForEach(items) { generation in HistoryRow(generation: generation) }
                                    }
                                }
                            }
                            if store.generations.isEmpty {
                                Text("Generated images will appear here.")
                                    .font(.caption)
                                    .foregroundStyle(.tertiary)
                                    .padding(.vertical, 20)
                            }
                        }
                        .padding(.top, 8)
                    } label: {
                        SidebarSectionLabel(title: "History", count: store.generations.count)
                    }
                }
                .padding(12)
            }
        }
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.45))
    }
}

struct SidebarSectionLabel: View {
    let title: String
    let count: Int
    var body: some View {
        HStack {
            Text(title).font(.caption.weight(.semibold)).textCase(.uppercase)
            Spacer()
            Text("\(count)").font(.caption2).foregroundStyle(.tertiary)
        }
    }
}

struct ProjectRow: View {
    @EnvironmentObject private var store: StudioStore
    let project: ProjectInfo

    var body: some View {
        Button {
            store.selectedProjectId = project.id
            if let first = store.generations.first(where: { $0.projectId == project.id }) { store.select(first) }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: project.archived ? "archivebox" : "folder")
                    .foregroundStyle(project.archived ? .secondary : Color.accentColor)
                Text(project.name).lineLimit(1)
                Spacer()
                Text("\(project.generationCount)").font(.caption2).foregroundStyle(.tertiary)
            }
            .padding(.vertical, 5)
            .padding(.horizontal, 6)
            .background(store.selectedProjectId == project.id ? Color.accentColor.opacity(0.12) : .clear, in: RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button("Rename…") { store.editProject(project) }.disabled(project.archived)
            Button(project.archived ? "Restore Project" : "Archive Project") { store.archiveOrRestore(project) }
            Button("Reveal in Finder") { store.revealProject(project) }
            Divider()
            Button("Delete Project…", role: .destructive) { store.requestDeleteProject(project) }
        }
    }
}

struct HistoryRow: View {
    @EnvironmentObject private var store: StudioStore
    let generation: Generation

    var body: some View {
        Button { store.select(generation) } label: {
            HStack(spacing: 8) {
                if store.treeDepth(for: generation) > 0 {
                    Image(systemName: "arrow.turn.down.right")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                Thumbnail(path: generation.thumbnailPath ?? generation.imagePath)
                    .frame(width: 42, height: 42)
                VStack(alignment: .leading, spacing: 3) {
                    Text(generation.originalPrompt)
                        .font(.caption)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                    HStack(spacing: 4) {
                        if generation.variantCount > 1 { Text("\(generation.variantIndex)/\(generation.variantCount)") }
                        Text(generation.modelId.contains("9b") ? "9B" : "4B")
                        Text("·")
                        Text(generation.date, style: .time)
                        if generation.archived { Image(systemName: "archivebox") }
                    }
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                }
                Spacer(minLength: 0)
            }
            .padding(5)
            .padding(.leading, CGFloat(store.treeDepth(for: generation)) * 7)
            .background(store.selectedGeneration?.id == generation.id ? Color.accentColor.opacity(0.13) : .clear, in: RoundedRectangle(cornerRadius: 7))
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button("Open") { store.select(generation) }
            Button("Fork") { store.select(generation); store.forkSelected() }
            Button("Edit") { store.select(generation); store.editSelected() }
            Menu("Move to Project") {
                Button("No Project") { store.select(generation); store.moveSelected(to: nil) }
                Divider()
                ForEach(store.projects.filter { !$0.archived }) { project in
                    Button(project.name) { store.select(generation); store.moveSelected(to: project.id) }
                }
            }
            Button("Reveal in Finder") { store.select(generation); store.revealImage() }
            Divider()
            Button("Delete…", role: .destructive) { store.select(generation); store.requestDeleteGeneration() }
        }
    }
}

struct Thumbnail: View {
    let path: String
    var body: some View {
        Group {
            if let image = NSImage(contentsOfFile: path) {
                Image(nsImage: image).resizable().scaledToFill()
            } else {
                ZStack { Color.secondary.opacity(0.12); Image(systemName: "photo").foregroundStyle(.tertiary) }
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}

struct WorkspaceView: View {
    @EnvironmentObject private var store: StudioStore

    var body: some View {
        VStack(spacing: 0) {
            PerformanceBar()
            Divider()
            CanvasView()
            if store.selectedGeneration != nil { ActionBar() }
            ComposerView()
        }
        .background(Color(nsColor: .windowBackgroundColor))
    }
}

struct PerformanceBar: View {
    @EnvironmentObject private var store: StudioStore

    var body: some View {
        HStack(spacing: 5) {
            if let job = store.activeJob {
                ProgressView().controlSize(.small)
                Text(liveText(job))
            } else if let generation = store.selectedGeneration {
                Text(generation.model)
                dot
                Text(generation.quantizationLabel == "None" ? "No quantization" : generation.quantizationLabel)
                dot
                Text("\(generation.width)×\(generation.height)")
                dot
                Text("\(generation.steps) steps")
                dot
                Text(String(format: "%.1f sec", generation.generationTime))
                dot
                Text(String(format: "%.2f steps/sec", generation.stepsPerSecond))
                if let memory = generation.peakMemoryBytes { dot; Text("\(formatBytes(memory)) peak") }
            } else {
                Text("Ready to generate")
            }
            Spacer()
            if let helper = store.selectedGeneration?.promptHelper, let model = helper.model {
                Text(promptHelperText(helper, model: model)).help("Prompt-helper language metrics are separate from diffusion speed.")
            }
        }
        .font(.caption2)
        .foregroundStyle(.secondary)
        .padding(.horizontal, 14)
        .frame(height: 32)
    }

    private var dot: some View { Text("·").foregroundStyle(.tertiary) }

    private func liveText(_ job: GenerationJob) -> String {
        var parts = [job.message]
        if let elapsed = job.elapsed { parts.append(String(format: "%.1f sec", elapsed)) }
        if let memory = job.peakMemoryBytes { parts.append(formatBytes(memory)) }
        return parts.joined(separator: " · ")
    }

    private func promptHelperText(_ helper: PromptHelperMetrics, model: String) -> String {
        var parts = ["Prompt Helper", model]
        if let rate = helper.tokensPerSecond { parts.append(String(format: "%.0f tok/s", rate)) }
        if let ttft = helper.timeToFirstToken { parts.append(String(format: "TTFT %.1f sec", ttft)) }
        if let count = helper.tokenCount { parts.append("\(count) tokens") }
        if let total = helper.totalTime { parts.append(String(format: "%.1f sec", total)) }
        return parts.joined(separator: " · ")
    }
}

struct CanvasView: View {
    @EnvironmentObject private var store: StudioStore
    @State private var zoom: CGFloat = 1
    @State private var actualSize = false
    @State private var isDropTarget = false

    var body: some View {
        ZStack {
            Color(nsColor: .underPageBackgroundColor).opacity(0.35)
            if let generation = store.selectedGeneration {
                if generation.archived {
                    VStack(spacing: 12) {
                        Image(systemName: "archivebox").font(.system(size: 42)).foregroundStyle(.secondary)
                        Text("This image is in an archived project").font(.headline)
                        Text("Restore its project to open the full-resolution image.").foregroundStyle(.secondary)
                    }
                } else if let image = NSImage(contentsOfFile: generation.imagePath) {
                    ScrollView([.horizontal, .vertical]) {
                        GeometryReader { geometry in
                            Image(nsImage: image)
                                .resizable()
                                .aspectRatio(contentMode: .fit)
                                .frame(
                                    width: actualSize ? image.size.width : max(100, geometry.size.width - 40),
                                    height: actualSize ? image.size.height : max(100, geometry.size.height - 40)
                                )
                                .scaleEffect(zoom)
                                .frame(maxWidth: .infinity, maxHeight: .infinity)
                                .padding(20)
                        }
                        .frame(minWidth: 400, minHeight: 320)
                    }
                    .gesture(MagnificationGesture().onChanged { zoom = max(0.2, min(5, $0)) })
                    .overlay(alignment: .bottomTrailing) {
                        HStack(spacing: 4) {
                            Button { actualSize = false; zoom = 1 } label: { Image(systemName: "arrow.down.right.and.arrow.up.left") }.help("Fit to window")
                            Button { actualSize = true; zoom = 1 } label: { Text("100%") }.help("Actual size")
                            Button { zoom = max(0.2, zoom - 0.25) } label: { Image(systemName: "minus.magnifyingglass") }
                            Button { zoom = min(5, zoom + 0.25) } label: { Image(systemName: "plus.magnifyingglass") }
                        }
                        .buttonStyle(.bordered)
                        .padding(12)
                    }
                }
            } else {
                EmptyCanvas(isDropTarget: isDropTarget)
            }
            if let job = store.activeJob {
                ZStack {
                    Rectangle().fill(.ultraThinMaterial)
                    VStack(spacing: 14) {
                        ProgressView().controlSize(.large)
                        Text(job.message).font(.headline)
                        if let elapsed = job.elapsed { Text(String(format: "%.1f seconds", elapsed)).font(.caption).foregroundStyle(.secondary) }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onDrop(of: [UTType.fileURL.identifier], isTargeted: $isDropTarget) { providers in
            guard store.selectedGeneration == nil, let provider = providers.first else { return false }
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
                let url: URL?
                if let data = item as? Data { url = URL(dataRepresentation: data, relativeTo: nil) }
                else { url = item as? URL }
                if let url { DispatchQueue.main.async { store.attachReference(url) } }
            }
            return true
        }
    }
}

struct EmptyCanvas: View {
    let isDropTarget: Bool
    var body: some View {
        VStack(spacing: 13) {
            Image(systemName: "photo.on.rectangle.angled")
                .font(.system(size: 48, weight: .light))
                .foregroundStyle(isDropTarget ? Color.accentColor : .secondary)
            Text("New Image").font(.title3.weight(.semibold))
            Text("Describe an image below, or drop a reference image here.")
                .font(.callout).foregroundStyle(.secondary)
        }
        .padding(50)
        .background(isDropTarget ? Color.accentColor.opacity(0.08) : .clear, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(isDropTarget ? Color.accentColor : Color.clear, style: StrokeStyle(lineWidth: 1.5, dash: [6])))
    }
}

struct ActionBar: View {
    @EnvironmentObject private var store: StudioStore
    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 5) {
                Button("Edit", systemImage: "pencil") { store.editSelected() }
                Button("Fork", systemImage: "arrow.triangle.branch") { store.forkSelected() }
                Button("Regenerate", systemImage: "arrow.clockwise") { store.regenerateSelected() }
                Button("Variation", systemImage: "dice") { store.variationSelected() }
                Button("Upscale", systemImage: "arrow.up.left.and.arrow.down.right") { store.showUpscaleNotice() }
                Divider().frame(height: 18)
                Button("Save", systemImage: "square.and.arrow.down") { store.exportImage() }
                Button("Copy", systemImage: "doc.on.doc") { store.copyImage() }
                Button("Export", systemImage: "square.and.arrow.up") { store.exportImage() }
                Button("Reveal", systemImage: "folder") { store.revealImage() }
                Menu("Move", systemImage: "folder.badge.plus") {
                    Button("No Project") { store.moveSelected(to: nil) }
                    Divider()
                    ForEach(store.projects.filter { !$0.archived }) { project in Button(project.name) { store.moveSelected(to: project.id) } }
                }
                Divider().frame(height: 18)
                Button("Delete", systemImage: "trash", role: .destructive) { store.requestDeleteGeneration() }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
        }
        .background(.bar)
    }
}

struct ComposerView: View {
    @EnvironmentObject private var store: StudioStore
    @FocusState private var promptFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            Divider()
            VStack(spacing: 10) {
                if let referenceName = store.workspace.referenceName {
                    HStack {
                        Label(referenceName, systemImage: "paperclip")
                            .font(.caption).lineLimit(1)
                        Spacer()
                        Button { store.clearReference() } label: { Image(systemName: "xmark.circle.fill") }
                            .buttonStyle(.plain).foregroundStyle(.secondary)
                    }
                    .padding(8)
                    .background(Color.accentColor.opacity(0.08), in: RoundedRectangle(cornerRadius: 7))
                }

                HStack(alignment: .bottom, spacing: 9) {
                    Button { store.chooseReferenceImage() } label: { Image(systemName: "paperclip") }
                        .buttonStyle(.bordered).help("Attach reference image")
                    TextField(store.workspace.mode == .edit ? "What should change?" : "Describe the image you want to create…", text: $store.workspace.originalPrompt, axis: .vertical)
                        .textFieldStyle(.plain)
                        .lineLimit(2...6)
                        .focused($promptFocused)
                        .padding(.vertical, 7)
                    Button {
                        Task { await store.generate() }
                    } label: {
                        Label("Generate", systemImage: "sparkles")
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(store.activeJob != nil)
                    .keyboardShortcut("g", modifiers: .command)
                }

                HStack(spacing: 12) {
                    Toggle("Prompt Improvement", isOn: Binding(get: { store.promptImprovement }, set: { store.promptImprovement = $0 }))
                        .toggleStyle(.switch).controlSize(.small)
                    Picker("Strength", selection: Binding(get: { store.promptStrength }, set: { store.promptStrength = $0 })) {
                        Text("Light").tag("light"); Text("Normal").tag("normal"); Text("Strong").tag("strong")
                    }
                    .pickerStyle(.menu).frame(width: 130).disabled(!store.promptImprovement)
                    if !store.promptHelper.available && store.promptImprovement {
                        Label("Original prompt will be used", systemImage: "info.circle")
                            .font(.caption2).foregroundStyle(.secondary)
                            .help("Prompt improvement unavailable — original prompt used")
                    }
                    Spacer()
                    Button(store.showAdvanced ? "Hide Advanced" : "Advanced", systemImage: "slider.horizontal.3") { withAnimation { store.showAdvanced.toggle() } }
                        .buttonStyle(.plain).foregroundStyle(.secondary)
                }
                .font(.caption)

                if store.promptImprovement && (!store.workspace.improvedPrompt.isEmpty || store.selectedGeneration != nil) {
                    DisclosureGroup("Show Improved Prompt", isExpanded: $store.showImprovedPrompt) {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Original Prompt").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                            Text(store.workspace.originalPrompt).font(.caption).textSelection(.enabled)
                            Text("Improved Prompt").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                            TextEditor(text: $store.workspace.improvedPrompt)
                                .font(.caption).frame(minHeight: 55, maxHeight: 90)
                                .overlay(RoundedRectangle(cornerRadius: 5).stroke(Color.secondary.opacity(0.2)))
                        }
                        .padding(.top, 6)
                    }
                    .font(.caption)
                }

                if store.showAdvanced { AdvancedSettingsView() }
            }
            .padding(12)
        }
        .background(.bar)
    }
}

struct AdvancedSettingsView: View {
    @EnvironmentObject private var store: StudioStore
    let columns = Array(repeating: GridItem(.flexible(minimum: 110), spacing: 10), count: 4)

    var body: some View {
        LazyVGrid(columns: columns, alignment: .leading, spacing: 10) {
            field("Width") { TextField("Width", value: $store.workspace.width, format: .number).textFieldStyle(.roundedBorder) }
            field("Height") { TextField("Height", value: $store.workspace.height, format: .number).textFieldStyle(.roundedBorder) }
            field("Steps") { Stepper(value: $store.workspace.steps, in: 1...100) { Text("\(store.workspace.steps)") } }
            field("Quantization") {
                Picker("", selection: $store.workspace.quantization) {
                    Text("None").tag(nil as Int?)
                    Text("8-bit").tag(8 as Int?)
                    Text("6-bit").tag(6 as Int?)
                    Text("4-bit").tag(4 as Int?)
                }.labelsHidden()
            }
            field("Aspect Ratio") {
                Picker("", selection: aspectBinding) {
                    Text("1:1").tag("1:1"); Text("4:3").tag("4:3"); Text("3:4").tag("3:4"); Text("16:9").tag("16:9"); Text("9:16").tag("9:16")
                }.labelsHidden()
            }
            field("Random Seed") { Toggle(store.workspace.randomSeed ? "On" : "Off", isOn: $store.workspace.randomSeed).toggleStyle(.switch) }
            field("Seed") { TextField("Seed", value: $store.workspace.seed, format: .number).textFieldStyle(.roundedBorder).disabled(store.workspace.randomSeed) }
            field("Variants") {
                Picker("", selection: $store.workspace.variantCount) { Text("1").tag(1); Text("2").tag(2); Text("4").tag(4) }
                    .pickerStyle(.segmented).labelsHidden()
            }
            field("Reference Image") { Button(store.workspace.referenceName ?? "Choose…") { store.chooseReferenceImage() }.lineLimit(1) }
            field("LoRA") {
                Picker("", selection: $store.workspace.loraId) {
                    Text("None").tag(nil as String?)
                    ForEach(store.loras) { lora in Text(lora.name).tag(lora.id as String?) }
                }.labelsHidden()
            }
            field("LoRA Strength") { TextField("Strength", value: $store.workspace.loraScale, format: .number.precision(.fractionLength(2))).textFieldStyle(.roundedBorder).disabled(store.workspace.loraId == nil) }
            field("Project") {
                Picker("", selection: $store.workspace.projectId) {
                    Text("No Project").tag(nil as String?)
                    ForEach(store.projects.filter { !$0.archived }) { project in Text(project.name).tag(project.id as String?) }
                }.labelsHidden()
            }
        }
        .font(.caption)
        .padding(10)
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.45), in: RoundedRectangle(cornerRadius: 9))
    }

    private func field<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 4) { Text(title).foregroundStyle(.secondary); content() }
    }

    private var aspectBinding: Binding<String> {
        Binding {
            switch (store.workspace.width, store.workspace.height) {
            case (1152, 864): return "4:3"
            case (864, 1152): return "3:4"
            case (1344, 768): return "16:9"
            case (768, 1344): return "9:16"
            default: return "1:1"
            }
        } set: { value in
            switch value {
            case "4:3": store.workspace.width = 1152; store.workspace.height = 864
            case "3:4": store.workspace.width = 864; store.workspace.height = 1152
            case "16:9": store.workspace.width = 1344; store.workspace.height = 768
            case "9:16": store.workspace.width = 768; store.workspace.height = 1344
            default: store.workspace.width = 1024; store.workspace.height = 1024
            }
        }
    }
}

struct ModelsSheet: View {
    @EnvironmentObject private var store: StudioStore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack { Text("Models").font(.title2.weight(.semibold)); Spacer(); Button("Done") { dismiss() }.keyboardShortcut(.defaultAction) }
                .padding()
            Divider()
            List {
                ForEach(store.models) { model in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Image(systemName: model.id.hasPrefix("seed") ? "arrow.up.left.and.arrow.down.right" : "square.stack.3d.up")
                                .font(.title3).foregroundStyle(model.status == "Installed" ? Color.accentColor : .secondary)
                            VStack(alignment: .leading) {
                                Text(model.label).font(.headline)
                                Text(model.status).font(.caption).foregroundStyle(model.status == "Installed" ? Color.green : .secondary)
                            }
                            Spacer()
                            if store.modelStatus.modelId == model.id { Text("Resident").font(.caption).foregroundStyle(.green) }
                            if let size = model.approxSize { Text(size).font(.caption).foregroundStyle(.secondary) }
                        }
                        if model.status == "Installed" {
                            DisclosureGroup("Cache location") { Text(cachePath(for: model.id)).font(.caption.monospaced()).textSelection(.enabled).padding(.top, 4) }
                                .font(.caption).foregroundStyle(.secondary)
                            Button("Reveal in Finder") { store.revealModel(model.id) }.controlSize(.small)
                        } else if model.id.hasPrefix("seed") {
                            Button("Install SeedVR2 7B (~14 GB)") {
                                Task { await store.installSeedVR2() }
                            }.controlSize(.small)
                        }
                    }
                    .padding(.vertical, 7)
                }
            }
            Divider()
            HStack {
                Text("Models use the shared Hugging Face cache. SeedVR2 7B must be installed manually from the Models view.").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("Open LoRA Folder") { store.openLoRAFolder() }
            }
            .padding()
        }
        .frame(width: 600, height: 520)
    }

    private func cachePath(for id: String) -> String {
        if id.hasPrefix("seed") {
            return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".cache/huggingface/hub/models--numz--SeedVR2_comfyUI").path
        }
        let name = id.contains("9b") ? "models--black-forest-labs--FLUX.2-klein-9B" : "models--black-forest-labs--FLUX.2-klein-4B"
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".cache/huggingface/hub/\(name)").path
    }
}

struct ProjectEditorSheet: View {
    @EnvironmentObject private var store: StudioStore
    @Environment(\.dismiss) private var dismiss
    @State var editor: StudioStore.ProjectEditor

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(editor.title).font(.title2.weight(.semibold))
            TextField("Project name", text: $editor.name).textFieldStyle(.roundedBorder)
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Save") { store.saveProjectEditor(editor); dismiss() }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction).disabled(editor.name.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(22)
        .frame(width: 380)
    }
}

struct SettingsView: View {
    @EnvironmentObject private var store: StudioStore
    var body: some View {
        Form {
            Section("Prompt Improvement") {
                Toggle("Improve prompts before image generation", isOn: Binding(get: { store.promptImprovement }, set: { store.promptImprovement = $0 }))
                Picker("Strength", selection: Binding(get: { store.promptStrength }, set: { store.promptStrength = $0 })) {
                    Text("Light").tag("light"); Text("Normal").tag("normal"); Text("Strong").tag("strong")
                }
                Text(store.promptHelper.available ? "Using \(store.promptHelper.model ?? "local helper")" : "Unavailable right now; the original prompt will be used.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Model Retention") {
                Picker("After generation", selection: Binding(get: { store.modelRetention }, set: { store.modelRetention = $0 })) {
                    Text("Automatic — 5 minutes").tag("automatic")
                    Text("Keep Loaded").tag("keep")
                    Text("Unload Immediately").tag("immediate")
                }
                Text("Selecting a model never loads it. Models load only when you generate.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Storage") {
                Text("Originals: lossless PNG")
                Text("Active projects: .lisproject packages")
                Text("Archived projects: lossless WebP inside ZIP")
                Text("Images are moved, never duplicated, when assigned to projects.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding()
        .frame(width: 520, height: 430)
    }
}

// MARK: - Upscale Sheet
struct UpscaleSheet: View {
    @EnvironmentObject private var store: StudioStore
    @Environment(\.dismiss) private var dismiss

    let sourceGeneration: Generation
    @State private var scale: String = "2x"
    @State private var softness: Double = 0.5
    @State private var seed: Int = 42
    @State private var preserveColors: Bool = true
    @State private var showAdvanced: Bool = false
    @State private var isRunning: Bool = false
    @State private var errorMessage: String?
    @State private var progressMessage: String = ""

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text("Upscale with SeedVR2 7B").font(.title2.weight(.semibold))
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
            }
            .padding()

            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    // Source info
                    HStack(spacing: 12) {
                        Thumbnail(path: sourceGeneration.thumbnailPath ?? sourceGeneration.imagePath)
                            .frame(width: 80, height: 80)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(sourceGeneration.filename).font(.headline)
                            Text("\(sourceGeneration.width) × \(sourceGeneration.height)").font(.caption).foregroundStyle(.secondary)
                            Text("Source: \(sourceGeneration.model) · \(formatBytes(sourceGeneration.peakMemoryBytes ?? 0))").font(.caption2).foregroundStyle(.tertiary)
                        }
                    }

                    Divider()

                    // Scale selection
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Scale Factor").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                        Picker("Scale", selection: $scale) {
                            Text("2×").tag("2x")
                            Text("4×").tag("4x")
                        }
                        .pickerStyle(.segmented)
                    }

                    // Output preview
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Output:").font(.caption).foregroundStyle(.secondary)
                        Text("\(sourceGeneration.width * (scale == "4x" ? 4 : 2)) × \(sourceGeneration.height * (scale == "4x" ? 4 : 2))")
                            .font(.caption.monospaced()).foregroundStyle(Color.accentColor)
                    }

                    Divider()

                    // Softness
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("Softness").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                            Spacer()
                            Text(String(format: "%.2f", softness)).font(.caption.monospaced()).foregroundStyle(.secondary)
                        }
                        Slider(value: $softness, in: 0.0...1.0, step: 0.05)
                            .disabled(isRunning)
                        Text("Controls pre-downsampling for smoother results. 0.5 is recommended.").font(.caption2).foregroundStyle(.tertiary)
                    }

                    // Preserve Colors (always ON, informational)
                    HStack {
                        Image(systemName: "paintpalette")
                            .foregroundStyle(.green)
                        Text("Color preservation: Always enabled (SeedVR2 7B native)").font(.caption).foregroundStyle(.secondary)
                    }

                    Divider()

                    // Advanced settings
                    DisclosureGroup(isExpanded: $showAdvanced) {
                        VStack(alignment: .leading, spacing: 12) {
                            // Seed
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Random Seed").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                                HStack {
                                    TextField("Seed", value: $seed, format: .number)
                                        .textFieldStyle(.roundedBorder)
                                        .disabled(isRunning)
                                    Button { seed = Int.random(in: 0..<2_147_483_647) } label: {
                                        Image(systemName: "shuffle")
                                    }
                                    .buttonStyle(.bordered)
                                    .controlSize(.small)
                                    .disabled(isRunning)
                                }
                            }

                            // Memory note
                            Text("Memory: ~18–24 GB peak on M5 Max (FP16 7B). Low-RAM mode is automatic.").font(.caption2).foregroundStyle(.tertiary)
                        }
                    } label: {
                        Text("Advanced Settings").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    }

                    if let error = errorMessage {
                        Text(error).font(.caption).foregroundStyle(.red)
                    }

                    if isRunning {
                        HStack {
                            ProgressView().controlSize(.small)
                            Text(progressMessage).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                .padding()
            }

            Divider()

            // Action buttons
            HStack {
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction).disabled(isRunning)
                Spacer()
                Button {
                    Task { await runUpscale() }
                } label: {
                    Text(isRunning ? "Processing…" : "Upscale")
                        .fontWeight(.semibold)
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(isRunning)
            }
            .padding()
        }
        .frame(width: 520, height: 560)
    }

    private func runUpscale() async {
        isRunning = true
        errorMessage = nil
        progressMessage = "Starting SeedVR2 7B upscale…"

        do {
            var payload: [String: Any] = [
                "source_generation_id": sourceGeneration.id,
                "scale": scale,
                "softness": softness,
                "seed": seed,
            ]
            if let pid = store.selectedProjectId {
                payload["project_id"] = pid
            }

            let jobResp: UpscaleJobResponse = try await store.backend.post("/api/upscale", json: payload)
            let jobId = jobResp.id

            let deadline = Date().addingTimeInterval(600)
            while Date() < deadline {
                try await Task.sleep(nanoseconds: 500_000_000)
                if Task.isCancelled { return }
                do {
                    let jobStatus: UpscaleJobStatus = try await store.backend.get("/api/jobs/\(jobId)")
                    let state = jobStatus.state
                    if let msg = jobStatus.message {
                        progressMessage = msg
                    }
                    if state == "complete" {
                        progressMessage = "Upscale complete!"
                        await store.refresh()
                        dismiss()
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
        isRunning = false
    }
}

func formatBytes(_ bytes: Int64) -> String {
    let formatter = ByteCountFormatter()
    formatter.allowedUnits = [.useMB, .useGB]
    formatter.countStyle = .memory
    return formatter.string(fromByteCount: bytes)
}

extension Notification.Name {
    static let toggleStudioSidebar = Notification.Name("LocalImageStudio.ToggleSidebar")
}
