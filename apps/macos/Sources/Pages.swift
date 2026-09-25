import SwiftUI

struct SupportView: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            PageHeading(eyebrow: "We can help", title: "Support report", subtitle: "Copy this report and paste it into Modiqo Discord. Nothing is sent automatically.")
            ScrollView { Text(model.supportText).font(.system(size: 12, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(16) }.frame(height: 260).background(Palette.paper, in: RoundedRectangle(cornerRadius: 3))
            HStack {
                Button("Copy report") { model.copySupport() }.buttonStyle(UtilityButtonStyle(prominent: true))
                Button("Open Discord ↗") { model.openDiscord() }
                if model.report != nil { Button("Local receipt") { model.openReport() } }
                Spacer(); Button("Done") { model.showSupport = false }
            }
        }.padding(28).frame(width: 620)
    }
}

struct HarnessesView: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeading(eyebrow: "Your setup, at a glance", title: "Harnesses", subtitle: "See where Play is installed and choose your preferred harness.")
            HStack {
                SectionLabel(title: "Installed harnesses", detail: String(model.installed.count))
                Picker("Preferred", selection: $model.preferred) { ForEach(model.installed) { Text($0.name).tag($0.id) } }.frame(width: 230)
            }
            HarnessTable()
            HStack {
                Button("Manage installation") { model.onboarding = true; model.step = 4 }.buttonStyle(UtilityButtonStyle(prominent: true)).disabled(model.busy)
                Button("Check for updates") { model.page = .updates; model.checkUpdates() }.disabled(model.busy)
            }
            Divider()
            HStack(spacing: 30) {
                component("Play", model.snapshot?.playVersion ?? "Not installed")
                component("Rote", model.snapshot?.roteVersion ?? "Not installed")
                component("Architecture", model.snapshot?.architecture == "arm64" ? "Apple Silicon" : "Intel")
            }
            Text("Detected means the Play files or marketplace registration are present. Setup verifies each selected integration and writes a receipt.").font(.system(size: 11)).foregroundStyle(.secondary)
        }
    }
    private func component(_ title: String, _ value: String) -> some View { VStack(alignment: .leading, spacing: 7) { Text(title).font(.system(size: 10)).foregroundStyle(.secondary); Text(value.isEmpty ? "Not installed" : value).font(.system(size: 12)) } }
}
struct UpdatesView: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeading(eyebrow: "Keep your setup in step", title: "Updates", subtitle: "One reviewed update keeps Play, Rote, and your installed harness integrations together.")
            Card {
                HStack(spacing: 22) {
                    Image(systemName: "arrow.down.circle").font(.system(size: 20)).foregroundStyle(Palette.orange)
                    VStack(alignment: .leading, spacing: 9) {
                        Text(model.release.map { "Play \($0.version)" } ?? "Check the latest release").font(.system(size: 18, weight: .semibold))
                        Text(model.release.map { "Rote update status: \($0.roteStatus.replacingOccurrences(of: "_", with: " "))" } ?? "Check Play and Rote before preparing your update.").font(.system(size: 12)).foregroundStyle(.secondary)
                    }; Spacer()
                }
            }
            Card {
                VStack(spacing: 14) {
                    row("Installed Play", model.snapshot?.playVersion.isEmpty == false ? model.snapshot!.playVersion : "Not installed")
                    Divider(); row("Installed Rote", model.snapshot?.roteVersion.isEmpty == false ? model.snapshot!.roteVersion : "Not installed")
                    Divider(); row("Harness integrations", model.installed.map(\.name).joined(separator: ", "))
                }
            }
            HStack {
                Button("Check for updates") { model.checkUpdates() }.disabled(model.busy)
                if model.release != nil {
                    Button("Review Play + Rote update") { model.reviewInstall(updateAll: true) }.buttonStyle(UtilityButtonStyle(prominent: true)).disabled(model.busy || model.installed.isEmpty)
                    Button("Release notes ↗") { if let release = model.release { model.openURL(release.releaseURL) } }.buttonStyle(.plain).font(.system(size: 11))
                }
            }
            Text("Play configuration is backed up before replacement and restored if verification fails. Rote updates are forward-only. Newer installed Play releases are never silently downgraded.").font(.system(size: 12)).foregroundStyle(.secondary).lineSpacing(4)
            Text("This updates the Play and Rote installation. Updates to the Mac application itself are distributed as a new app download.").font(.system(size: 11)).foregroundStyle(.secondary)
        }
    }
    private func row(_ label: String, _ value: String) -> some View { HStack { Text(label); Spacer(); Text(value).foregroundStyle(.secondary).multilineTextAlignment(.trailing) }.font(.system(size: 12)) }
}
struct OrganizationsView: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeading(eyebrow: "Better together", title: "Organizations", subtitle: "Keep company Plays private and share the work with your team.")
            group("Organizations you own", organizations: model.organizations.filter(\.owned))
            group("Organizations you’ve joined", organizations: model.organizations.filter { !$0.owned })
            HStack {
                Button("Create an organization ↗") { model.openURL("https://www.modiqo.ai/account") }.buttonStyle(UtilityButtonStyle(prominent: true))
                Button("Refresh organizations") { model.loadOrganizations() }.disabled(model.busy)
            }
            Text("Only published Plays join search. Organization access is checked by the registry and the shared search service.").font(.system(size: 11)).foregroundStyle(.secondary)
        }
    }
    private func group(_ title: String, organizations: [Organization]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(.system(size: 12, weight: .semibold)).foregroundStyle(.secondary)
            if organizations.isEmpty { Text("No organizations in this group.").font(.system(size: 12)).foregroundStyle(.secondary).padding(.vertical, 10) }
            ForEach(organizations) { org in
                Card {
                    HStack(spacing: 13) {
                        Text(String(org.name.prefix(2)).uppercased()).font(.system(size: 12, weight: .semibold)) .frame(width: 28, height: 28).background(Palette.chrome, in: RoundedRectangle(cornerRadius: 3))
                        VStack(alignment: .leading, spacing: 5) { Text(org.name).font(.system(size: 14, weight: .medium)); Text("@\(org.slug) · \(org.owned ? "Owner" : org.role.capitalized)").font(.system(size: 11)).foregroundStyle(.secondary) }
                        Spacer()
                        Button("Find Plays") { model.searchScope = "org"; model.searchOrg = org.slug; model.results = nil; model.page = .search }.controlSize(.small).disabled(model.busy)
                        Button("Manage ↗") { model.openURL("https://www.modiqo.ai/account") }.controlSize(.small)
                    }
                }
            }
        }
    }
}
struct SearchView: View {
    @EnvironmentObject var model: AppModel
    @FocusState private var searchFocused: Bool
    private var groups: [String] { var seen = Set<String>(); return (model.results?.results ?? []).compactMap { seen.insert($0.groupID).inserted ? $0.groupID : nil } }
    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            PageHeading(eyebrow: "A good place to start", title: "Search Plays", subtitle: "Search published Plays from your organizations and the community.")
            HStack(spacing: 12) {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                TextField("Try “review a pull request”", text: $model.query).textFieldStyle(.plain).focused($searchFocused).onSubmit { model.search() }
                Button("Search") { model.search() }.buttonStyle(UtilityButtonStyle(prominent: true)).disabled(model.busy || model.query.trimmingCharacters(in: .whitespaces).count < 2)
            }.padding(14).background(Palette.card, in: RoundedRectangle(cornerRadius: 3)).overlay(RoundedRectangle(cornerRadius: 3).stroke(Palette.line))
            HStack(spacing: 12) {
                Picker("Scope", selection: $model.searchScope) {
                    Text("Everything").tag("all"); Text("Community").tag("community"); Text("My Plays").tag("personal"); Text("My organizations").tag("organizations"); Text("Specific organization").tag("org")
                }.labelsHidden().frame(width: 180)
                if model.searchScope == "org" {
                    Picker("Organization", selection: $model.searchOrg) { Text("Choose organization").tag(""); ForEach(model.organizations) { Text($0.name).tag($0.slug) } }.labelsHidden().frame(width: 210)
                }
                Spacer()
            }.disabled(model.busy).onChange(of: model.searchScope) { _ in model.results = nil }.onChange(of: model.searchOrg) { _ in model.results = nil }
            if let response = model.results {
                if !response.complete {
                    Label("Some sources or relevance checks are incomplete. Treat uncertain results as suggestions, not confirmed matches.", systemImage: "exclamationmark.circle").font(.system(size: 12)).foregroundStyle(Palette.orange).fixedSize(horizontal: false, vertical: true)
                }
                Text("Results for “\(model.searchedQuery)” · \(response.results.count) published Plays").font(.system(size: 11)).foregroundStyle(.secondary)
                if response.results.isEmpty {
                    VStack(spacing: 13) { Image(systemName: "magnifyingglass").font(.system(size: 30)).foregroundStyle(.secondary); Text("No matching Plays returned.").font(.system(size: 18, weight: .medium)); Text("Try a shorter phrase or another scope.").font(.system(size: 12)).foregroundStyle(.secondary) }.frame(maxWidth: .infinity).padding(45)
                }
                ForEach(groups, id: \.self) { groupID in
                    let rows = response.results.filter { $0.groupID == groupID }
                    VStack(alignment: .leading, spacing: 12) {
                        Text(rows.first?.groupLabel ?? "Published Plays").font(.system(size: 13, weight: .semibold))
                        ForEach(rows) { play in
                            Button { model.selectedPlay = play } label: {
                                Card {
                                    HStack(spacing: 15) {
                                        Image(systemName: "play.rectangle").font(.system(size: 16)).foregroundStyle(Palette.green)
                                        VStack(alignment: .leading, spacing: 6) { Text(play.title).font(.system(size: 13, weight: .medium)); Text(play.description).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(3) }
                                        Spacer(minLength: 12)
                                        VStack(alignment: .trailing, spacing: 5) { Text(play.visibility.capitalized); Text(play.relevance.capitalized).foregroundStyle(["uncertain", "unverified"].contains(play.relevance) ? Palette.orange : Palette.green) }.font(.system(size: 10))
                                        Image(systemName: "chevron.right").font(.system(size: 10)).foregroundStyle(.secondary)
                                    }
                                }
                            }.buttonStyle(.plain)
                        }
                    }
                }
            } else if !model.busy {
                Text("Search runs through the shared Play search service. Unpublished local Plays are not indexed.").font(.system(size: 12)).foregroundStyle(.secondary).padding(.top, 20)
            }
        }.onAppear { searchFocused = true }
    }
}
struct PlayDetail: View {
    @EnvironmentObject var model: AppModel
    var play: PlayResult
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack { Eyebrow(text: "\(play.groupLabel) · \(play.visibility)"); Spacer(); Button { model.selectedPlay = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain) }
            Text(play.title).font(.system(size: 20, weight: .semibold))
            Text(play.description).font(.system(size: 13)).foregroundStyle(.secondary).lineSpacing(4)
            Text(play.reference).font(.system(size: 11, design: .monospaced)).textSelection(.enabled)
            Label("Relevance: \(play.relevance)", systemImage: "info.circle").font(.system(size: 11)).foregroundStyle(.secondary)
            CopyButton(value: model.entry + " inspect " + play.reference)
            Text("Inspect the published Play before running it. Copying a prompt does not run a Play.").font(.system(size: 11)).foregroundStyle(.secondary)
            HStack { Button("Open published Play ↗") { model.openURL(play.url) }; Spacer(); Button("Done") { model.selectedPlay = nil }.buttonStyle(UtilityButtonStyle(prominent: true)) }
        }.padding(30).frame(width: 520)
    }
}
