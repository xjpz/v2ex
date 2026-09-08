#!/usr/bin/env python3
"""Exercise production notification sync against an isolated website transport."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[1]
network = (root / 'V2EX/Networking/V2EXClient.swift').read_text()
parser = network[network.index('struct WebsiteNotificationState {'):]
requests = network[network.index('    func notificationReadState('):network.index('    func deleteNotification(')]
model = (root / 'V2EX/Features/Notifications/NotificationsView.swift').read_text().split('struct NotificationsView:')[0].replace('import SwiftUI', 'import Foundation\nimport Combine')
stubs = r'''
enum V2EXError: Error { case sessionExpired; case decoding(String) }
struct V2Member { var username: String; var avatarLarge: String?; var avatarURL: URL? { nil } }
struct V2Notification { enum Kind { case reply }; let id: Int; var member: V2Member?; var kind: Kind { .reply } }
@MainActor final class V2EXSessionStore { var cookie = "alice-cookie" }
@MainActor final class V2EXClient {
    static let shared = V2EXClient()
    static let desktopUserAgent = "fixture"
    var websiteAccount = "alice"
    var unread = 4
    var failRead = false
    var invalidPage = false
    var visits: [String] = []
    var pause = false
    var continuation: CheckedContinuation<Void, Never>?
    func currentMember(token: String) async throws -> V2Member { V2Member(username: token) }
    func notifications(page: Int, token: String) async throws -> [V2Notification] { [.init(id: 1), .init(id: 2)] }
    func member(username: String) async throws -> V2Member { V2Member(username: username) }
    func deleteNotification(id: Int, token: String) async throws {}
    func memberBlockHTML(path: String, cookie: String, userAgent: String) async throws -> String {
        visits.append(path)
        if path == "/notifications" {
            if pause { await withCheckedContinuation { continuation = $0 } }
            if failRead { throw V2EXError.sessionExpired }
            if invalidPage { return "<html>Challenge</html>" }
            unread = 0
        }
        return "<a href=\"/member/\(websiteAccount)\" class=\"top\">name</a><a href=\"/signout?once=1\">Exit</a><a href=\"/notifications\" class=\"fade\">\(unread) 未读提醒</a><a href=\"/notifications?p=1\">1</a>"
    }
''' + requests + '\n}\n'
checks = r'''
@main struct Checks {
    @MainActor static func main() async throws {
        assert(WebsiteNotificationState(html: "<html>Login</html>") == nil)
        let english = "<a class=\"top\" href=\"/member/alice\">alice</a><a href=\"/signout?once=1\">Exit</a><a href=\"/notifications\">1,234 unread notifications</a>"
        assert(WebsiteNotificationState(html: english)?.unreadCount == 1234)
        let client = V2EXClient.shared
        let session = V2EXSessionStore()
        let model = NotificationsViewModel()
        await model.refresh(token: "alice", session: session)
        assert(model.unreadCount == 4 && !client.visits.contains("/notifications"))
        client.failRead = true
        await model.markAllRead(session: session)
        assert(model.unreadCount == 4 && model.syncMessage != nil)
        client.failRead = false
        client.invalidPage = true
        await model.markAllRead(session: session)
        assert(model.unreadCount == 4)
        client.invalidPage = false
        await model.markAllRead(session: session)
        assert(model.officialUnreadCount == 0 && client.unread == 0)
        assert(Array(client.visits.suffix(3)) == ["/", "/notifications", "/"])
        client.unread = 2
        await model.refresh(token: "alice", session: session)
        assert(model.unreadCount == 2)
        client.unread = 0 // Read on website; refresh must reflect it without local seen IDs.
        await model.refresh(token: "alice", session: session)
        assert(model.unreadCount == 0)
        client.visits = []
        client.websiteAccount = "bob"
        await model.refresh(token: "alice", session: session)
        assert(model.officialUnreadCount == nil)
        await model.markAllRead(session: session)
        assert(!client.visits.contains("/notifications"))
        session.cookie = ""
        await model.refresh(token: "alice", session: session)
        await model.markAllRead(session: session)
        assert(model.officialUnreadCount == nil && !client.visits.contains("/notifications"))
        session.cookie = "alice-cookie"
        client.websiteAccount = "alice"
        client.unread = 3
        await model.refresh(token: "alice", session: session)
        client.pause = true
        let pending = Task { await model.markAllRead(session: session) }
        while client.continuation == nil { await Task.yield() }
        await model.refresh(token: "", session: session)
        client.continuation?.resume()
        await pending.value
        assert(model.items.isEmpty && model.officialUnreadCount == nil)
        print("PASS: official count, no read-on-refresh, verified acknowledgement, failure preservation, website read import, account mismatch, guest, stale response")
    }
}
'''
with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp) / 'checks.swift'
    source.write_text(model + parser + stubs + checks)
    binary = Path(tmp) / 'checks'
    subprocess.run(['swiftc', '-parse-as-library', '-module-cache-path', '/tmp/v2ex-test-module-cache', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
