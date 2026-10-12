import AppKit
import SwiftUI

enum Palette {
    private static func adaptive(_ light: UInt32, _ dark: UInt32) -> Color {
        func color(_ value: UInt32) -> NSColor {
            NSColor(srgbRed: CGFloat((value >> 16) & 255) / 255, green: CGFloat((value >> 8) & 255) / 255, blue: CGFloat(value & 255) / 255, alpha: 1)
        }
        return Color(nsColor: NSColor(name: nil) { appearance in
            color(appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light)
        })
    }
    static let paper = adaptive(0xF3F4F6, 0x1D1E22)
    static let sidebar = adaptive(0xECEEF1, 0x222328)
    static let chrome = adaptive(0xF7F8FA, 0x25262C)
    static let card = adaptive(0xFFFFFF, 0x24252A)
    static let alternate = adaptive(0xF8F9FA, 0x27282E)
    static let line = adaptive(0xD5D7DE, 0x3B3D46)
    static let text = adaptive(0x24262D, 0xE3E4EB)
    static let secondary = adaptive(0x616674, 0xA1A6B3)
    static let accent = adaptive(0x5155A7, 0xB0B3FF)
    static let selection = adaptive(0xE0E3F4, 0x393C60)
    static let button = adaptive(0x5559AD, 0x5056A0)
    static let green = adaptive(0x28735C, 0x85BCA7)
    static let orange = adaptive(0xAC4B2E, 0xE39A7C)
}

struct UtilityButtonStyle: ButtonStyle {
    var prominent = false
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 12, weight: .medium))
            .foregroundStyle(prominent ? .white : Palette.text)
            .padding(.horizontal, 10).padding(.vertical, 5)
            .background(prominent ? Palette.button : Palette.card, in: RoundedRectangle(cornerRadius: 4))
            .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(prominent ? Palette.accent.opacity(0.55) : Palette.line, lineWidth: 1))
            .overlay(RoundedRectangle(cornerRadius: 4).fill(configuration.isPressed ? Color.primary.opacity(0.10) : .clear))
            .opacity(enabled ? 1 : 0.42)
            .contentShape(Rectangle())
    }
}

struct Card<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content.padding(14).background(Palette.card)
            .overlay(Rectangle().strokeBorder(Palette.line, lineWidth: 1))
    }
}

struct Panel<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content.background(Palette.card)
            .overlay(Rectangle().strokeBorder(Palette.line, lineWidth: 1))
    }
}

struct Eyebrow: View {
    var text: String
    var body: some View { Text(text).font(.system(size: 11, weight: .medium)).foregroundStyle(Palette.secondary) }
}

struct PageHeading: View {
    var eyebrow: String; var title: String; var subtitle: String
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.system(size: 21, weight: .semibold))
            Text(subtitle).font(.system(size: 12)).foregroundStyle(Palette.secondary).lineSpacing(2).fixedSize(horizontal: false, vertical: true)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct Brand: View {
    var body: some View {
        HStack(spacing: 8) {
            if let url = Bundle.main.url(forResource: "modiqo-logo", withExtension: "png"), let logo = NSImage(contentsOf: url) {
                Image(nsImage: logo).renderingMode(.template).resizable().frame(width: 98, height: 98)
                    .frame(width: 88, height: 26).clipped().accessibilityLabel("Modiqo")
            } else { Text("modiqo").font(.system(size: 18, weight: .semibold)) }
            Rectangle().fill(Palette.line).frame(width: 1, height: 16)
            Text("Play").font(.system(size: 12, weight: .medium)).foregroundStyle(Palette.secondary)
        }
    }
}

struct AppearanceControl: View {
    @EnvironmentObject var model: AppModel
    private let options = [("system", "display", "System"), ("light", "sun.max", "Light"), ("dark", "moon", "Dark")]
    var body: some View {
        HStack(spacing: 0) {
            ForEach(options, id: \.0) { option in
                Button { model.appearance = option.0 } label: {
                    Image(systemName: option.1).font(.system(size: 11)).frame(width: 28, height: 24)
                        .foregroundStyle(model.appearance == option.0 ? Palette.accent : Palette.secondary)
                        .background(model.appearance == option.0 ? Palette.selection : .clear)
                }.buttonStyle(.plain).help(option.2 + " appearance").accessibilityLabel(option.2 + " appearance")
                    .accessibilityAddTraits(model.appearance == option.0 ? .isSelected : [])
            }
        }.clipShape(RoundedRectangle(cornerRadius: 4))
            .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Palette.line))
            .accessibilityElement(children: .contain).accessibilityLabel("Appearance")
    }
}

struct SectionLabel: View {
    var title: String; var detail: String = ""
    var body: some View {
        HStack(spacing: 8) {
            Text(title).font(.system(size: 12, weight: .semibold))
            if !detail.isEmpty { Text(detail).font(.system(size: 11, design: .monospaced)).foregroundStyle(Palette.secondary) }
            Spacer()
        }
    }
}
