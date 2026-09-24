import AppKit
import SwiftUI

@MainActor final class AppModel: ObservableObject {
    @Published var snapshot: Snapshot?
    @Published var page: Page = .home
    @Published var onboarding = true
    @Published var step = 0
    @Published var busy = false
    @Published var busyLabel = ""
    @Published var error: String?
    @Published var signInRequired = false
    @Published var notice: String?
    @Published var selected = Set<String>()
    @Published var organizations: [Organization] = []
    @Published var release: ReleaseInfo?
    @Published var plan: InstallPlan?
    @Published var report: InstallReport?
    @Published var events: [ProgressEvent] = []
    @Published var email = ""
    @Published var code = ""
    @Published var codeSent = false
    @Published var resendAfter = Date.distantPast
    @Published var orgName = ""
    @Published var orgSlug = ""
    @Published var activeOrg = ""
    @Published var inviteEmail = ""
    @Published var inviteRole = "developer"
    @Published var invitations: [Invitation] = []
    @Published var query = ""
    @Published var searchScope = "all"
    @Published var searchOrg = ""
    @Published var results: SearchResponse?
    @Published var searchedQuery = ""
    @Published var selectedPlay: PlayResult?
    @Published var confirmPrepare = false
    @Published var showSupport = false
    @Published var preferred: String = UserDefaults.standard.string(forKey: "preferredHarness") ?? "claude" {
        didSet { UserDefaults.standard.set(preferred, forKey: "preferredHarness") }
    }
    @Published var appearance = UserDefaults.standard.string(forKey: "appearance") ?? "system" {
        didSet { UserDefaults.standard.set(appearance, forKey: "appearance") }
    }
    private let bridge = NativeBridge()
    private var loaded = false
    var installed: [Harness] { snapshot?.harnesses.filter(\.installed) ?? [] }
    var detected: [Harness] { snapshot?.harnesses.filter(\.detected) ?? [] }
    var currentHarness: Harness? { installed.first(where: { $0.id == preferred }) ?? installed.first ?? detected.first }
    var entry: String { currentHarness?.entry ?? "/play" }
    var signedIn: Bool { snapshot?.identity.signedIn == true }
    var targetVersion: String { release?.version ?? snapshot?.bundledVersion ?? "" }
    var scheme: ColorScheme? { appearance == "dark" ? .dark : appearance == "light" ? .light : nil }
    var examples: [ExamplePrompt] {
        guard let url = Bundle.main.url(forResource: "examples", withExtension: "json"),
              let data = try? Data(contentsOf: url), let values = try? JSONDecoder().decode([ExamplePrompt].self, from: data) else { return [] }
        return values
    }

    private func request<T: Decodable>(_ action: String, _ payload: [String: Any] = [:], as: T.Type = T.self) async throws -> T {
        let data = try await bridge.call(action, payload: payload) { [weak self] event in
            Task { @MainActor in
                guard let self else { return }
                self.busyLabel = event.label
                if let index = self.events.firstIndex(where: { $0.label == event.label }) { self.events[index] = event }
                else { self.events.append(event) }
            }
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
    private func raw(_ action: String, _ payload: [String: Any] = [:]) async throws {
        _ = try await bridge.call(action, payload: payload) { [weak self] event in
            Task { @MainActor in self?.busyLabel = event.label }
        }
    }
    func work(_ label: String, operation: @escaping () async throws -> Void) {
        guard !busy else { return }
        busy = true; busyLabel = label; error = nil; notice = nil; signInRequired = false
        Task {
            defer { busy = false; busyLabel = "" }
            do { try await operation() }
            catch { self.error = error.localizedDescription; self.signInRequired = (error as? BridgeError)?.code == "signin" }
        }
    }
    func refresh(initial: Bool = false) {
        if initial && loaded { return }
        loaded = true
        work("Checking your Mac") {
            let value: Snapshot = try await self.request("status")
            if self.snapshot?.identity.userID != value.identity.userID || !value.identity.signedIn { self.clearAccountViews() }
            self.snapshot = value
            self.report = value.lastReport
            self.email = value.identity.email
            if self.selected.isEmpty { self.selected = Set(value.harnesses.filter { $0.detected && ($0.installed || $0.selected) }.map(\.id)) }
            if initial { self.onboarding = !(value.identity.signedIn && value.harnesses.contains(where: \.installed)) }
            if value.interrupted { self.notice = "A previous installation was interrupted. Review setup to verify or repair it. Your recovery files remain available." }
            if value.identity.signedIn {
                do { self.organizations = try await self.request("organizations", as: OrganizationResponse.self).organizations }
                catch { self.notice = "Your Mac was checked, but organizations could not be loaded. You can retry from Organizations." }
            }
        }
    }
    func continueWelcome() {
        guard let snapshot else { refresh(); return }
        if !snapshot.roteReady { confirmPrepare = true }
        else { step = snapshot.identity.signedIn ? 2 : 1 }
    }
    func prepare() {
        confirmPrepare = false
        work("Preparing Rote") {
            AppRuntime.installing = true
            defer { AppRuntime.installing = false }
            try await self.raw("prepare", ["approved": true])
            self.snapshot = try await self.request("status")
            self.step = 1
        }
    }
    func signIn(_ provider: String) {
        work("Opening your browser") {
            let identity: Identity = try await self.request("login", ["provider": provider])
            self.clearAccountViews()
            self.snapshot?.identity = identity; self.email = identity.email; self.step = 2
            self.organizations = (try? await self.request("organizations", as: OrganizationResponse.self).organizations) ?? []
        }
    }
    func sendCode() {
        work("Sending your sign-in code") {
            try await self.raw("email", ["operation": "send", "email": self.email])
            self.codeSent = true; self.code = ""; self.resendAfter = Date().addingTimeInterval(60)
        }
    }
    func verifyCode() {
        work("Verifying your sign-in") {
            defer { self.code = "" }
            let identity: Identity = try await self.request("email", ["operation": "verify", "email": self.email, "code": self.code])
            self.clearAccountViews()
            self.snapshot?.identity = identity; self.step = 2
            self.organizations = (try? await self.request("organizations", as: OrganizationResponse.self).organizations) ?? []
        }
    }
    func createOrganization() {
        work("Creating your organization") {
            try await self.raw("create_org", ["slug": self.orgSlug, "name": self.orgName])
            self.invitations = []
            self.activeOrg = self.orgSlug; self.step = 3
            self.organizations = try await self.request("organizations", as: OrganizationResponse.self).organizations
        }
    }
    func addInvitation() {
        let value = inviteEmail.trimmingCharacters(in: .whitespacesAndNewlines)
        guard value.contains("@"), value.contains("."), !value.contains(" "), !invitations.contains(where: { $0.email.lowercased() == value.lowercased() }) else {
            error = "Enter a colleague’s email that is not already in the list."; return
        }
        invitations.append(Invitation(email: value, role: inviteRole)); inviteEmail = ""
    }
    func sendInvitations() {
        work("Sending invitations") {
            for index in self.invitations.indices where self.invitations[index].status != "Sent" {
                self.invitations[index].status = "Sending"
                do {
                    try await self.raw("invite", ["slug": self.activeOrg, "email": self.invitations[index].email, "role": self.invitations[index].role])
                    self.invitations[index].status = "Sent"
                } catch {
                    self.invitations[index].status = "Check account"
                    throw error
                }
            }
            self.step = 4
        }
    }
    func checkUpdates() {
        work("Checking Play and Rote releases") { self.release = try await self.request("updates") }
    }
    func reviewInstall(updateAll: Bool = false) {
        if !signedIn { onboarding = true; step = 1; return }
        if updateAll { selected = Set(installed.map(\.id)) }
        guard !selected.isEmpty else { error = "Choose at least one detected harness."; return }
        work("Preparing your installation plan") {
            self.release = try await self.request("updates")
            self.plan = try await self.request("plan", ["harnesses": Array(self.selected).sorted(), "version": self.targetVersion])
        }
    }
    func applyPlan() {
        guard let plan else { return }
        self.plan = nil; events = []; report = nil; onboarding = true; step = 5
        work("Starting installation") {
            AppRuntime.installing = true
            defer { AppRuntime.installing = false }
            let report: InstallReport = try await self.request("install", ["planID": plan.id, "approved": true])
            self.report = report
            if let updated: Snapshot = try? await self.request("status") { self.snapshot = updated }
            if report.successful {
                self.openHome(); self.release = nil
                self.notice = "Play is ready. Restart your harnesses to load the updated skills and hooks."
            } else if report.status == "rolled_back" && report.rolledBack == true {
                self.openHome()
                self.error = "Installation failed. Your previous Play setup was restored. Review the details or contact support."
            } else { self.error = "Setup needs attention. Review the receipt, then refresh and prepare a new plan." }
        }
    }
    func openHome() { onboarding = false; page = .home }
    func openSetup() { onboarding = true; step = 0; error = nil; notice = nil }
    func openSignIn() { onboarding = true; step = 1; error = nil; signInRequired = false; code = ""; codeSent = false }
    private func clearAccountViews() {
        organizations = []; results = nil; selectedPlay = nil; plan = nil
        invitations = []; activeOrg = ""; orgName = ""; orgSlug = ""; searchOrg = ""
    }
    func selectOrganization(_ org: Organization) {
        if activeOrg != org.slug { invitations = [] }
        activeOrg = org.slug; orgName = org.name; step = org.owned || org.role == "admin" ? 3 : 4
    }
    func copy(_ prompt: String) {
        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(prompt, forType: .string)
        notice = "Prompt copied. Paste it into a fresh harness conversation."
    }
    func launch(_ harness: Harness) {
        work("Opening \(harness.name)") { try await self.raw("launch", ["harness": harness.id]) }
    }
    func search() {
        guard !busy else { return }
        let submitted = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard submitted.count >= 2 else { return }
        results = nil; searchedQuery = submitted
        work("Searching published Plays") {
            self.results = try await self.request("search", ["query": submitted, "scope": self.searchScope, "org": self.searchOrg])
        }
    }
    func loadOrganizations() {
        work("Loading your organizations") { self.organizations = try await self.request("organizations", as: OrganizationResponse.self).organizations }
    }
    func openURL(_ url: String) {
        guard let value = URL(string: url), value.scheme == "https", let host = value.host,
              ["www.modiqo.ai", "modiqo.ai", "play.modiqo.ai", "play.staging.modiqo.ai", "github.com"].contains(host) else { return }
        NSWorkspace.shared.open(value)
    }
    func openReport() {
        guard let report else { return }
        NSWorkspace.shared.open(URL(fileURLWithPath: report.reportPath))
    }
    var supportText: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.1.0"
        var lines = ["Play for Mac support report", "App: \(version)", "macOS: \(ProcessInfo.processInfo.operatingSystemVersionString)",
                     "Architecture: \(snapshot?.architecture ?? "unknown")", "Play: \(snapshot?.playVersion ?? "unknown")",
                     "Rote: \(snapshot?.roteVersion ?? "unknown")"]
        if let report {
            lines += ["Installation: \(report.status)", "Run: \(report.runID)", "Target Play: \(report.version)",
                      "Harnesses: \(report.harnesses.joined(separator: ", "))", "Previous setup restored: \(report.rolledBack == true ? "yes" : "not confirmed")"]
            for issue in report.issues ?? [] { lines.append("\(issue.step): \(issue.reason)") }
        } else { lines.append(signInRequired ? "Issue: search service rejected sign-in (HTTP 401)." : error == nil ? "Issue: describe what happened here." : "Issue: operation could not finish.") }
        lines.append("Account details, credentials, raw logs, and local paths are omitted.")
        return lines.joined(separator: "\n")
    }
    func copySupport() {
        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(supportText, forType: .string)
        notice = "Support report copied. Review it, then paste it into Modiqo Discord."
    }
    func openDiscord() { NSWorkspace.shared.open(URL(string: "https://discord.gg/YyjBtzvhGz")!) }
}
