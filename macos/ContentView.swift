import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject private var store: StudioStore
    @State private var columnVisibility: NavigationSplitViewVisibility = .all

    var body: some View {
        VStack(spacing: 0) {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            SidebarView()
                .navigationSplitViewColumnWidth(min: 210, ideal: 250, max: 330)
        } detail: {
            HSplitView {
                WorkspaceView().frame(minWidth: 350)
                if store.showInspector {
                    InspectorView().frame(minWidth: 260, idealWidth: 280, maxWidth: 340)
                }
            }
        }
        ComposerView()
        }
        .frame(minWidth: 940, minHeight: 680)
        .toolbar {
            ToolbarItem(placement: .navigation) {
                HStack(spacing: 6) {
                    Text("Generate with:").font(.subheadline).foregroundStyle(.secondary)
                    Picker("Next generation model", selection: Binding(get: { store.workspace.modelId }, set: { store.chooseImageModel($0) })) {
                        ForEach(store.generationModels) { Text($0.label).tag($0.id) }
                    }.labelsHidden().frame(maxWidth: 205)
                        .help("Model for the next generation. The selected image’s model is shown in Image Info.")
                        .accessibilityLabel("Next generation model")
                    ModelResidencyButton()
                }
            }
            ToolbarItem(placement: .status) {
                if store.modelStatus.status == "loading" || store.activeJob?.phase == "loading" {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.small)
                        Text(store.activeJob?.message ?? "Loading image model…").font(.caption)
                    }
                } else {
                    // Retain native toolbar spacing when the loading label is absent.
                    Color.clear.frame(width: 1, height: 1).accessibilityHidden(true)
                }
            }
            ToolbarItemGroup(placement: .primaryAction) {
                Button { store.exportImage() } label: { Label("Export", systemImage: "square.and.arrow.up") }
                    .disabled(store.selectedGeneration == nil || store.selectedGeneration?.archived == true).help("Export Image (⌘E)")
                Button { store.showModels = true } label: { Label("Models", systemImage: "square.stack.3d.up") }.help("Manage Models")
                Button { store.showInspector.toggle() } label: { Label("Inspector", systemImage: "sidebar.right") }.help("Toggle Inspector (⌘⌥I)")
            }
        }

        .onReceive(NotificationCenter.default.publisher(for: .toggleStudioSidebar)) { _ in
            columnVisibility = columnVisibility == .detailOnly ? .all : .detailOnly
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

struct ModelResidencyButton: View {
    @EnvironmentObject private var store: StudioStore
    @State private var showingStatus = false
    private var residency: String {
        let status = store.modelStatus
        if status.status == "loading" { return "Loading image model…" }
        if status.status == "loaded", let id = status.modelId, id != "seedvr2_7b" {
            let name = store.models.first(where: { $0.id == id })?.label ?? "Image model"
            return "\(name) is loaded in memory."
        }
        if status.modelId == "seedvr2_7b" {
            return store.activeJob == nil ? "Last job used SeedVR2 for upscaling." : "SeedVR2 upscale is running."
        }
        return "No generation model is loaded in memory."
    }
    var body: some View {
        Button { showingStatus.toggle() } label: { Image(systemName: "info.circle").foregroundStyle(.secondary) }
            .buttonStyle(.plain).help("Image model availability and memory status")
            .accessibilityLabel("Image model status")
            .popover(isPresented: $showingStatus) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Image Models").font(.headline)
                    ForEach(store.generationModels) { model in
                        LabeledContent(model.label, value: model.status)
                    }
                    Divider()
                    Text(residency)
                    if let bytes = store.modelStatus.activeMemoryBytes, bytes > 1024 {
                        Text("Worker active memory: \(formatBytes(bytes))").foregroundStyle(.secondary)
                    }
                    Text("Models load when needed for a job.").foregroundStyle(.secondary)
                }.font(.callout).padding(16).frame(width: 290)
            }
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
            .buttonStyle(.bordered)
            .controlSize(.regular)
            .padding(12)
            .keyboardShortcut("n", modifiers: .command)

            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    DisclosureGroup(isExpanded: $store.projectsExpanded) {
                        VStack(spacing: 2) {
                            Button { store.selectProject(nil) } label: {
                                Label("All Images", systemImage: "photo.on.rectangle")
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }.buttonStyle(.plain).padding(6)
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
                            ForEach(store.visibleHistory) { generation in HistoryRow(generation: generation) }
                            if store.generations.isEmpty {
                                Text("Generated images will appear here.")
                                    .font(.caption)
                                    .foregroundStyle(.tertiary)
                                    .padding(.vertical, 20)
                            }
                        }
                        .padding(.top, 8)
                    } label: {
                        SidebarSectionLabel(title: "History", count: store.visibleHistory.count)
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
    @State private var hovered = false
    private var showsActions: Bool { hovered || store.selectedProjectId == project.id }

    var body: some View {
        HStack(spacing: 6) {
            Button { store.selectProject(project.id) } label: {
                HStack(spacing: 8) {
                    Image(systemName: project.archived ? "archivebox" : "folder")
                        .foregroundStyle(project.archived ? .secondary : Color.accentColor)
                    Text(project.name).lineLimit(1)
                    Spacer(minLength: 0)
                    Text("\(project.generationCount)").font(.caption2).foregroundStyle(.tertiary)
                }.contentShape(Rectangle())
            }.buttonStyle(.plain)
            HStack(spacing: 6) {
                if !project.archived {
                    Button { store.newImage(in: project) } label: { Image(systemName: "photo.badge.plus") }
                        .help("New image in \(project.name)").accessibilityLabel("New image in \(project.name)")
                }
                Button(role: .destructive) { store.requestDeleteProject(project) } label: { Image(systemName: "trash") }
                    .help("Delete project \(project.name)").accessibilityLabel("Delete project \(project.name)")
                    .disabled(store.activeJob != nil)
            }.buttonStyle(.plain).foregroundStyle(.secondary).opacity(showsActions ? 1 : 0)
        }
        .padding(.vertical, 5).padding(.horizontal, 6)
        .background(store.selectedProjectId == project.id ? Color.accentColor.opacity(0.12) : .clear, in: RoundedRectangle(cornerRadius: 6))
        .onHover { hovered = $0 }
        .contextMenu {
            if !project.archived { Button("New Image") { store.newImage(in: project) } }
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
    @State private var hovered = false

    var body: some View {
        HStack(spacing: 3) {
        Button { store.select(generation) } label: {
            HStack(spacing: 8) {
                if store.treeDepth(for: generation) > 0 {
                    Image(systemName: "arrow.turn.down.right")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .help("Derived from a parent image")
                }
                Thumbnail(path: generation.thumbnailPath ?? generation.imagePath)
                    .frame(width: 54, height: 54)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                VStack(alignment: .leading, spacing: 3) {
                    Text(generation.isUpscale ? "Upscale \(generation.upscaleScaleFactor ?? "")" : generation.originalPrompt)
                        .font(.caption)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                    HStack(spacing: 4) {
                        if generation.variantCount > 1 { Text("\(generation.variantIndex)/\(generation.variantCount)") }
                        Text(generation.isUpscale ? "SeedVR2" : generation.parentId == nil ? "Original" : generation.referenceUsed ? "Edit" : "Variation / Fork")
                        Text("·")
                        Text(generation.date, style: .time)
                        if generation.archived { Image(systemName: "archivebox") }
                    }
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
            }
            .padding(5)
            .padding(.leading, CGFloat(store.treeDepth(for: generation)) * 7)
        }
        .buttonStyle(.plain)
        Button(role: .destructive) { store.requestDeleteGeneration(generation) } label: { Image(systemName: "trash") }
            .buttonStyle(.plain).foregroundStyle(.secondary).padding(.trailing, 5)
            .opacity(hovered || store.selectedGeneration?.id == generation.id ? 1 : 0)
            .disabled(store.activeJob != nil)
            .help("Delete image").accessibilityLabel("Delete image \(generation.filename)")
        }
        .background(store.selectedGeneration?.id == generation.id ? Color.accentColor.opacity(0.13) : .clear, in: RoundedRectangle(cornerRadius: 7))
        .onHover { hovered = $0 }
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
            Button("Delete…", role: .destructive) { store.requestDeleteGeneration(generation) }
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
        }
        .background(Color(nsColor: .windowBackgroundColor))
    }
}

struct PerformanceBar: View {
    @EnvironmentObject private var store: StudioStore
    var body: some View {
        HStack(spacing: 8) {
            if let job = store.activeJob {
                ProgressView().controlSize(.small)
                Text(job.message).lineLimit(1)
                Spacer()
                if let elapsed = job.elapsed { Text(String(format: "%.1f s", elapsed)).monospacedDigit() }
            } else if let generation = store.selectedGeneration {
                Text(generation.model).lineLimit(1)
                Spacer()
                Text("\(generation.width) × \(generation.height)")
                Text(String(format: "·  %.1f s", generation.generationTime)).monospacedDigit()
            } else {
                Text(store.workspace.mode == .edit ? "Edit image" : store.workspace.mode == .fork ? "New variation" : "New image")
                Spacer()
                Text("\(store.workspace.width) × \(store.workspace.height)")
            }
        }
        .font(.caption).foregroundStyle(.secondary)
        .padding(.horizontal, 16).frame(height: 32)
        .accessibilityElement(children: .combine)
    }
}

struct CanvasView: View {
    @EnvironmentObject private var store: StudioStore
    @State private var zoom: CGFloat = 1
    @GestureState private var pinch: CGFloat = 1
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
                    GeometryReader { geometry in
                        let pixels = CGSize(width: generation.width, height: generation.height)
                        let fit = CanvasSizing.fit(image: pixels, viewport: geometry.size)
                        let base = actualSize ? CGSize(width: pixels.width / (NSScreen.main?.backingScaleFactor ?? 2), height: pixels.height / (NSScreen.main?.backingScaleFactor ?? 2)) : fit
                        let scale = max(0.2, min(5, zoom * pinch))
                        let display = CGSize(width: base.width * scale, height: base.height * scale)
                        ScrollView([.horizontal, .vertical]) {
                            Image(nsImage: image).resizable()
                                .frame(width: display.width, height: display.height)
                                .padding(20)
                                .frame(minWidth: geometry.size.width, minHeight: geometry.size.height)
                        }
                    }
                    .gesture(MagnificationGesture()
                        .updating($pinch) { value, state, _ in state = value }
                        .onEnded { zoom = max(0.2, min(5, zoom * $0)) })
                    .overlay(alignment: .bottomTrailing) {
                        HStack(spacing: 4) {
                            Button("Fit") { actualSize = false; zoom = 1 }.help("Fit to window")
                            Button { actualSize = true; zoom = 1 } label: { Text("100%") }.help("Actual size")
                            Button { zoom = max(0.2, zoom - 0.25) } label: { Image(systemName: "minus.magnifyingglass") }.help("Zoom out").accessibilityLabel("Zoom out")
                            Button { zoom = min(5, zoom + 0.25) } label: { Image(systemName: "plus.magnifyingglass") }.help("Zoom in").accessibilityLabel("Zoom in")
                        }
                        .buttonStyle(.bordered).controlSize(.small)
                        .padding(8).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
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
        .onChange(of: store.selectedGeneration?.id) { _ in actualSize = false; zoom = 1 }
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
        HStack(spacing: 12) {
            Button("Edit", systemImage: "pencil") { store.editSelected() }
            Button("Variation", systemImage: "dice") { store.variationSelected() }
            Button("Upscale", systemImage: "arrow.up.left.and.arrow.down.right") { store.showUpscaleNotice() }
            Spacer()
            Menu {
                Button("Fork") { store.forkSelected() }
                Button("Regenerate") { store.regenerateSelected() }
                Divider()
                Button("Save As…") { store.exportImage() }
                Button("Copy Image") { store.copyImage() }
                Button("Reveal in Finder") { store.revealImage() }
                Menu("Move to Project") {
                    Button("No Project") { store.moveSelected(to: nil) }
                    ForEach(store.projects.filter { !$0.archived }) { project in
                        Button(project.name) { store.moveSelected(to: project.id) }
                    }
                }
                Divider()
                Button("Delete…", role: .destructive) { store.requestDeleteGeneration() }
            } label: { Image(systemName: "ellipsis.circle") }
            .menuStyle(.borderlessButton).fixedSize().help("More image actions").accessibilityLabel("More image actions")
        }
        .disabled(store.activeJob != nil || store.selectedGeneration?.archived == true)
        .controlSize(.small).padding(.horizontal, 16).padding(.vertical, 9)
        .background(.bar)
    }
}

struct ComposerView: View {
    @EnvironmentObject private var store: StudioStore
    @FocusState private var promptFocused: Bool
    private var promptHeight: CGFloat {
        PromptEditorSizing.height(for: store.workspace.originalPrompt)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(store.workspace.mode == .edit ? "Describe your changes" : "Prompt").font(.headline)
                if store.isEnhanced {
                    Text("Enhanced · Review or edit").font(.caption).foregroundStyle(.secondary)
                    Button("Revert to Original") { store.revertPrompt() }.buttonStyle(.borderless).controlSize(.small)
                }
                if let name = store.workspace.referenceName {
                    Label(name, systemImage: "paperclip").lineLimit(1).font(.caption).foregroundStyle(.secondary)
                    Button { store.clearReference() } label: { Image(systemName: "xmark.circle") }
                        .buttonStyle(.plain).help("Remove reference image").accessibilityLabel("Remove reference image")
                }
                Spacer()
                Button { store.chooseReferenceImage() } label: { Image(systemName: "paperclip") }
                    .help("Attach reference image").accessibilityLabel("Attach reference image")
            }
            TextEditor(text: $store.workspace.originalPrompt)
                .font(.body).scrollContentBackground(.hidden)
                .frame(height: promptHeight).padding(3)
                .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 5))
                .focused($promptFocused).accessibilityLabel("Image prompt")
                .disabled(store.activeJob != nil)
            HStack(spacing: 10) {
                HelperPicker().frame(maxWidth: 280).disabled(store.activeJob != nil || store.isEnhancing)
                Button { Task { await store.enhancePrompt() } } label: {
                    HStack(spacing: 4) {
                        if store.isEnhancing { ProgressView().controlSize(.mini) }
                        else { Image(systemName: "sparkles") }
                        Text(store.isEnhancing ? "Enhancing…" : "Enhance")
                    }
                }
                .help("Enhance the visible prompt, then review or edit before generating")
                .disabled(store.activeJob != nil || store.isEnhancing || store.helperModelID == "off" || store.helperModelID.isEmpty || store.workspace.originalPrompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Menu {
                    Picker("Strength", selection: Binding(get: { store.promptStrength }, set: { store.promptStrength = $0 })) {
                        Text("Light").tag("light"); Text("Normal").tag("normal"); Text("Strong").tag("strong")
                    }
                    Button("Refresh Models") { Task { await store.refresh() } }
                } label: { Image(systemName: "slider.horizontal.3") }
                .fixedSize().menuStyle(.borderlessButton).accessibilityLabel("Prompt helper options").help("Prompt helper options")
                if let metrics = store.lastHelperMetrics {
                    HelperMetricsLabel(metrics: metrics)
                } else if store.helperUnavailable {
                    Text("Helper unavailable; Generate uses your prompt").font(.caption).foregroundStyle(.secondary).lineLimit(2)
                }
                Spacer(minLength: 0)
                Button("Generate", systemImage: "photo") { Task { await store.generate() } }
                    .buttonStyle(.borderedProminent).keyboardShortcut(.return, modifiers: .command)
                    .disabled(store.activeJob != nil || store.isEnhancing || store.workspace.originalPrompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            .controlSize(.small)
            if let notice = store.notice {
                Text(notice).font(.caption).foregroundStyle(.secondary)
            }
            if let status = store.promptImprovementNotice {
                Label(status, systemImage: "info.circle").font(.caption).foregroundStyle(.secondary)
                    .accessibilityIdentifier("promptImprovementStatus")
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 8).background(.bar)
        .overlay(alignment: .top) { Divider() }
        .onChange(of: store.promptFocusRequest) { _ in promptFocused = true }
        .task(id: store.notice) {
            guard store.notice != nil else { return }
            do { try await Task.sleep(nanoseconds: 5_000_000_000); store.notice = nil }
            catch {}
        }
    }
}

struct HelperPicker: View {
    @EnvironmentObject private var store: StudioStore
    var body: some View {
        Picker("Prompt Helper", selection: Binding(get: { store.helperModelID }, set: { store.chooseHelper($0) })) {
            Text("Off").tag("off")
            if store.helperModelID.isEmpty { Text("Unavailable").tag("") }
            ForEach(store.promptHelper.models, id: \.self) { Text(HelperPresentation.name(for: $0)).tag($0) }
            if !store.helperModelID.isEmpty && store.helperUnavailable {
                Text("\(HelperPresentation.name(for: store.helperModelID)) (unavailable)").tag(store.helperModelID)
            }
        }.pickerStyle(.menu).help(store.helperModelID == "off" ? "Prompt Helper is off" : "Server model ID: \(store.helperModelID)")
    }
}

struct HelperMetricsLabel: View {
    let metrics: PromptHelperMetrics
    var includesModel = true
    var body: some View {
        if metrics.hasDisplayMetrics {
            Text(((includesModel ? [HelperPresentation.name(for: metrics.model!)] : []) + metrics.displayParts).joined(separator: " · "))
                .font(.caption).monospacedDigit().foregroundStyle(.secondary)
                .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                .help("\(metrics.model!) — throughput is output tokens divided by total request latency.")
                .accessibilityIdentifier("promptHelperPerformance")
        }
    }
}

struct InspectorView: View {
    @EnvironmentObject private var store: StudioStore
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(store.selectedGeneration == nil ? "Generation" : "Image Info").font(.headline)
                Spacer()
                Button { store.showInspector = false } label: { Image(systemName: "sidebar.right") }
                    .buttonStyle(.plain).help("Hide inspector").accessibilityLabel("Hide inspector")
            }.padding(16)
            Divider()
            Form {
                if let gen = store.selectedGeneration {
                    Section("Image") {
                        info("Model", gen.model)
                        info("Resolution", "\(gen.width) × \(gen.height)")
                        info("Seed", "\(gen.seed)")
                        info("Steps", "\(gen.steps)")
                        info("Quantization", gen.quantizationLabel)
                    }
                    Section("Performance") {
                        info("Time", String(format: "%.2f s", gen.generationTime))
                        if !gen.isUpscale { info("Speed", String(format: "%.2f steps/s", gen.stepsPerSecond)) }
                        if let memory = gen.peakMemoryBytes { info("Peak memory", formatBytes(memory)) }
                    }
                    if let parent = gen.parentId {
                        Section("Lineage") {
                            if let source = store.generations.first(where: { $0.id == parent }) {
                                Button { store.select(source) } label: {
                                    Label("View parent image", systemImage: "arrow.turn.up.left")
                                }.help(source.originalPrompt)
                            } else { Text("Parent outside loaded history").foregroundStyle(.secondary) }
                            if let scale = gen.upscaleScaleFactor { info("Upscale", scale) }
                            if let precision = gen.upscalePrecision { info("Precision", precision) }
                            if gen.isUpscale { info("Source", "\(gen.upscaleSourceWidth) × \(gen.upscaleSourceHeight)") }
                        }
                    }
                    if gen.promptHelper.model != nil {
                        Section("Prompt Helper") {
                            Text(HelperPresentation.name(for: gen.promptHelper.model ?? "")).font(.caption).textSelection(.enabled).help(gen.promptHelper.model ?? "")
                            HelperMetricsLabel(metrics: gen.promptHelper, includesModel: false)
                        }
                    }
                    Button("Generation Settings") { store.selectedGeneration = nil; store.workspace.mode = .fork }
                } else {
                    Section("Generation") {
                        Picker("Image Model", selection: Binding(get: { store.workspace.modelId }, set: { store.chooseImageModel($0) })) {
                            ForEach(store.generationModels) { Text($0.label).tag($0.id) }
                        }
                        Picker("Resolution", selection: aspectBinding) {
                            Text("Square · 1024 × 1024").tag("square")
                            Text("4:3 · 1152 × 864").tag("4:3")
                            Text("3:4 · 864 × 1152").tag("3:4")
                            Text("Portrait · 768 × 1344").tag("portrait")
                            Text("Landscape · 1344 × 768").tag("landscape")
                            Text("Custom").tag("custom")
                        }
                        HStack {
                            TextField("Width", value: $store.workspace.width, format: .number)
                            Text("×").foregroundStyle(.secondary)
                            TextField("Height", value: $store.workspace.height, format: .number)
                        }
                        Stepper("Steps: \(store.workspace.steps)", value: $store.workspace.steps, in: 1...100)
                        Toggle("Random seed", isOn: $store.workspace.randomSeed)
                        if !store.workspace.randomSeed { TextField("Seed", value: $store.workspace.seed, format: .number) }
                        Picker("Project", selection: Binding(get: { store.workspace.projectId }, set: { store.chooseDraftProject($0) })) {
                            Text("No Project").tag(nil as String?)
                            ForEach(store.projects.filter { !$0.archived }) { Text($0.name).tag($0.id as String?) }
                        }
                    }
                    DisclosureGroup("Advanced", isExpanded: $store.showAdvanced) {
                        Picker("Quantization", selection: $store.workspace.quantization) {
                            Text("None").tag(nil as Int?)
                            ForEach([4, 6, 8], id: \.self) { Text("\($0)-bit").tag($0 as Int?) }
                        }
                        Picker("Variants", selection: $store.workspace.variantCount) {
                            ForEach([1, 2, 4], id: \.self) { Text("\($0)").tag($0) }
                        }
                        Picker("LoRA", selection: $store.workspace.loraId) {
                            Text("None").tag(nil as String?)
                            ForEach(store.loras) { Text($0.name).tag($0.id as String?) }
                        }
                        if store.workspace.loraId != nil { TextField("LoRA strength", value: $store.workspace.loraScale, format: .number) }
                    }
                    Button("Manage Models…") { store.showModels = true }
                }
            }.formStyle(.grouped).controlSize(.small)
        }.background(Color(nsColor: .windowBackgroundColor))
    }
    private func info(_ title: String, _ value: String) -> some View {
        LabeledContent(title) { Text(value).textSelection(.enabled) }
    }
    private var aspectBinding: Binding<String> {
        Binding {
            switch (store.workspace.width, store.workspace.height) {
            case (1024, 1024): return "square"
            case (1152, 864): return "4:3"
            case (864, 1152): return "3:4"
            case (768, 1344): return "portrait"
            case (1344, 768): return "landscape"
            default: return "custom"
            }
        } set: { value in
            switch value {
            case "square": store.workspace.width = 1024; store.workspace.height = 1024
            case "4:3": store.workspace.width = 1152; store.workspace.height = 864
            case "3:4": store.workspace.width = 864; store.workspace.height = 1152
            case "portrait": store.workspace.width = 768; store.workspace.height = 1344
            case "landscape": store.workspace.width = 1344; store.workspace.height = 768
            default: break
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
                HelperPicker()
                Picker("Strength", selection: Binding(get: { store.promptStrength }, set: { store.promptStrength = $0 })) {
                    Text("Light").tag("light"); Text("Normal").tag("normal"); Text("Strong").tag("strong")
                }
                Button("Refresh Models") { Task { await store.refresh() } }
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
                            .clipShape(RoundedRectangle(cornerRadius: 6))
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
        await store.performUpscale(job: UpscaleJob(sourceGenerationId: sourceGeneration.id, scale: scale, softness: softness, seed: seed, projectId: sourceGeneration.projectId))
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
