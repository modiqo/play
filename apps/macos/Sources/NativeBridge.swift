import AppKit
import Foundation

final class NativeBridge: Sendable {
    let resources: URL
    init() { resources = Bundle.main.resourceURL! }

    func call(_ action: String, payload: [String: Any] = [:], progress: @escaping (ProgressEvent) -> Void) async throws -> Data {
        #if arch(arm64)
        let architecture = "arm64"
        #else
        let architecture = "x86_64"
        #endif
        let runtime = resources.appendingPathComponent("runtime/\(architecture)")
        let python = runtime.appendingPathComponent("python/bin/python3")
        let inputData = try JSONSerialization.data(withJSONObject: payload)
        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process()
                process.executableURL = python
                process.arguments = ["-B", self.resources.appendingPathComponent("backend.py").path,
                                     self.resources.appendingPathComponent("play-source").path, action]
                var environment = ProcessInfo.processInfo.environment
                environment["PATH"] = runtime.appendingPathComponent("bin").path + ":" + python.deletingLastPathComponent().path + ":" + (environment["PATH"] ?? "/usr/bin:/bin")
                environment["PLAY_DESKTOP_RUNTIME"] = runtime.path
                environment["PYTHONUNBUFFERED"] = "1"
                environment["PYTHONDONTWRITEBYTECODE"] = "1"
                // Never inherit a virtual environment or Python import path from a development shell.
                environment.removeValue(forKey: "PYTHONHOME")
                environment.removeValue(forKey: "PYTHONPATH")
                environment.removeValue(forKey: "VIRTUAL_ENV")
                process.environment = environment
                process.currentDirectoryURL = FileManager.default.homeDirectoryForCurrentUser
                let input = Pipe(), output = Pipe()
                process.standardInput = input
                process.standardOutput = output
                process.standardError = FileHandle.nullDevice
                var response: Data?
                var failure: String?
                var failureCode = "operation"
                func consume(_ line: Data) {
                    guard let event = try? JSONSerialization.jsonObject(with: line) as? [String: Any], let type = event["type"] as? String else { return }
                    if type == "progress", let label = event["label"] as? String {
                        progress(ProgressEvent(label: label, state: event["state"] as? String ?? "running"))
                    } else if type == "result", let value = event["data"] {
                        response = try? JSONSerialization.data(withJSONObject: value)
                    } else if type == "error" { failure = event["message"] as? String; failureCode = event["code"] as? String ?? "operation" }
                }
                do {
                    try process.run()
                    try input.fileHandleForWriting.write(contentsOf: inputData)
                    try input.fileHandleForWriting.close()
                    var pending = Data()
                    while true {
                        let chunk = output.fileHandleForReading.availableData
                        if chunk.isEmpty { break }
                        pending.append(chunk)
                        // A malformed bridge cannot allocate an unbounded UI response.
                        if pending.count > 4_194_304 {
                            process.terminate()
                            throw BridgeError(message: "The local bridge returned too much data.")
                        }
                        while let newline = pending.firstIndex(of: 10) {
                            consume(pending.subdata(in: 0..<newline))
                            pending.removeSubrange(0...newline)
                        }
                    }
                    if !pending.isEmpty { consume(pending) }
                    process.waitUntilExit()
                    if let failure { throw BridgeError(message: failure, code: failureCode) }
                    guard process.terminationStatus == 0, let response else {
                        throw BridgeError(message: "The local Play service stopped unexpectedly. Refresh and try again.")
                    }
                    continuation.resume(returning: response)
                } catch {
                    if process.isRunning { process.terminate() }
                    continuation.resume(throwing: error)
                }
            }
        }
    }
}

@MainActor enum AppRuntime { static var installing = false }

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if AppRuntime.installing {
            let alert = NSAlert()
            alert.messageText = "Setup is still running"
            alert.informativeText = "Keep Play open until installation or recovery finishes. This protects your harness configuration."
            alert.addButton(withTitle: "Keep running")
            alert.runModal()
            return .terminateCancel
        }
        return .terminateNow
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { sender.windows.first?.makeKeyAndOrderFront(nil) }
        return true
    }
}
