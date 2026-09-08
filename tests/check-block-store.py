#!/usr/bin/env python3
"""Exercise the production moderation store with in-memory persistence and a fake website."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'V2EX/Features/Moderation/ModerationStore.swift').read_text().replace('UserDefaults.standard', 'MemoryDefaults.shared')
snapshot = (root / 'V2EX/Networking/V2EXClient.swift').read_text().split('struct WebsiteBlockSnapshot:')[1]
snapshot = 'struct WebsiteBlockSnapshot:' + snapshot
stubs = r'''
import Foundation
import Combine

@MainActor final class MemoryDefaults {
    static let shared = MemoryDefaults()
    var values: [String: Any] = [:]
    func stringArray(forKey key: String) -> [String]? { values[key] as? [String] }
    func dictionary(forKey key: String) -> [String: Any]? { values[key] as? [String: Any] }
    func set(_ value: Any, forKey key: String) { values[key] = value }
}
@MainActor enum DiskStore {
    static var data: Data?
    static func url(for name: String) -> URL { URL(fileURLWithPath: "/tmp/unused-test.json") }
    static func load<T: Decodable>(_ type: T.Type, from: URL) -> T? {
        data.flatMap { try? JSONDecoder().decode(type, from: $0) }
    }
    static func save<T: Encodable>(_ value: T, to: URL) { data = try? JSONEncoder().encode(value) }
}
struct Member { let id: Int? }
struct V2Topic { let id: Int; let authorName: String; let title: String; let content: String?; var member: Member? = nil }
struct V2Reply { let id: Int; let authorName: String; let content: String; var member: Member? = nil }
struct ThreadedReply {
    let reply: V2Reply
    var floor: Int = 0
    var quoted: Quote? = nil
    struct Quote { let username: String; let floor: Int?; let excerpt: String }
}
struct V2Notification { let authorName: String; var member: Member? = nil; var memberId: Int? = nil }
@MainActor final class V2EXSessionStore {
    var username = "alice"
    var cookie = "alice-cookie"
    var isLoggedIn: Bool { !cookie.isEmpty }
}
@MainActor enum ReportService {
    static var calls = 0
    static func send(_ report: ContentReport) async -> Bool { calls += 1; return true }
}
@MainActor final class V2EXClient {
    static let shared = V2EXClient()
    var names: [String] = []
    var unavailableIDs: [Int] = []
    var mutationFail = false
    var mutationCalls = 0
    var fail = false
    var paused = false
    var continuation: CheckedContinuation<WebsiteBlockSnapshot, Error>?
    func blockedUsers(cookie: String) async throws -> WebsiteBlockSnapshot {
        if paused { return try await withCheckedThrowingContinuation { continuation = $0 } }
        if fail { throw NSError(domain: "test", code: 1) }
        return WebsiteBlockSnapshot(usernames: names, unavailableIDs: unavailableIDs)
    }
    func setMemberBlocked(username: String, blocked: Bool, cookie: String) async throws {
        mutationCalls += 1
        if mutationFail { throw NSError(domain: "mutation", code: 1) }
    }
}
@main struct Checks {
    @MainActor static func main() async {
        let defaults = MemoryDefaults.shared
        defaults.set(["LocalOnly", "RemoteOne"], forKey: "blockedUsernames")
        let session = V2EXSessionStore()
        let client = V2EXClient.shared
        let store = ModerationStore()
        client.names = ["remoteone", "RemoteTwo"]
        await store.refreshWebsiteBlocks(session: session)
        precondition(Set(store.usernames.map { $0.lowercased() }) == ["remoteone", "remotetwo"])
        precondition(store.reports.isEmpty && ReportService.calls == 0)
        precondition(!store.isBlocked(username: "LocalOnly"))
        print("PASS official list only; legacy local rules ignored; no reports on import")
        client.fail = true
        await store.refreshWebsiteBlocks(session: session)
        precondition(store.isBlocked(username: "RemoteTwo"))
        print("PASS failure preserves remote snapshot")
        client.fail = false
        client.names = []
        await store.refreshWebsiteBlocks(session: session)
        precondition(store.usernames.isEmpty)
        print("PASS explicit empty official list removes blocks")
        client.names = ["AliceBlocked"]
        await store.refreshWebsiteBlocks(session: session)
        session.username = "bob"; session.cookie = "bob-cookie"
        client.names = ["BobBlocked"]
        await store.refreshWebsiteBlocks(session: session)
        precondition(!store.isBlocked(username: "AliceBlocked") && store.isBlocked(username: "BobBlocked"))
        session.username = ""; session.cookie = ""
        await store.refreshWebsiteBlocks(session: session)
        precondition(store.usernames.isEmpty)
        print("PASS account switch and logout isolate remote lists")
        let reopened = ModerationStore()
        session.username = "alice"; session.cookie = "alice-cookie"
        client.fail = true
        await reopened.refreshWebsiteBlocks(session: session)
        precondition(reopened.isBlocked(username: "AliceBlocked"))
        print("PASS cache survives relaunch and offline fetch")
        client.fail = false; client.paused = true
        let oldRead = Task { await reopened.refreshWebsiteBlocks(session: session) }
        while client.continuation == nil { await Task.yield() }
        let pending = client.continuation!; client.continuation = nil; client.paused = false
        session.username = "bob"; session.cookie = "bob-cookie"
        client.names = ["NewBobBlocked"]
        await reopened.refreshWebsiteBlocks(session: session)
        pending.resume(returning: WebsiteBlockSnapshot(usernames: ["StaleAliceBlocked"], unavailableIDs: []))
        await oldRead.value
        precondition(!reopened.isBlocked(username: "StaleAliceBlocked") && reopened.isBlocked(username: "NewBobBlocked"))
        print("PASS late response cannot overwrite another account")
        client.names = ["VisibleUser"]; client.unavailableIDs = [999]
        await reopened.refreshWebsiteBlocks(session: session)
        precondition(reopened.blockedUserCount == 2 && reopened.unavailableBlockedIDs == [999])
        let hidden = V2Topic(id: 1, authorName: "unknown", title: "x", content: nil, member: Member(id: 999))
        precondition(reopened.isHidden(hidden))
        print("PASS unavailable official user retained, counted and filtered by ID")
        precondition(reopened.isHidden(notification: V2Notification(authorName: "visibleuser")))
        precondition(reopened.isHidden(notification: V2Notification(authorName: "", memberId: 999)))
        precondition(!reopened.isHidden(notification: V2Notification(authorName: "Allowed")))
        let blocked = ThreadedReply(reply: V2Reply(id: 1, authorName: "VisibleUser", content: "hidden"), floor: 5)
        let normal = ThreadedReply(reply: V2Reply(id: 2, authorName: "Allowed", content: "normal"), floor: 6,
            quoted: .init(username: "VisibleUser", floor: 5, excerpt: "hidden"))
        let orphan = ThreadedReply(reply: V2Reply(id: 3, authorName: "Deleted", content: "hidden", member: Member(id: 999)), floor: 7)
        let orphanQuote = ThreadedReply(reply: V2Reply(id: 4, authorName: "Allowed", content: "normal"), floor: 8,
            quoted: .init(username: "Deleted", floor: 7, excerpt: "hidden"))
        let filtered = reopened.visible([blocked, normal, orphan, orphanQuote])
        precondition(filtered.map(\.floor) == [6, 8] && filtered.allSatisfy { $0.quoted == nil })
        precondition(reopened.visible([normal]).first?.quoted == nil)
        print("PASS blocked notifications, replies and quote previews hidden; original floors preserved")

        client.mutationFail = true
        reopened.block(username: "FailedUser", session: session)
        precondition(!reopened.isBlocked(username: "FailedUser"))
        while !reopened.syncingUsers.isEmpty { await Task.yield() }
        precondition(!reopened.isBlocked(username: "FailedUser") && reopened.reports.isEmpty)
        reopened.unblock(username: "VisibleUser", session: session)
        while !reopened.syncingUsers.isEmpty { await Task.yield() }
        precondition(reopened.isBlocked(username: "VisibleUser"))
        print("PASS failed block/unblock preserves official list; no false report")
        client.mutationFail = false
        reopened.block(username: "SuccessUser", session: session)
        precondition(!reopened.isBlocked(username: "SuccessUser"))
        while !reopened.syncingUsers.isEmpty { await Task.yield() }
        precondition(reopened.isBlocked(username: "SuccessUser") && reopened.reports.count == 1)
        reopened.unblock(username: "SuccessUser", session: session)
        while !reopened.syncingUsers.isEmpty { await Task.yield() }
        precondition(!reopened.isBlocked(username: "SuccessUser"))
        print("PASS official confirmation gates list changes and notifications")
        session.username = ""; session.cookie = ""
        let calls = client.mutationCalls
        reopened.block(username: "GuestBlock", session: session)
        reopened.unblock(username: "VisibleUser", session: session)
        precondition(reopened.usernames.isEmpty && client.mutationCalls == calls)
        precondition(reopened.reports.count == 1)
        print("PASS guests cannot create local blocks or submit website mutations")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='v2ex-store-tests-') as directory:
    path = Path(directory)
    swift = path / 'Checks.swift'
    swift.write_text(stubs + snapshot + source)
    subprocess.run(['swiftc', '-parse-as-library', '-module-cache-path', str(path / 'cache'), str(swift), '-o', str(path / 'checks')], check=True)
    subprocess.run([str(path / 'checks')], check=True)
