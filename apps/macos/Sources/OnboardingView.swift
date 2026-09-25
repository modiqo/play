import SwiftUI

struct SetupSidebar: View {
    @EnvironmentObject var model: AppModel
    let labels = ["Welcome", "Account", "Organization", "Invite colleagues", "Harnesses", "Install & verify"]
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Setup").font(.system(size: 10, weight: .medium)).foregroundStyle(Palette.secondary).padding(.horizontal, 10)
            VStack(spacing: 3) {
                ForEach(labels.indices, id: \.self) { index in
                    HStack(spacing: 10) {
                        ZStack {
                            RoundedRectangle(cornerRadius: 3).strokeBorder(Palette.line).frame(width: 22, height: 22)
                            if index < model.step { Image(systemName: "checkmark").font(.system(size: 10)).foregroundStyle(Palette.green) }
                            else { Text(String(index + 1)).font(.system(size: 10, design: .monospaced)) }
                        }
                        Text(labels[index]).font(.system(size: 12, weight: index == model.step ? .medium : .regular))
                        Spacer(minLength: 0)
                    }.foregroundStyle(index == model.step ? Palette.accent : Palette.secondary)
                        .padding(.horizontal, 8).frame(height: 34)
                        .background(index == model.step ? Palette.selection : .clear, in: RoundedRectangle(cornerRadius: 3))
                }
            }
            Spacer()
            Divider().overlay(Palette.line)
            Text("Review changes before installing.").font(.system(size: 11)).foregroundStyle(Palette.secondary).padding(.horizontal, 8)
            if model.signedIn && !model.installed.isEmpty { Button("Back to Home") { model.openHome() }.disabled(model.busy).padding(.horizontal, 8) }
        }.padding(.horizontal, 8).padding(.vertical, 16).background(Palette.sidebar)
    }
}
struct OnboardingView: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Group {
                switch model.step {
                case 0: welcome
                case 1: account
                case 2: organization
                case 3: invitations
                case 4: harnesses
                case 5: installation
                default: completion
                }
            }
            if model.step > 0 && model.step < 5 {
                Divider()
                Button("← Back") { model.step = model.step == 4 && model.activeOrg.isEmpty ? 2 : model.step - 1; model.error = nil }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.secondary).disabled(model.busy)
            }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
    private func primary(_ title: String, disabled: Bool = false, action: @escaping () -> Void) -> some View {
        Button(title, action: action).buttonStyle(UtilityButtonStyle(prominent: true)).disabled(model.busy || disabled)
    }
    private func field(_ label: String, placeholder: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 9) { Text(label).font(.system(size: 12, weight: .medium)); TextField(placeholder, text: text).textFieldStyle(.roundedBorder).controlSize(.regular).disabled(model.busy) }
    }
    private func note(_ text: String, symbol: String = "info.circle") -> some View {
        HStack(alignment: .top, spacing: 10) { Image(systemName: symbol).foregroundStyle(Palette.green); Text(text).font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true).lineSpacing(4) }.padding(12).frame(maxWidth: .infinity, alignment: .leading).background(Palette.chrome).overlay(Rectangle().strokeBorder(Palette.line))
    }
    private var welcome: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeading(eyebrow: "A home for your next Play", title: "Set up Play", subtitle: "Set up Play in the tools you already use. Then find, run, and share Plays with your team.")
            if let snapshot = model.snapshot {
                Card {
                    VStack(alignment: .leading, spacing: 10) {
                        Label(snapshot.roteInstalled || !snapshot.playVersion.isEmpty ? "Existing installation detected" : "System check", systemImage: "desktopcomputer").font(.system(size: 13, weight: .medium))
                        Text("Play: \(snapshot.playVersion.isEmpty ? "not installed" : snapshot.playVersion) · Rote: \(snapshot.roteVersion.isEmpty ? "not installed" : snapshot.roteVersion)").font(.system(size: 11)).foregroundStyle(.secondary)
                        Text("\(model.detected.count) harnesses detected · \(snapshot.architecture == "arm64" ? "Apple Silicon" : "Intel")").font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                }
                primary(snapshot.roteReady ? "Continue with your setup →" : "Prepare this Mac →") { model.continueWelcome() }
            } else { primary("Check this Mac") { model.refresh() } }
            Text("Existing configuration is backed up before Play changes. You review the installation plan first.").font(.system(size: 11)).foregroundStyle(.secondary).lineSpacing(3)
        }
    }
    private var account: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeading(eyebrow: "Your Plays follow you", title: model.codeSent ? "Check your email" : "Sign in", subtitle: model.codeSent ? "Enter the six-digit code sent to \(model.email)." : "Sign in or create an account. Use the same account you use on Modiqo.")
            if model.codeSent {
                field("One-time code", placeholder: "Six-digit code", text: $model.code)
                primary("Verify and continue →", disabled: model.code.count != 6 || !model.code.allSatisfy(\.isNumber)) { model.verifyCode() }
                HStack {
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        let remaining = max(0, Int(model.resendAfter.timeIntervalSince(context.date).rounded(.up)))
                        Button(remaining > 0 ? "Resend in \(remaining)s" : "Resend code") { model.sendCode() }.disabled(model.busy || remaining > 0)
                    }
                    Spacer()
                    Button("Use another email") { model.codeSent = false; model.code = "" }.disabled(model.busy)
                }.font(.system(size: 11)).buttonStyle(.plain)
            } else {
                if model.snapshot?.roteReady != true {
                    note("Prepare Rote 0.85.0 or newer before using email sign-in.")
                    Button("Prepare Rote") { model.confirmPrepare = true }.disabled(model.busy)
                }
                HStack(spacing: 12) {
                    Button("Continue with Google") { model.signIn("google") }.frame(maxWidth: .infinity)
                    Button("Continue with GitHub") { model.signIn("github") }.frame(maxWidth: .infinity)
                }.buttonStyle(UtilityButtonStyle()).controlSize(.regular).disabled(model.busy)
                HStack { Rectangle().fill(Palette.line).frame(height: 1); Text("or use email").font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(); Rectangle().fill(Palette.line).frame(height: 1) }
                field("Work or personal email", placeholder: "you@company.com", text: $model.email)
                primary("Email me a code →", disabled: !model.email.contains("@") || model.snapshot?.roteReady != true) { model.sendCode() }
                note("Google and GitHub open your browser. Email uses a one-time code. Rote keeps your sign-in for Play and the command line.")
                if model.signedIn { Button("Continue with your existing account →") { model.step = 2 }.buttonStyle(.plain) }
            }
        }
    }
    private var organization: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeading(eyebrow: "Make room for your team", title: "Organization", subtitle: "Create an organization to publish private Plays and share them with your colleagues.")
            if !model.organizations.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Or continue with an existing organization").font(.system(size: 11)).foregroundStyle(.secondary)
                    ForEach(model.organizations) { org in
                        Button { model.selectOrganization(org) } label: { HStack { Text(org.name); Spacer(); Text(org.owned ? "Owner" : "Member").foregroundStyle(.secondary); Image(systemName: "arrow.right") }.font(.system(size: 12)).padding(12).background(Palette.card, in: RoundedRectangle(cornerRadius: 3)) }.buttonStyle(.plain).disabled(model.busy)
                    }
                }
                Divider()
            }
            field("Company or organization name", placeholder: "e.g. Northstar Studio", text: $model.orgName)
            field("Organization handle", placeholder: "e.g. northstar-studio", text: $model.orgSlug)
            note("You’ll be the owner. Choose a unique handle with lowercase letters, numbers, or hyphens.", symbol: "checkmark.shield")
            primary("Create organization →", disabled: model.orgName.trimmingCharacters(in: .whitespaces).isEmpty || model.orgSlug.isEmpty) { model.createOrganization() }
            Button("I’m using Play on my own") { model.activeOrg = ""; model.step = 4 }.buttonStyle(.plain).frame(maxWidth: .infinity).foregroundStyle(.secondary).disabled(model.busy)
        }
    }
    private var invitations: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeading(eyebrow: "Good work is a team sport", title: "Invite colleagues", subtitle: "Invite colleagues to \(model.orgName). You can always do this later.")
            field("Colleague’s email", placeholder: "colleague@company.com", text: $model.inviteEmail)
            Picker("Role", selection: $model.inviteRole) { Text("Co-manager (admin)").tag("admin"); Text("Member (developer)").tag("developer"); Text("Reader").tag("reader") }.disabled(model.busy)
            Button("+ Add colleague") { model.addInvitation() }.disabled(model.busy || model.inviteEmail.isEmpty)
            ForEach(model.invitations) { invite in
                HStack { Text(invite.email).font(.system(size: 12)); Spacer(); Text(invite.role).font(.system(size: 10)).foregroundStyle(.secondary); Text(invite.status).font(.system(size: 10)); if invite.status == "Waiting" { Button { model.invitations.removeAll { $0.id == invite.id } } label: { Image(systemName: "xmark") }.buttonStyle(.plain).disabled(model.busy) } }.padding(11).background(Palette.card, in: RoundedRectangle(cornerRadius: 3))
            }
            note("Co-managers can manage Plays and members. Members can contribute Plays. Readers can use shared Plays.")
            if model.invitations.contains(where: { $0.status == "Check account" }) {
                Button("Review pending invitations on your account ↗") { model.openURL("https://www.modiqo.ai/account") }
            }
            primary(model.invitations.isEmpty ? "Continue without invitations →" : "Send invitations & continue →", disabled: model.invitations.contains(where: { $0.status == "Check account" })) { if model.invitations.isEmpty { model.step = 4 } else { model.sendInvitations() } }
            if !model.invitations.isEmpty { Button("Skip remaining invitations") { model.step = 4 }.disabled(model.busy) }
        }
    }
    private var harnesses: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeading(eyebrow: "Meet your tools where they are", title: "Choose harnesses", subtitle: "Choose where to install or update Play. Existing installations stay in place when you leave them unselected.")
            if model.detected.isEmpty { note("No supported harness was detected. Install a harness such as Claude Code, Codex, or Cursor, then refresh."); Button("Refresh detection") { model.refresh() }.disabled(model.busy) }
            ForEach(model.detected) { harness in
                Toggle(isOn: Binding(get: { model.selected.contains(harness.id) }, set: { if $0 { model.selected.insert(harness.id) } else { model.selected.remove(harness.id) } })) {
                    HStack(spacing: 12) {
                        Image(systemName: harness.symbol).foregroundStyle(Palette.green).font(.title3)
                        VStack(alignment: .leading, spacing: 5) { Text(harness.name).font(.system(size: 13, weight: .medium)); Text(harness.installed ? "Play \(harness.version.isEmpty ? "detected" : harness.version)" : "Detected · ready to set up").font(.system(size: 11)).foregroundStyle(.secondary) }
                        Spacer(); Text(harness.entry).font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
                    }
                }.toggleStyle(.checkbox).padding(10).background(Palette.card).overlay(Rectangle().strokeBorder(Palette.line)).disabled(model.busy)
            }
            primary("Review setup →", disabled: model.selected.isEmpty) { model.reviewInstall() }
            note("The plan checks the latest Play release and Rote update. It backs up Play configuration before applying changes.", symbol: "checkmark.shield")
        }
    }
    private var installation: some View {
        VStack(alignment: .leading, spacing: 18) {
            Image(systemName: model.error == nil ? "arrow.down.circle" : "exclamationmark.circle").font(.system(size: 20)).foregroundStyle(Palette.orange)
            PageHeading(eyebrow: model.error == nil ? "A little setup, a lot of possibility" : "Your recovery files are kept", title: model.error == nil ? "Installation progress" : "Installation needs attention", subtitle: model.busy ? "Keep Play open while your installation and harnesses are verified." : "Review the installation receipt, then prepare a fresh plan to retry safely.")
            ForEach(model.events) { event in
                HStack(spacing: 10) {
                    if event.state == "running" && model.busy { ProgressView().controlSize(.small) }
                    else { Image(systemName: event.state == "complete" ? "checkmark.circle.fill" : event.state == "failed" ? "exclamationmark.circle" : "circle").foregroundStyle(event.state == "failed" ? Palette.orange : Palette.green) }
                    Text(event.label).font(.system(size: 12)); Spacer()
                }.padding(.vertical, 5)
            }
            if !model.busy {
                if model.report != nil { Button("Open installation receipt") { model.openReport() } }
                HStack { Button("Copy support report") { model.copySupport() }; Button("Discord support ↗") { model.openDiscord() } }
                Button("Go to Home") { model.openHome() }.buttonStyle(UtilityButtonStyle())
                primary("Review setup again →") { model.step = 4; model.refresh() }
            }
        }
    }
    private var completion: some View {
        VStack(alignment: .leading, spacing: 18) {
            Image(systemName: "checkmark.circle.fill").font(.system(size: 20)).foregroundStyle(Palette.green)
            PageHeading(eyebrow: "All set", title: "Installation complete", subtitle: "Restart running harnesses so they load the updated skills and hooks. Then open a fresh conversation.")
            Text("Installed on").font(.system(size: 15, weight: .semibold))
            HarnessTable()
            primary("Go to my home →") { model.openHome() }
            if model.report != nil { Button("View installation receipt") { model.openReport() }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.secondary) }
        }
    }
}

struct PlanSheet: View {
    @EnvironmentObject var model: AppModel
    var plan: InstallPlan
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            PageHeading(eyebrow: "Before we start", title: "Review installation", subtitle: "Apply Play and Rote changes together, then verify your selected harnesses.")
            Card {
                VStack(spacing: 13) {
                    row("Play", "\(plan.installedVersion.isEmpty ? "Not installed" : plan.installedVersion) → \(plan.version)")
                    Divider(); row("Rote", "\(plan.roteVersion) · \(plan.roteAction)")
                    Divider(); row("Harnesses", plan.harnesses.joined(separator: ", "))
                }
            }
            VStack(alignment: .leading, spacing: 12) {
                Label("Back up Play’s existing installation and settings.", systemImage: "checkmark.shield")
                Label("Install or update Play and Rote skills in the selected tools.", systemImage: "arrow.down.circle")
                Label("Check the installation and save a recovery receipt.", systemImage: "checkmark.circle")
            }.font(.system(size: 12)).foregroundStyle(.secondary)
            DisclosureGroup("Installation details") {
                ScrollView { VStack(alignment: .leading, spacing: 10) { ForEach(Array(plan.actions.enumerated()), id: \.offset) { _, action in Text(action).font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) } } }.frame(height: 150).padding(.top, 10)
            }.font(.system(size: 11))
            Text(plan.note).font(.system(size: 11)).foregroundStyle(.secondary).lineSpacing(3)
            HStack { Button("Go back") { model.plan = nil }; Spacer(); Button("Install / update Play + Rote") { model.applyPlan() }.buttonStyle(UtilityButtonStyle(prominent: true)).disabled(model.busy) }
        }.padding(30).frame(width: 580)
    }
    private func row(_ label: String, _ value: String) -> some View { HStack { Text(label); Spacer(); Text(value).foregroundStyle(.secondary).multilineTextAlignment(.trailing) }.font(.system(size: 12)) }
}
