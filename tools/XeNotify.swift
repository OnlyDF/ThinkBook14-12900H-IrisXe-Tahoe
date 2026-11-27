import AppKit
import Foundation
import UserNotifications

class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    var titleText: String = ""
    var subtitleText: String = ""
    var bodyText: String = ""
    var cmdText: String = ""
    var shouldSend: Bool = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let args = CommandLine.arguments
        var i = 1
        while i < args.count {
            switch args[i] {
            case "--title":
                if i + 1 < args.count { titleText = args[i + 1]; i += 1 }
            case "--subtitle":
                if i + 1 < args.count { subtitleText = args[i + 1]; i += 1 }
            case "--body":
                if i + 1 < args.count { bodyText = args[i + 1]; i += 1 }
            case "--cmd":
                if i + 1 < args.count { cmdText = args[i + 1]; i += 1 }
            default:
                break
            }
            i += 1
        }
        shouldSend = !titleText.isEmpty || !bodyText.isEmpty

        let center = UNUserNotificationCenter.current()
        center.delegate = self

        if shouldSend {
            center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
                if granted {
                    let content = UNMutableNotificationContent()
                    content.title = self.titleText
                    content.subtitle = self.subtitleText
                    content.body = self.bodyText
                    if !self.cmdText.isEmpty {
                        content.userInfo = ["cmd": self.cmdText]
                    }
                    let req = UNNotificationRequest(
                        identifier: UUID().uuidString,
                        content: content,
                        trigger: nil
                    )
                    center.add(req) { _ in
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                            NSApp.terminate(nil)
                        }
                    }
                } else {
                    DispatchQueue.main.async { NSApp.terminate(nil) }
                }
            }
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
                NSApp.terminate(nil)
            }
        }
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .list, .sound])
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let info = response.notification.request.content.userInfo
        if let cmd = info["cmd"] as? String, !cmd.isEmpty {
            launchTerminalConfirm(cmd: cmd)
        }
        completionHandler()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            NSApp.terminate(nil)
        }
    }

    private func launchTerminalConfirm(cmd: String) {
        let scriptPath = "/tmp/xe-watchdog-confirm.command"
        let escapedForEcho = cmd.replacingOccurrences(of: "'", with: "'\\''")
        let script = """
        #!/bin/zsh
        clear
        echo "========================================"
        echo "  Xe 健康预警 - 待确认命令"
        echo "========================================"
        echo ""
        echo "  \(escapedForEcho)"
        echo ""
        printf "按 [回车] 立即执行，或按 Ctrl+C / 关闭窗口取消: "
        read -r _
        echo ""
        \(cmd)
        STATUS=$?
        echo ""
        echo "执行完成 (exit=$STATUS)。"
        """
        do {
            try script.write(toFile: scriptPath, atomically: true, encoding: .utf8)
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: scriptPath)
            NSWorkspace.shared.open(URL(fileURLWithPath: scriptPath))
        } catch {
            // Ignore write errors
        }
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = AppDelegate()
app.delegate = delegate
app.run()
