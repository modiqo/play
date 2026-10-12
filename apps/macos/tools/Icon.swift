import AppKit

// Draw the app icon with native shapes and the unmodified Modiqo wordmark.
let image = NSImage(size: NSSize(width: 1024, height: 1024))
image.lockFocus()
NSColor(red: 0.94, green: 0.95, blue: 0.91, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 64, y: 64, width: 896, height: 896), xRadius: 196, yRadius: 196).fill()
NSColor(red: 0.87, green: 0.32, blue: 0.16, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 294, y: 358, width: 436, height: 436), xRadius: 110, yRadius: 110).fill()
NSColor.white.setFill()
let triangle = NSBezierPath()
triangle.move(to: NSPoint(x: 452, y: 463))
triangle.line(to: NSPoint(x: 452, y: 689))
triangle.line(to: NSPoint(x: 635, y: 576))
triangle.close(); triangle.fill()
if let logo = NSImage(contentsOfFile: CommandLine.arguments[1]) {
    logo.draw(in: NSRect(x: 279, y: -5, width: 466, height: 466))
}
image.unlockFocus()
let representation = NSBitmapImageRep(data: image.tiffRepresentation!)!
try representation.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
