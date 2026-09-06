import AppKit
import Combine
import SwiftUI

@main
struct LocalImageStudioLauncher {
    static func main() {
        let application = NSApplication.shared
        let delegate = AppDelegate()
        application.delegate = delegate
        application.setActivationPolicy(.regular)
        application.run()
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSToolbarDelegate, NSMenuItemValidation {
    private var memoryPressureSource: DispatchSourceMemoryPressure?
    private var mainWindow: NSWindow!
    private var settingsWindow: NSWindow?
    private var toolbarStatusLabel: NSTextField?
    private var toolbarProgress: NSProgressIndicator?
    private var toolbarModelPopup: NSPopUpButton?
    private var cancellables = Set<AnyCancellable>()
    private let sidebarItem = NSToolbarItem.Identifier("LocalImageStudio.Sidebar")
    private let modelItem = NSToolbarItem.Identifier("LocalImageStudio.Model")
    private let statusItem = NSToolbarItem.Identifier("LocalImageStudio.Status")
    private let modelsItem = NSToolbarItem.Identifier("LocalImageStudio.Models")

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        BackendController.shared.start()
        buildMainWindow()
        buildMainMenu()
        observeToolbarState()
        let source = DispatchSource.makeMemoryPressureSource(eventMask: [.warning, .critical], queue: .main)
        source.setEventHandler {
            Task { @MainActor in await StudioStore.shared.unloadForMemoryPressure() }
        }
        source.resume()
        memoryPressureSource = source
        mainWindow.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if ProcessInfo.processInfo.environment["LIS_CAPTURE_SELF"] == "1" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.captureWindowForTesting() }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        memoryPressureSource?.cancel()
        BackendController.shared.shutdownSynchronously()
    }

    func windowWillClose(_ notification: Notification) {
        if notification.object as? NSWindow === mainWindow { NSApp.terminate(nil) }
    }

    private func buildMainWindow() {
        let root = ContentView()
            .environmentObject(StudioStore.shared)
            .task { await StudioStore.shared.load() }
        let hosting = NSHostingView(rootView: root)
        mainWindow = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1280, height: 840),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        mainWindow.title = "Local Image Studio"
        mainWindow.titleVisibility = .hidden
        mainWindow.titlebarAppearsTransparent = true
        mainWindow.minSize = NSSize(width: 940, height: 680)
        mainWindow.collectionBehavior.insert(.fullScreenPrimary)
        mainWindow.isReleasedWhenClosed = false
        mainWindow.delegate = self
        mainWindow.contentView = hosting
        let toolbar = NSToolbar(identifier: "LocalImageStudio.MainToolbar")
        toolbar.delegate = self
        toolbar.displayMode = .iconOnly
        toolbar.allowsUserCustomization = false
        mainWindow.toolbar = toolbar
        mainWindow.toolbarStyle = .unified
        mainWindow.center()
    }

    private func captureWindowForTesting() {
        guard let view = mainWindow.contentView,
              let representation = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: representation)
        if let data = representation.representation(using: .png, properties: [:]) {
            try? data.write(to: URL(fileURLWithPath: "/private/tmp/local-image-studio-v2-self.png"), options: .atomic)
        }
    }

    private func buildMainMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        menu.addItem(appItem)
        let appMenu = NSMenu()
        appItem.submenu = appMenu
        appMenu.addItem(withTitle: "About Local Image Studio", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        let settings = NSMenuItem(title: "Settings…", action: #selector(showSettings), keyEquivalent: ",")
        settings.target = self
        appMenu.addItem(settings)
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Local Image Studio", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Local Image Studio", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        let fileItem = NSMenuItem()
        menu.addItem(fileItem)
        let fileMenu = NSMenu(title: "File")
        fileItem.submenu = fileMenu
        fileMenu.addItem(command("New Image", action: #selector(newImage), key: "n"))
        fileMenu.addItem(command("New Project…", action: #selector(newProject), key: "n", modifiers: [.command, .shift]))
        fileMenu.addItem(.separator())
        fileMenu.addItem(command("Save / Export…", action: #selector(exportImage), key: "s"))

        let editItem = NSMenuItem()
        menu.addItem(editItem)
        let editMenu = NSMenu(title: "Edit")
        editItem.submenu = editMenu
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(.separator())
        editMenu.addItem(command("Copy Image", action: #selector(copyImage), key: "c"))

        let generationItem = NSMenuItem()
        menu.addItem(generationItem)
        let generationMenu = NSMenu(title: "Generation")
        generationItem.submenu = generationMenu
        generationMenu.addItem(command("Generate", action: #selector(generate), key: "g"))
        generationMenu.addItem(.separator())
        generationMenu.addItem(command("Fork", action: #selector(forkImage), key: ""))
        generationMenu.addItem(command("Edit", action: #selector(editImage), key: ""))
        generationMenu.addItem(command("Reveal in Finder", action: #selector(revealImage), key: ""))

        let viewItem = NSMenuItem()
        menu.addItem(viewItem)
        let viewMenu = NSMenu(title: "View")
        viewItem.submenu = viewMenu
        viewMenu.addItem(command("Toggle Sidebar", action: #selector(toggleSidebar), key: "s", modifiers: [.command, .control]))
        viewMenu.addItem(.separator())
        viewMenu.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        viewMenu.items.last?.keyEquivalentModifierMask = [.command, .control]

        let windowItem = NSMenuItem()
        menu.addItem(windowItem)
        let windowMenu = NSMenu(title: "Window")
        windowItem.submenu = windowMenu
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.miniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        NSApp.windowsMenu = windowMenu

        NSApp.mainMenu = menu
    }

    func toolbarAllowedItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        [sidebarItem, .space, modelItem, statusItem, .flexibleSpace, modelsItem]
    }

    func toolbarDefaultItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        [sidebarItem, .space, modelItem, statusItem, .flexibleSpace, modelsItem]
    }

    func toolbar(_ toolbar: NSToolbar, itemForItemIdentifier identifier: NSToolbarItem.Identifier, willBeInsertedIntoToolbar flag: Bool) -> NSToolbarItem? {
        let item = NSToolbarItem(itemIdentifier: identifier)
        switch identifier {
        case sidebarItem:
            let button = NSButton(image: NSImage(systemSymbolName: "sidebar.left", accessibilityDescription: "Toggle Sidebar")!, target: self, action: #selector(toggleSidebar))
            button.bezelStyle = .texturedRounded
            item.view = button
            item.label = "Sidebar"
            item.toolTip = "Toggle Sidebar"
        case modelItem:
            let popup = NSPopUpButton(frame: NSRect(x: 0, y: 0, width: 230, height: 28), pullsDown: false)
            popup.addItems(withTitles: ["FLUX.2 Klein 4B — Fast", "FLUX.2 Klein 9B — Quality"])
            popup.target = self
            popup.action = #selector(modelChanged(_:))
            popup.selectItem(at: StudioStore.shared.workspace.modelId.contains("9b") ? 1 : 0)
            toolbarModelPopup = popup
            item.view = popup
            item.label = "Model"
        case statusItem:
            let progress = NSProgressIndicator()
            progress.style = .spinning
            progress.controlSize = .small
            progress.isDisplayedWhenStopped = false
            let label = NSTextField(labelWithString: "Unloaded")
            label.textColor = .secondaryLabelColor
            label.font = .systemFont(ofSize: 11)
            let stack = NSStackView(views: [progress, label])
            stack.orientation = .horizontal
            stack.spacing = 6
            toolbarProgress = progress
            toolbarStatusLabel = label
            item.view = stack
            item.label = "Status"
        case modelsItem:
            let button = NSButton(image: NSImage(systemSymbolName: "square.stack.3d.up", accessibilityDescription: "Models")!, target: self, action: #selector(showModels))
            button.bezelStyle = .texturedRounded
            item.view = button
            item.label = "Models"
            item.toolTip = "Model Management"
        default:
            return nil
        }
        return item
    }

    private func observeToolbarState() {
        StudioStore.shared.$modelStatus
            .combineLatest(StudioStore.shared.$activeJob)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] status, job in self?.updateToolbarStatus(status: status, job: job) }
            .store(in: &cancellables)
        StudioStore.shared.$workspace
            .receive(on: DispatchQueue.main)
            .sink { [weak self] workspace in
                self?.toolbarModelPopup?.selectItem(at: workspace.modelId.contains("9b") ? 1 : 0)
            }
            .store(in: &cancellables)
    }

    private func updateToolbarStatus(status: ModelRuntimeStatus, job: GenerationJob?) {
        if job?.phase == "loading" {
            toolbarStatusLabel?.stringValue = job?.message ?? "Loading…"
            toolbarProgress?.startAnimation(nil)
        } else {
            toolbarProgress?.stopAnimation(nil)
            if status.status == "loaded", let model = status.modelId {
                toolbarStatusLabel?.stringValue = model.contains("9b") ? "9B Loaded" : "4B Loaded"
                toolbarStatusLabel?.textColor = .systemGreen
            } else {
                toolbarStatusLabel?.stringValue = "Unloaded"
                toolbarStatusLabel?.textColor = .secondaryLabelColor
            }
        }
    }

    private func command(_ title: String, action: Selector, key: String, modifiers: NSEvent.ModifierFlags = .command) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.keyEquivalentModifierMask = modifiers
        item.target = self
        return item
    }

    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool {
        if menuItem.action == #selector(copyImage) {
            if mainWindow.firstResponder is NSTextView { return false }
            return StudioStore.shared.selectedGeneration != nil
        }
        return true
    }

    @objc private func newImage() { StudioStore.shared.newImage() }
    @objc private func newProject() { StudioStore.shared.createProject() }
    @objc private func exportImage() { StudioStore.shared.exportImage() }
    @objc private func copyImage() { StudioStore.shared.copyImage() }
    @objc private func forkImage() { StudioStore.shared.forkSelected() }
    @objc private func editImage() { StudioStore.shared.editSelected() }
    @objc private func revealImage() { StudioStore.shared.revealImage() }
    @objc private func generate() { Task { await StudioStore.shared.generate() } }
    @objc private func toggleSidebar() { NotificationCenter.default.post(name: .toggleStudioSidebar, object: nil) }
    @objc private func modelChanged(_ sender: NSPopUpButton) {
        StudioStore.shared.workspace.modelId = sender.indexOfSelectedItem == 1 ? "flux2_klein_9b" : "flux2_klein_4b"
    }
    @objc private func showModels() { StudioStore.shared.showModels = true }

    @objc private func showSettings() {
        if let settingsWindow {
            settingsWindow.makeKeyAndOrderFront(nil)
            return
        }
        let hosting = NSHostingView(rootView: SettingsView().environmentObject(StudioStore.shared))
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 430),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = "Local Image Studio Settings"
        window.contentView = hosting
        window.center()
        settingsWindow = window
        window.makeKeyAndOrderFront(nil)
    }
}
