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
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuItemValidation {
    private var memoryPressureSource: DispatchSourceMemoryPressure?
    private var mainWindow: NSWindow!
    private var settingsWindow: NSWindow?
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        BackendController.shared.start()
        buildMainWindow()
        buildMainMenu()
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
        mainWindow.title = L10n.text("Local Image Studio")
        mainWindow.titleVisibility = .hidden
        mainWindow.titlebarAppearsTransparent = true
        mainWindow.minSize = NSSize(width: 940, height: 680)
        mainWindow.collectionBehavior.insert(.fullScreenPrimary)
        mainWindow.isReleasedWhenClosed = false
        mainWindow.delegate = self
        mainWindow.contentView = hosting
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
        appMenu.addItem(withTitle: L10n.text("About Local Image Studio"), action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        let settings = NSMenuItem(title: L10n.text("Settings…"), action: #selector(showSettings), keyEquivalent: ",")
        settings.target = self
        appMenu.addItem(settings)
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: L10n.text("Hide Local Image Studio"), action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: L10n.text("Quit Local Image Studio"), action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        let fileItem = NSMenuItem()
        menu.addItem(fileItem)
        let fileMenu = NSMenu(title: L10n.text("File"))
        fileItem.submenu = fileMenu
        fileMenu.addItem(command(L10n.text("New Image"), action: #selector(newImage), key: "n"))
        fileMenu.addItem(command(L10n.text("New Project…"), action: #selector(newProject), key: "n", modifiers: [.command, .shift]))
        fileMenu.addItem(.separator())
        fileMenu.addItem(command(L10n.text("Save As…"), action: #selector(exportImage), key: "s"))
        fileMenu.addItem(command(L10n.text("Export…"), action: #selector(exportImage), key: "e"))

        let editItem = NSMenuItem()
        menu.addItem(editItem)
        let editMenu = NSMenu(title: L10n.text("Edit"))
        editItem.submenu = editMenu
        editMenu.addItem(withTitle: L10n.text("Undo"), action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: L10n.text("Redo"), action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: L10n.text("Cut"), action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: L10n.text("Copy"), action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: L10n.text("Paste"), action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: L10n.text("Select All"), action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editMenu.addItem(.separator())
        editMenu.addItem(command(L10n.text("Copy Image"), action: #selector(copyImage), key: "c"))

        let generationItem = NSMenuItem()
        menu.addItem(generationItem)
        let generationMenu = NSMenu(title: L10n.text("Generation"))
        generationItem.submenu = generationMenu
        generationMenu.addItem(command(L10n.text("Generate"), action: #selector(generate), key: "g"))
        generationMenu.addItem(.separator())
        generationMenu.addItem(command(L10n.text("Fork"), action: #selector(forkImage), key: ""))
        generationMenu.addItem(command(L10n.text("Edit"), action: #selector(editImage), key: ""))
        generationMenu.addItem(command(L10n.text("Reveal in Finder"), action: #selector(revealImage), key: ""))

        let viewItem = NSMenuItem()
        menu.addItem(viewItem)
        let viewMenu = NSMenu(title: L10n.text("View"))
        viewItem.submenu = viewMenu
        viewMenu.addItem(command(L10n.text("Toggle Sidebar"), action: #selector(toggleSidebar), key: "s", modifiers: [.command, .control]))
        viewMenu.addItem(command(L10n.text("Toggle Inspector"), action: #selector(toggleInspector), key: "i", modifiers: [.command, .option]))
        viewMenu.addItem(.separator())
        viewMenu.addItem(withTitle: L10n.text("Enter Full Screen"), action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        viewMenu.items.last?.keyEquivalentModifierMask = [.command, .control]

        let windowItem = NSMenuItem()
        menu.addItem(windowItem)
        let windowMenu = NSMenu(title: L10n.text("Window"))
        windowItem.submenu = windowMenu
        windowMenu.addItem(withTitle: L10n.text("Minimize"), action: #selector(NSWindow.miniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: L10n.text("Zoom"), action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        NSApp.windowsMenu = windowMenu

        NSApp.mainMenu = menu
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
    @objc private func toggleInspector() { StudioStore.shared.showInspector.toggle() }
    @objc private func toggleSidebar() { NotificationCenter.default.post(name: .toggleStudioSidebar, object: nil) }
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
        window.title = L10n.text("Local Image Studio Settings")
        window.contentView = hosting
        window.center()
        settingsWindow = window
        window.makeKeyAndOrderFront(nil)
    }
}
