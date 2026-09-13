import Foundation
import Flux2
import MLX
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

// MARK: - Configuration (4B Klein, distilled)
let MODEL_SNAPSHOT = URL(
  fileURLWithPath: "/Users/ricknichols/.cache/huggingface/hub/models--black-forest-labs--FLUX.2-klein-4B/snapshots/e7b7dc27f91deacad38e78976d1f2b499d76a294"
)

let OUTPUT_PATH = "/Users/ricknichols/LocalImageStudio-v3/artifacts/generated_4b_klein.png"
let PROMPT = "a cat sitting on a windowsill looking at rain"
let WIDTH = 512
let HEIGHT = 512
let NUM_INFERENCE_STEPS = 4
let SEED: UInt64 = 42

// MARK: - Write MLXArray as PNG (inlined from CLI+Image.swift)
func writePNG(image: MLXArray, url: URL) throws {
  let outputURL = url.standardizedFileURL
  try FileManager.default.createDirectory(
    at: outputURL.deletingLastPathComponent(),
    withIntermediateDirectories: true,
    attributes: nil
  )

  guard image.ndim == 4 else {
    throw NSError(domain: "MinimalHarnes", code: 1,
                  userInfo: [NSLocalizedDescriptionKey: "decoded image must be NCHW (4D)"])
  }

  let batch = image.dim(0)
  guard batch >= 1 else {
    throw NSError(domain: "MinimalHarnes", code: 2,
                  userInfo: [NSLocalizedDescriptionKey: "decoded image batch is empty"])
  }

  let channels = image.dim(1)
  guard channels == 3 else {
    throw NSError(domain: "MinimalHarnes", code: 3,
                  userInfo: [NSLocalizedDescriptionKey: "decoded image must have 3 channels, got \(channels)"])
  }

  let height = image.dim(2)
  let width = image.dim(3)

  // Convert from [-1, 1] to [0, 255] uint8
  var rgb = image[0].asType(.float32)
  rgb = (rgb / MLXArray(2.0)) + MLXArray(0.5)
  rgb = MLX.clip(rgb, min: 0.0, max: 1.0)
  rgb = rgb * MLXArray(255.0)
  rgb = rgb.transposed(1, 2, 0)
  let flat = rgb.reshaped(-1).asArray(UInt8.self)

  // Add alpha channel (opaque)
  var rgba = [UInt8](repeating: 255, count: width * height * 4)
  var rgbIndex = 0
  for pixel in 0..<(width * height) {
    rgba[pixel * 4] = flat[rgbIndex]
    rgba[pixel * 4 + 1] = flat[rgbIndex + 1]
    rgba[pixel * 4 + 2] = flat[rgbIndex + 2]
    rgbIndex += 3
  }

  let data = Data(rgba)
  guard let provider = CGDataProvider(data: data as CFData) else {
    throw NSError(domain: "MinimalHarnes", code: 4,
                  userInfo: [NSLocalizedDescriptionKey: "Failed to create image provider"])
  }

  let colorSpace = CGColorSpaceCreateDeviceRGB()
  let bitmapInfo = CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue)
  guard let cgImage = CGImage(
    width: width,
    height: height,
    bitsPerComponent: 8,
    bitsPerPixel: 32,
    bytesPerRow: width * 4,
    space: colorSpace,
    bitmapInfo: bitmapInfo,
    provider: provider,
    decode: nil,
    shouldInterpolate: true,
    intent: .defaultIntent
  ) else {
    throw NSError(domain: "MinimalHarnes", code: 5,
                  userInfo: [NSLocalizedDescriptionKey: "Failed to create CGImage"])
  }

  guard let destination = CGImageDestinationCreateWithURL(
    outputURL as CFURL, UTType.png.identifier as CFString, 1, nil
  ) else {
    throw NSError(domain: "MinimalHarnes", code: 6,
                  userInfo: [NSLocalizedDescriptionKey: "Failed to create image destination"])
  }

  CGImageDestinationAddImage(destination, cgImage, nil)
  guard CGImageDestinationFinalize(destination) else {
    throw NSError(domain: "MinimalHarnes", code: 7,
                  userInfo: [NSLocalizedDescriptionKey: "Failed to finalize image"])
  }

  print("  Output saved: \(outputURL.path)")
}

// MARK: - Main
do {
  print("=== Minimal FLUX.2 Klein 4B Generation ===")
  print("Swift: \(ProcessInfo.processInfo.operatingSystemVersionString)")
  print("Model snapshot: \(MODEL_SNAPSHOT.path)")
  print("Output path: \(OUTPUT_PATH)")

  // Set seed for reproducibility
  MLXRandom.seed(SEED)

  // Phase 1: Load pipeline (cold load)
  print("\n--- Loading pipeline (cold) ---")
  let loadStart = Date()
  let pipeline = try Flux2KleinPipeline(
    snapshot: MODEL_SNAPSHOT,
    dtype: .bfloat16,
    loadTokenizer: true
  )
  let loadElapsed = Date().timeIntervalSince(loadStart)
  print("  Load time: \(String(format: "%.2f", loadElapsed))s")
  print("  isDistilled: \(pipeline.isDistilled)")

  // Phase 2: Generate image
  print("\n--- Generating image ---")
  let genStart = Date()
  let output = try pipeline.generate(
    prompts: [PROMPT],
    height: HEIGHT,
    width: WIDTH,
    numInferenceSteps: NUM_INFERENCE_STEPS,
    guidanceScale: 1.0  // distilled model — no guidance
  )
  let genElapsed = Date().timeIntervalSince(genStart)

  print("  Generation time: \(String(format: "%.2f", genElapsed))s")
  print("  Output shape: \(output.decoded.shape)")

  // Phase 3: Save image
  print("\n--- Saving output ---")
  let outputPath = URL(fileURLWithPath: OUTPUT_PATH)
  try writePNG(image: output.decoded, url: outputPath)

  // Verify file exists
  let fileManager = FileManager.default
  if fileManager.fileExists(atPath: OUTPUT_PATH) {
    let attrs = try fileManager.attributesOfItem(atPath: OUTPUT_PATH)
    if let fileSize = attrs[.size] as? UInt64 {
      print("  File size: \(fileSize) bytes")
    }

    // Get image dimensions from the file
    guard let source = CGImageSourceCreateWithURL(outputPath as CFURL, nil) else {
      throw NSError(domain: "MinimalHarnes", code: 8,
                    userInfo: [NSLocalizedDescriptionKey: "Failed to read back saved image"])
    }
    guard let cgImg = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
      throw NSError(domain: "MinimalHarnes", code: 9,
                    userInfo: [NSLocalizedDescriptionKey: "Failed to decode saved image"])
    }
    print("  Image dimensions: \(cgImg.width) x \(cgImg.height)")
  } else {
    throw NSError(domain: "MinimalHarnes", code: 10,
                  userInfo: [NSLocalizedDescriptionKey: "Output file not found after save"])
  }

  print("\n=== Generation complete ===")

} catch {
  print("ERROR: \(error.localizedDescription)")
  exit(1)
}
