import Foundation

struct ModelInfo: Codable, Identifiable, Hashable {
    let id: String
    let label: String
    let purpose: String?
    var supportsGeneration: Bool { purpose == "generation" || (purpose == nil && !id.hasPrefix("seedvr")) }
    let tagline: String
    let status: String
    let approxSize: String?
}

struct LoRAInfo: Codable, Identifiable, Hashable {
    let id: String
    let name: String
}

struct ProjectInfo: Codable, Identifiable, Hashable {
    let id: String
    var name: String
    var archived: Bool
    var generationCount: Int
    let createdAt: String
    var updatedAt: String
}

struct PromptHelperMetrics: Codable, Hashable {
    let model: String?
    let tokensPerSecond: Double?
    let timeToFirstToken: Double?
    let tokenCount: Int?
    let totalTime: Double?
}

struct Generation: Codable, Identifiable, Hashable {
    let id: String
    let parentId: String?
    var projectId: String?
    let originalPrompt: String
    let improvedPrompt: String
    let promptImprovementModel: String?
    let promptImprovementStrength: String?
    let promptHelper: PromptHelperMetrics
    let modelId: String
    let model: String
    let quantization: Int?
    let quantizationLabel: String
    let seed: Int
    let width: Int
    let height: Int
    let steps: Int
    let generationTime: Double
    let secondsPerImage: Double
    let stepsPerSecond: Double
    let peakMemoryBytes: Int64?
    let gpuUtilization: Double?
    let referenceUsed: Bool
    let referenceSourceId: String?
    let referenceImagePath: String?
    let loraName: String?
    let loraScale: Double?
    let variantGroupId: String?
    let variantIndex: Int
    let variantCount: Int
    let generationGroupId: String?
    let createdAt: String
    let imagePath: String
    let thumbnailPath: String?
    let filename: String
    let archived: Bool
    // Upscale metadata
    let upscaleSourceWidth: Int
    let upscaleSourceHeight: Int
    let upscaleScaleFactor: String?
    let upscaleModelVariant: String?
    let upscalePrecision: String?

    var date: Date {
        ISO8601DateFormatter.studio.date(from: createdAt) ?? .distantPast
    }

    var isUpscale: Bool {
        modelId == "seedvr2_7b"
    }
}

struct ModelRuntimeStatus: Codable, Hashable {
    let status: String
    let modelId: String?
    let activeMemoryBytes: Int64?

    static let unloaded = ModelRuntimeStatus(status: "unloaded", modelId: nil, activeMemoryBytes: nil)
}

struct PromptHelperAvailability: Codable, Hashable {
    var models: [String] = []
    let available: Bool
    let model: String?
    let notice: String?
}

struct StorageInfo: Codable, Hashable {
    let format: String
    let archive: String
}

struct BootstrapResponse: Codable {
    let models: [ModelInfo]
    let generations: [Generation]
    let projects: [ProjectInfo]
    let loras: [LoRAInfo]
    let activeJob: GenerationJob?
    let modelStatus: ModelRuntimeStatus
    let promptHelper: PromptHelperAvailability
    let storage: StorageInfo
}

struct GenerationJob: Codable, Identifiable {
    let id: String
    let state: String
    let phase: String?
    let message: String
    let createdAt: String?
    let step: Int?
    let steps: Int?
    let variantIndex: Int?
    let variantCount: Int?
    let elapsed: Double?
    let peakMemoryBytes: Int64?
    let originalPrompt: String?
    let improvedPrompt: String?
    let promptNotice: String?
    let promptHelper: PromptHelperMetrics?
    let generation: Generation?
    let generations: [Generation]?
    let modelStatus: ModelRuntimeStatus?
    // Upscale-specific fields
    let sourceGenerationId: String?
    let scale: String?
    let softness: Double?
    let outputPath: String?
}

struct UpscaleJob: Identifiable {
    var requestPayload: [String: Any] {
        var payload: [String: Any] = ["source_generation_id": sourceGenerationId,
                                    "scale": scale, "softness": softness, "seed": seed]
        if let projectId { payload["project_id"] = projectId }
        return payload
    }

    let id = UUID()
    var sourceGenerationId: String
    var scale: String = "2x"
    var softness: Double = 0.5
    var quantization: Int? = nil
    var seed: Int = 42
    var projectId: String?
    var isRunning: Bool = false
    var errorMessage: String?
}

struct StatusResponse: Codable {
    let activeJob: GenerationJob?
    let modelStatus: ModelRuntimeStatus
}

struct OKResponse: Codable { let ok: Bool }

struct ErrorResponse: Codable { let error: String }

extension ISO8601DateFormatter {
    static let studio: ISO8601DateFormatter = {
        let value = ISO8601DateFormatter()
        value.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return value
    }()
}

enum WorkspaceMode: String {
    case newImage
    case viewing
    case fork
    case edit
}

struct WorkspaceState {
    var mode: WorkspaceMode = .newImage
    var originalPrompt = ""
    var improvedPrompt = ""
    var modelId = "flux2_klein_4b"
    var width = 1024
    var height = 1024
    var steps = 4
    var quantization: Int? = nil
    var randomSeed = true
    var seed = 42
    var variantCount = 1
    var parentId: String? = nil
    var projectId: String? = nil
    var referenceGenerationId: String? = nil
    var referenceData: String? = nil
    var referencePath: String? = nil
    var referenceName: String? = nil
    var loraId: String? = nil
    var loraScale = 1.0
}

struct UpscaleJobResponse: Codable, Identifiable {
    let id: String
}

struct UpscaleJobStatus: Codable, Identifiable {
    let id: String?
    let state: String?
    let message: String?
}

enum HistorySection: String, CaseIterable, Identifiable {
    case today = "Today"
    case yesterday = "Yesterday"
    case previous7Days = "Previous 7 Days"
    case older = "Older"
    var id: String { rawValue }
}

// Fit uses viewport geometry, never the image's native display size. Upscaling
// low-resolution images is intentional; the image aspect ratio is preserved.
enum CanvasSizing {
    static func fit(image: CGSize, viewport: CGSize, margin: CGFloat = 20) -> CGSize {
        guard image.width > 0, image.height > 0 else { return .zero }
        let scale = min(max(0, viewport.width - margin * 2) / image.width,
                        max(0, viewport.height - margin * 2) / image.height)
        return CGSize(width: image.width * scale, height: image.height * scale)
    }
}
