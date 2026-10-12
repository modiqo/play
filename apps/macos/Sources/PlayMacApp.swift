import AppKit
import SwiftUI

@main struct PlayMacApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel()
    var body: some Scene {
        WindowGroup("Play for Mac", id: "main") {
            RootView().environmentObject(model).preferredColorScheme(model.scheme)
                .frame(minWidth: 960, minHeight: 680)
                .task { model.refresh(initial: true) }
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1180, height: 830)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandMenu("Play") {
                Button("Search Plays") { if model.signedIn { model.onboarding = false; model.page = .search } }
                    .keyboardShortcut("k").disabled(model.busy || !model.signedIn)
                Button("Refresh setup") { model.refresh() }.keyboardShortcut("r").disabled(model.busy)
                Button("Check for updates") { model.onboarding = false; model.page = .updates; model.checkUpdates() }.disabled(model.busy)
                Divider()
                Button("Documentation") { model.openURL("https://www.modiqo.ai/docs") }
            }
        }
        Settings {
            Form {
                Picker("Appearance", selection: $model.appearance) {
                    Text("System").tag("system"); Text("Light").tag("light"); Text("Dark").tag("dark")
                }
                Text("Play uses your existing Rote sign-in. Credentials remain in Rote’s private storage.")
                    .font(.caption).foregroundStyle(.secondary)
                Text("Play for Mac · \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.1.0")")
                    .font(.caption).foregroundStyle(.secondary)
            }.padding(24).frame(width: 420).preferredColorScheme(model.scheme)
        }
    }
}
