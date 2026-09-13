// swift-tools-version: 6.0
import PackageDescription

let package = Package(
  name: "MinimalHarnes",
  platforms: [.macOS(.v14)],
  dependencies: [
    .package(url: "https://github.com/ml-explore/flux2.swift.git", revision: "e8caa12"),
  ],
  targets: [
    .executableTarget(
      name: "MinimalHarnes",
      dependencies: [
        .product(name: "Flux2", package: "flux2.swift")
      ]
    )
  ]
)
