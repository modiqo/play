import SwiftUI

struct RootView: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 14) {
                Brand().frame(width: 166, alignment: .leading)
                Rectangle().fill(Palette.line).frame(width: 1, height: 18)
                Text(model.onboarding ? "Setup" : model.page.title).font(.system(size: 12, weight: .semibold))
                Spacer(minLength: 8)
                AppearanceControl()
                Button { model.showSupport = true } label: { Label("Support", systemImage: "questionmark.circle") }
                Button { model.openURL("https://www.modiqo.ai/account") } label: { Label("Create an organization", systemImage: "person.2.badge.plus") }
                Button { model.refresh() } label: { Image(systemName: "arrow.clockwise") }.disabled(model.busy).help("Refresh setup").accessibilityLabel("Refresh setup")
            }.padding(.horizontal, 14).frame(height: 44).background(Palette.chrome)
            Divider().overlay(Palette.line)
            HStack(spacing: 0) {
                Group {
                    if model.onboarding { SetupSidebar() }
                    else { Sidebar() }
                }.frame(width: 194)
                Divider().overlay(Palette.line)
                VStack(spacing: 0) {
                    if model.busy {
                        HStack(spacing: 9) { ProgressView().controlSize(.small); Text(model.busyLabel).font(.system(size: 11)); Spacer() }
                            .padding(.horizontal, 18).padding(.vertical, 8).background(Palette.selection.opacity(0.5))
                    }
                    if let error = model.error {
                        MessageBanner(message: error, isError: true) { model.error = nil }
                        HStack(spacing: 8) {
                            Button("Copy support report") { model.copySupport() }
                            Button("Discord support ↗") { model.openDiscord() }
                            Button("View details") { model.showSupport = true }
                            if model.signInRequired { Button("Sign in again") { model.openSignIn() }.disabled(model.busy) }
                            Spacer()
                        }.padding(.horizontal, 18).padding(.bottom, 9).background(Palette.chrome)
                    }
                    if let notice = model.notice { MessageBanner(message: notice, isError: false) { model.notice = nil } }
                    ScrollView {
                        if model.onboarding { OnboardingView().frame(maxWidth: 660).padding(28).frame(maxWidth: .infinity, alignment: .topLeading) }
                        else {
                            Group {
                                switch model.page {
                                case .home: HomeView()
                                case .harnesses: HarnessesView()
                                case .search: SearchView()
                                case .organizations: OrganizationsView()
                                case .updates: UpdatesView()
                                }
                            }.padding(20).frame(maxWidth: .infinity, alignment: .topLeading)
                        }
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity).background(Palette.paper)
            }
            Divider().overlay(Palette.line)
            HStack(spacing: 8) {
                Circle().fill(model.busy ? Palette.accent : Palette.secondary).frame(width: 5, height: 5)
                Text(model.busy ? model.busyLabel : "\(model.installed.count) harness integrations").lineLimit(1)
                Spacer()
                Text("Play \(model.snapshot?.playVersion.isEmpty == false ? model.snapshot!.playVersion : "—")")
                Divider().frame(height: 11)
                Text(model.snapshot?.roteVersion.isEmpty == false ? model.snapshot!.roteVersion : "Rote —")
                Divider().frame(height: 11)
                Text(model.snapshot?.architecture ?? "Mac")
            }.font(.system(size: 10, design: .monospaced)).foregroundStyle(Palette.secondary)
                .padding(.horizontal, 12).frame(height: 25).background(Palette.chrome)
        }.background(Palette.paper).foregroundStyle(Palette.text).font(.system(size: 12))
            .buttonStyle(UtilityButtonStyle()).tint(Palette.accent)
            .sheet(item: $model.plan) { PlanSheet(plan: $0).environmentObject(model).buttonStyle(UtilityButtonStyle()).preferredColorScheme(model.scheme) }
            .sheet(item: $model.selectedPlay) { PlayDetail(play: $0).environmentObject(model).buttonStyle(UtilityButtonStyle()).preferredColorScheme(model.scheme) }
            .sheet(isPresented: $model.showSupport) { SupportView().environmentObject(model).buttonStyle(UtilityButtonStyle()).preferredColorScheme(model.scheme) }
            .alert("Prepare Rote on this Mac?", isPresented: $model.confirmPrepare) {
                Button("Prepare Rote") { model.prepare() }
                Button("Cancel", role: .cancel) {}
            } message: { Text("Play installs missing Rote through getrote.dev, or updates an older Rote to support email sign-in. This changes your local Rote installation. Updates are forward-only.") }
    }
}

struct MessageBanner: View {
    var message: String; var isError: Bool; var dismiss: () -> Void
    var body: some View {
        HStack(alignment: .top, spacing: 9) {
            Image(systemName: isError ? "exclamationmark.circle" : "info.circle").foregroundStyle(isError ? Palette.orange : Palette.accent)
            Text(message).font(.system(size: 12)).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            Button(action: dismiss) { Image(systemName: "xmark") }.buttonStyle(.plain).accessibilityLabel("Dismiss message")
        }.padding(.horizontal, 18).padding(.vertical, 10).background(Palette.chrome)
            .overlay(alignment: .leading) { Rectangle().fill(isError ? Palette.orange : Palette.accent).frame(width: 2) }
    }
}

struct Sidebar: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 17) {
            VStack(spacing: 2) { ForEach([Page.home, .search, .harnesses]) { nav($0) } }
            section("Browse") {
                web("Community", "square.grid.2x2", "/feed")
                web("Playmakers", "person.2", "/profiles")
                web("Trending", "chart.line.uptrend.xyaxis", "/trending")
                web("Documentation", "book", "/docs")
            }
            section("Manage") { nav(.organizations); nav(.updates) }
            Spacer(minLength: 14)
            Button { model.openDiscord() } label: { row("Discord support", "bubble.left.and.bubble.right", external: true) }.buttonStyle(.plain)
            Divider().overlay(Palette.line)
            if model.signedIn {
                Button { model.openSignIn() } label: {
                    HStack(spacing: 9) {
                        Image(systemName: "person.crop.circle").font(.system(size: 18)).foregroundStyle(Palette.secondary)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(model.snapshot?.identity.email ?? "Account").font(.system(size: 11)).lineLimit(1).truncationMode(.middle)
                            Text("Account settings").font(.system(size: 10)).foregroundStyle(Palette.secondary)
                        }
                        Spacer(minLength: 0)
                    }.padding(.horizontal, 5).padding(.vertical, 4)
                }.buttonStyle(.plain).disabled(model.busy).help("Sign in or switch account")
            }
        }.padding(.horizontal, 8).padding(.top, 14).padding(.bottom, 12).background(Palette.sidebar)
    }
    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.system(size: 10, weight: .medium)).foregroundStyle(Palette.secondary).padding(.horizontal, 10).padding(.bottom, 2)
            content()
        }
    }
    private func row(_ title: String, _ symbol: String, external: Bool = false) -> some View {
        HStack(spacing: 9) {
            Image(systemName: symbol).font(.system(size: 12)).frame(width: 16).foregroundStyle(Palette.secondary)
            Text(title).font(.system(size: 12)); Spacer(minLength: 0)
            if external { Image(systemName: "arrow.up.right").font(.system(size: 9)).foregroundStyle(Palette.secondary) }
        }.padding(.horizontal, 10).frame(height: 30).contentShape(Rectangle())
    }
    private func nav(_ page: Page) -> some View {
        Button { model.page = page; model.error = nil; if page == .organizations { model.loadOrganizations() } } label: {
            HStack(spacing: 9) {
                Image(systemName: page.symbol).font(.system(size: 12)).frame(width: 16)
                Text(page.title).font(.system(size: 12)); Spacer(minLength: 0)
                if page == .harnesses { Text("\(model.installed.count)").font(.system(size: 10, design: .monospaced)).foregroundStyle(Palette.secondary) }
            }.padding(.horizontal, 10).frame(height: 30)
                .foregroundStyle(model.page == page ? Palette.accent : Palette.text)
                .background(model.page == page ? Palette.selection : .clear, in: RoundedRectangle(cornerRadius: 3))
                .contentShape(Rectangle())
        }.buttonStyle(.plain).disabled(model.busy)
    }
    private func web(_ title: String, _ symbol: String, _ path: String) -> some View {
        Button { model.openURL("https://www.modiqo.ai\(path)") } label: { row(title, symbol, external: true) }.buttonStyle(.plain)
    }
}
