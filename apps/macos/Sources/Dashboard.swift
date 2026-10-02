import SwiftUI

struct CopyButton: View {
    @EnvironmentObject var model: AppModel
    var value: String; var compact = false
    var body: some View {
        Button { model.copy(value) } label: {
            HStack(spacing: 8) {
                Text(compact ? "Copy" : value).font(.system(size: 11, design: compact ? .default : .monospaced)).lineLimit(1)
                Image(systemName: "doc.on.doc").font(.system(size: 10)).foregroundStyle(Palette.secondary)
            }.padding(.horizontal, 8).padding(.vertical, 5).background(Palette.chrome)
                .overlay(RoundedRectangle(cornerRadius: 3).strokeBorder(Palette.line))
        }.buttonStyle(.plain).help("Copy \(value)")
    }
}

struct HarnessTile: View {
    @EnvironmentObject var model: AppModel
    var harness: Harness
    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: harness.symbol).font(.system(size: 13)).foregroundStyle(Palette.secondary).frame(width: 18)
            Text(harness.name).font(.system(size: 12)).frame(maxWidth: .infinity, alignment: .leading)
            Image(systemName: "pin.fill").font(.system(size: 9)).foregroundStyle(Palette.accent).opacity(model.preferred == harness.id ? 1 : 0).frame(width: 10).help(model.preferred == harness.id ? "Preferred harness" : "")
            Text(harness.version.isEmpty ? "Detected" : harness.version).font(.system(size: 11, design: .monospaced)).foregroundStyle(Palette.secondary).lineLimit(1).truncationMode(.middle).frame(width: 172, alignment: .leading).help(harness.version)
            Text(harness.entry).font(.system(size: 11, design: .monospaced)).foregroundStyle(Palette.secondary).frame(width: 100, alignment: .leading)
            Button("Open ↗") { model.launch(harness) }.disabled(model.busy || !harness.commandAvailable)
        }.padding(.horizontal, 12).frame(minHeight: 36)
    }
}

struct HarnessTable: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        Panel {
            VStack(spacing: 0) {
                HStack(spacing: 10) {
                    Text("Application").frame(maxWidth: .infinity, alignment: .leading)
                    Text("Play version").frame(width: 172, alignment: .leading)
                    Text("Command").frame(width: 100, alignment: .leading)
                    Text(" ").frame(width: 58)
                }.font(.system(size: 11)).foregroundStyle(Palette.secondary).padding(.horizontal, 12).frame(height: 27).background(Palette.chrome)
                Divider().overlay(Palette.line)
                if model.installed.isEmpty { Text("No Play integrations detected.").foregroundStyle(Palette.secondary).frame(maxWidth: .infinity, alignment: .leading).padding(14) }
                ForEach(Array(model.installed.enumerated()), id: \.element.id) { index, harness in
                    HarnessTile(harness: harness).background(index.isMultiple(of: 2) ? Palette.card : Palette.alternate)
                    if index < model.installed.count - 1 { Divider().overlay(Palette.line.opacity(0.65)) }
                }
            }
        }
    }
}

struct HomeView: View {
    @EnvironmentObject var model: AppModel
    private let guide = [("Start a conversation", "Open a fresh conversation in your harness.", ""), ("What’s new", "New community Plays, in a short list.", "what's new"), ("Run a first Play", "Try Hello before running your own work.", "run Hello"), ("Explore a task", "Describe what you want to accomplish.", "explore")]
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .top) {
                PageHeading(eyebrow: "", title: "Overview", subtitle: "Your local Play installation and quick-start commands.")
                Button("Check for updates") { model.page = .updates; model.checkUpdates() }.disabled(model.busy)
            }
            Panel {
                HStack(spacing: 0) {
                    metric("Play", model.snapshot?.playVersion.isEmpty == false ? model.snapshot!.playVersion : "—", "Installed version")
                    Divider().overlay(Palette.line)
                    metric("Rote", (model.snapshot?.roteVersion ?? "—").replacingOccurrences(of: "rote ", with: ""), "Installed version")
                    Divider().overlay(Palette.line)
                    metric("Harnesses", String(model.installed.count), "With Play installed")
                    Divider().overlay(Palette.line)
                    metric("Architecture", model.snapshot?.architecture == "arm64" ? "Apple Silicon" : model.snapshot?.architecture == "x86_64" ? "Intel" : "—", "This Mac")
                }.frame(height: 83)
            }
            if let report = model.report, !report.successful {
                Panel {
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: "exclamationmark.circle").foregroundStyle(Palette.orange).padding(.top, 2)
                        VStack(alignment: .leading, spacing: 5) {
                            Text(report.rolledBack == true ? "Previous setup restored" : "Installation needs attention").font(.system(size: 12, weight: .medium))
                            ForEach(Array((report.issues ?? []).enumerated()), id: \.offset) { _, issue in Text(issue.reason).font(.system(size: 11)).foregroundStyle(Palette.secondary) }
                        }
                        Spacer(minLength: 8)
                        Button("Details & support") { model.showSupport = true }
                        Button("Review setup") { model.openSetup() }.disabled(model.busy)
                    }.padding(12)
                }
            }
            VStack(spacing: 8) {
                HStack { SectionLabel(title: "Installed harnesses", detail: String(model.installed.count)); Button("Manage") { model.page = .harnesses }.disabled(model.busy) }
                HarnessTable()
                if model.installed.isEmpty { Button("Set up Play") { model.openSetup() }.buttonStyle(UtilityButtonStyle(prominent: true)) }
            }
            VStack(spacing: 8) {
                HStack {
                    SectionLabel(title: "Quick start")
                    if !model.installed.isEmpty { Picker("Harness", selection: $model.preferred) { ForEach(model.installed) { Text($0.name).tag($0.id) } }.labelsHidden().frame(width: 140) }
                }
                Panel {
                    VStack(spacing: 0) {
                        ForEach(guide.indices, id: \.self) { index in
                            HStack(spacing: 12) {
                                Text(String(format: "%02d", index + 1)).font(.system(size: 11, design: .monospaced)).foregroundStyle(Palette.secondary).frame(width: 22)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(guide[index].0).font(.system(size: 12, weight: .medium))
                                    Text(guide[index].1).font(.system(size: 11)).foregroundStyle(Palette.secondary)
                                }
                                Spacer(); CopyButton(value: model.entry + (guide[index].2.isEmpty ? "" : " " + guide[index].2))
                            }.padding(.horizontal, 12).padding(.vertical, 9)
                            if index < guide.count - 1 { Divider().overlay(Palette.line) }
                        }
                    }
                }
            }
            VStack(alignment: .leading, spacing: 8) {
                SectionLabel(title: "Explore examples", detail: model.entry + " explore")
                LazyVGrid(columns: [GridItem(.flexible(), alignment: .top), GridItem(.flexible(), alignment: .top)], alignment: .leading, spacing: 10) {
                    ForEach(model.examples) { example in
                        Card {
                            VStack(alignment: .leading, spacing: 10) {
                                HStack { Text(example.tools).font(.system(size: 10, design: .monospaced)).foregroundStyle(Palette.secondary); Spacer(); CopyButton(value: model.entry + " explore " + example.prompt, compact: true) }
                                Text(example.title).font(.system(size: 13, weight: .semibold))
                                Text(example.prompt).font(.system(size: 12)).foregroundStyle(Palette.secondary).lineSpacing(3).fixedSize(horizontal: false, vertical: true)
                            }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                        }
                    }
                }
            }
            HStack {
                Button("Search published Plays") { model.page = .search }
                Button("Trending ↗") { model.openURL("https://www.modiqo.ai/trending") }
                Spacer()
                Button("Playoffs guide ↗") { model.openURL("https://www.modiqo.ai/blog/the-playoffs") }
            }
        }
    }
    private func metric(_ title: String, _ value: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 11)).foregroundStyle(Palette.secondary)
            Text(value).font(.system(size: title == "Architecture" ? 16 : 19, weight: .medium, design: .monospaced)).lineLimit(1).minimumScaleFactor(0.8)
            Text(detail).font(.system(size: 10)).foregroundStyle(Palette.secondary)
        }.padding(.horizontal, 14).frame(maxWidth: .infinity, alignment: .leading)
    }
}
