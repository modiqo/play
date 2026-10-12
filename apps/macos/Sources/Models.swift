import Foundation

struct Identity: Decodable {
    var state: String
    var email: String
    var userID: String
    var signedIn: Bool { state == "authenticated" }
}
struct Harness: Decodable, Identifiable {
    var id: String
    var name: String
    var detected: Bool
    var installed: Bool
    var version: String
    var entry: String
    var commandAvailable: Bool
    var selected: Bool
    var symbol: String {
        switch id { case "claude": return "sparkle"; case "codex": return "diamond.fill"
        case "cursor": return "cursorarrow"; case "kimi": return "circle.fill"
        default: return "terminal" }
    }
}
struct InstallReport: Decodable {
    var status: String
    var runID: String
    var reportPath: String
    var harnesses: [String]
    var version: String
    var backupAvailable: Bool
    var failures: [String]
    var issues: [InstallIssue]?
    var rolledBack: Bool?
    var successful: Bool { status == "completed" }
}
struct InstallIssue: Decodable { var step: String; var reason: String }
struct Snapshot: Decodable {
    var playVersion: String
    var bundledVersion: String
    var roteVersion: String
    var roteInstalled: Bool
    var roteReady: Bool
    var identity: Identity
    var harnesses: [Harness]
    var architecture: String
    var interrupted: Bool
    var lastReport: InstallReport?
}
struct Organization: Decodable, Identifiable {
    var id: String
    var slug: String
    var name: String
    var owned: Bool
    var role: String
}
struct OrganizationResponse: Decodable { var organizations: [Organization] }
struct ReleaseInfo: Decodable {
    var version: String
    var installedVersion: String
    var available: Bool
    var roteStatus: String
    var releaseURL: String
    var needsUpdate: Bool { available || roteStatus == "available" || roteStatus == "not_installed" }
}
struct InstallPlan: Decodable, Identifiable {
    var id: String
    var version: String
    var installedVersion: String
    var roteVersion: String
    var roteAction: String
    var harnesses: [String]
    var actions: [String]
    var note: String
}
struct PlayResult: Decodable, Identifiable {
    var id: String
    var title: String
    var description: String
    var reference: String
    var url: String
    var groupID: String
    var groupLabel: String
    var groupKind: String
    var relevance: String
    var visibility: String
}
struct SearchResponse: Decodable { var complete: Bool; var results: [PlayResult] }
struct ProgressEvent: Identifiable {
    var id: String { label }
    var label: String
    var state: String
}
struct Invitation: Identifiable {
    let id = UUID()
    var email: String
    var role: String
    var status = "Waiting"
}
struct ExamplePrompt: Decodable, Identifiable {
    var id: String { title }
    var title: String
    var tools: String
    var prompt: String
}
enum Page: String, CaseIterable, Identifiable {
    case home, search, harnesses, organizations, updates
    var id: String { rawValue }
    var title: String {
        switch self { case .home: return "Home"; case .search: return "Search Plays"
        case .harnesses: return "Your harnesses"; case .organizations: return "Organizations"
        case .updates: return "Updates" }
    }
    var symbol: String {
        switch self { case .home: return "house"; case .search: return "magnifyingglass"
        case .harnesses: return "desktopcomputer"; case .organizations: return "folder"
        case .updates: return "arrow.triangle.2.circlepath" }
    }
}
struct BridgeError: LocalizedError {
    var message: String
    var code: String = "operation"
    var errorDescription: String? { message }
}
