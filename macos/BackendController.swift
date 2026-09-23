import AppKit
import Foundation

enum BackendError: LocalizedError {
    case notReady
    case message(String)

    var errorDescription: String? {
        switch self {
        case .notReady: return L10n.text("The private backend is not ready.")
        case .message(let message): return message
        }
    }
}

@MainActor
final class BackendController: ObservableObject {
    static let shared = BackendController()

    @Published private(set) var isReady = false
    @Published private(set) var launchError: String?

    private var process: Process?
    private var outputBuffer = ""
    private var baseURL: URL?
    private let token = UUID().uuidString.replacingOccurrences(of: "-", with: "")
    private let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 60
        config.timeoutIntervalForResource = 3600
        config.waitsForConnectivity = false
        return URLSession(configuration: config)
    }()
    private var readyContinuations: [CheckedContinuation<Void, Error>] = []

    private init() {}

    func start() {
        guard process == nil else { return }
        guard let resources = Bundle.main.resourceURL else {
            failLaunch(L10n.text("The app resources could not be found."))
            return
        }
        let backend = resources.appendingPathComponent("backend_v2.py")
        let python = ProcessInfo.processInfo.environment["LIS_MFLUX_PYTHON"]
            .map { URL(fileURLWithPath: $0) }
            ?? FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent(".local/share/uv/tools/mflux/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            failLaunch(L10n.text("The existing MFLUX Python runtime could not be found."))
            return
        }
        let process = Process()
        let stdoutPipe = Pipe()
        do {
            let logsDir = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask).first!
                .appendingPathComponent("Logs").appendingPathComponent("Local Image Studio")
            try FileManager.default.createDirectory(at: logsDir, withIntermediateDirectories: true)
            let logURL = logsDir.appendingPathComponent("backend_stderr.log")
            process.standardError = try FileHandle(forWritingTo: logURL)
        } catch {
            process.standardError = FileHandle.standardError
        }
        process.executableURL = python
        process.arguments = [
            backend.path,
            "--port", "0",
            "--token", token,
            "--parent-pid", String(ProcessInfo.processInfo.processIdentifier),
            "--prompt-helper-model", UserDefaults.standard.string(forKey: "promptHelperModelID") ?? "",
        ]
        process.currentDirectoryURL = resources
        process.standardOutput = stdoutPipe
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
        environment["DO_NOT_TRACK"] = "1"
        process.environment = environment
        process.terminationHandler = { [weak self] finished in
            DispatchQueue.main.async {
                guard let self else { return }
                if !self.isReady && self.process != nil {
                    self.failLaunch(L10n.text("The private backend stopped before the app was ready."))
                }
            }
        }
        stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            DispatchQueue.main.async { self?.receive(text) }
        }
        do {
            try process.run()
            self.process = process
        } catch {
            failLaunch(L10n.format("The private backend could not start: %@", error.localizedDescription))
        }
    }

    private func receive(_ text: String) {
        outputBuffer += text
        let lines = outputBuffer.components(separatedBy: .newlines)
        outputBuffer = lines.last ?? ""
        for line in lines.dropLast() {
            let parts = line.split(separator: " ")
            guard parts.count >= 3, parts[0] == "READY", let port = Int(parts[1]) else { continue }
            baseURL = URL(string: "http://127.0.0.1:\(port)")
            isReady = true
            let continuations = readyContinuations
            readyContinuations.removeAll()
            continuations.forEach { $0.resume() }
        }
    }

    private func failLaunch(_ message: String) {
        launchError = message
        let continuations = readyContinuations
        readyContinuations.removeAll()
        continuations.forEach { $0.resume(throwing: BackendError.message(message)) }
    }

    private func awaitReady() async throws {
        if isReady { return }
        if let launchError { throw BackendError.message(launchError) }
        try await withCheckedThrowingContinuation { continuation in
            readyContinuations.append(continuation)
        }
    }

    private func makeRequest(path: String, method: String = "GET", json: [String: Any]? = nil) async throws -> URLRequest {
        try await awaitReady()
        guard let baseURL, let url = URL(string: path, relativeTo: baseURL) else { throw BackendError.notReady }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue(token, forHTTPHeaderField: "X-Local-Image-Studio-Token")
        if let json {
            request.httpBody = try JSONSerialization.data(withJSONObject: json)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return request
    }

    func get<T: Decodable>(_ path: String, as type: T.Type = T.self) async throws -> T {
        let request = try await makeRequest(path: path)
        return try await execute(request, as: type)
    }

    func post<T: Decodable>(_ path: String, json: [String: Any] = [:], as type: T.Type = T.self) async throws -> T {
        let request = try await makeRequest(path: path, method: "POST", json: json)
        return try await execute(request, as: type)
    }

    func delete<T: Decodable>(_ path: String, as type: T.Type = T.self) async throws -> T {
        let request = try await makeRequest(path: path, method: "DELETE")
        return try await execute(request, as: type)
    }

    private func execute<T: Decodable>(_ request: URLRequest, as type: T.Type) async throws -> T {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw BackendError.message(L10n.text("Invalid backend response.")) }
        if !(200..<300).contains(http.statusCode) {
            let decoded = try? decoder.decode(ErrorResponse.self, from: data).error
            let message = decoded.map { L10n.text($0) }
                ?? L10n.format("Backend request failed (%d).", http.statusCode)
            throw BackendError.message(message)
        }
        return try decoder.decode(type, from: data)
    }

    private var decoder: JSONDecoder {
        let value = JSONDecoder()
        value.keyDecodingStrategy = .convertFromSnakeCase
        return value
    }

    func shutdownSynchronously() {
        guard let process else { return }
        if let baseURL, let url = URL(string: "/api/shutdown", relativeTo: baseURL) {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue(token, forHTTPHeaderField: "X-Local-Image-Studio-Token")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = Data("{}".utf8)
            let semaphore = DispatchSemaphore(value: 0)
            session.dataTask(with: request) { _, _, _ in semaphore.signal() }.resume()
            _ = semaphore.wait(timeout: .now() + 8)
        }
        if process.isRunning {
            process.terminate()
            let deadline = Date().addingTimeInterval(4)
            while process.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
            if process.isRunning { kill(process.processIdentifier, SIGKILL) }
        }
        self.process = nil
        isReady = false
    }
}
