#!/usr/bin/env python3
"""Compile the production feed model against a deterministic paged transport."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[1]
model = (root / 'V2EX/Features/Home/HomeView.swift').read_text().split('struct HomeView:')[0].replace('import SwiftUI', 'import Foundation\nimport Combine')
stubs = r'''
struct V2Topic { let id: Int; var title = "topic"; var authorName = "author"; var lastTouched: Int? = 1 }
@MainActor final class V2EXClient {
    static let shared = V2EXClient()
    struct TopicPage { let topics: [V2Topic]; let hasMore: Bool }
    var calls: [String] = []
    var fail = false
    var pause = false
    var continuation: CheckedContinuation<TopicPage, Error>?
    func publicTopicPage(node: String? = nil, page: Int) async throws -> TopicPage {
        calls.append("\(node ?? "recent"):\(page)")
        if pause { return try await withCheckedThrowingContinuation { continuation = $0 } }
        if fail { throw NSError(domain: "offline", code: 1) }
        let ids = page == 1 ? [1, 2] : page == 2 ? [2, 3] : [4]
        return TopicPage(topics: ids.map { V2Topic(id: $0) }, hasMore: page < (node == "short" ? 1 : 3))
    }
    func hotTopics() async throws -> [V2Topic] { [V2Topic(id: 10)] }
    func r2Topics() async throws -> [V2Topic] { [V2Topic(id: 20)] }
}
@main struct Checks {
    @MainActor static func main() async {
        let client = V2EXClient.shared
        let model = HomeViewModel()
        await model.load(feed: .all, followedNodes: [])
        assert(model.topics.map(\.id) == [1,2] && model.hasMore)
        client.fail = true
        await model.loadMore(feed: .all)
        assert(model.topics.map(\.id) == [1,2] && model.hasMore && model.moreError != nil)
        client.fail = false
        await model.loadMore(feed: .all)
        assert(client.calls.suffix(2) == ["recent:2", "recent:2"])
        assert(model.topics.map(\.id) == [1,2,3] && model.moreError == nil)
        await model.loadMore(feed: .all)
        assert(model.topics.map(\.id) == [1,2,3,4] && !model.hasMore)
        await model.load(feed: .hot, followedNodes: [])
        assert(!model.hasMore)
        await model.load(feed: .all, followedNodes: [])
        assert(model.topics.count == 4 && !model.hasMore)
        await model.load(feed: .all, followedNodes: [], force: true)
        assert(model.topics.count == 2 && model.hasMore)
        client.pause = true
        let pending = Task { await model.loadMore(feed: .all) }
        while client.continuation == nil { await Task.yield() }
        await model.load(feed: .r2, followedNodes: [])
        client.continuation?.resume(returning: .init(topics: [V2Topic(id: 99)], hasMore: true))
        await pending.value
        assert(model.feed == .r2 && model.topics.map(\.id) == [20] && !model.isLoading)
        client.pause = false
        await model.load(feed: .following, followedNodes: ["short", "long"])
        await model.loadMore(feed: .following)
        assert(client.calls.last == "long:2" && !client.calls.contains("short:2"))
        await model.load(feed: .following, followedNodes: ["new"])
        assert(client.calls.last == "new:1")
        print("PASS: pagination, retry cursor, deduplication, end, cache, refresh, stale response, followed sources")
    }
}
'''
with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp) / 'checks.swift'
    source.write_text(model + stubs)
    binary = Path(tmp) / 'checks'
    subprocess.run(['swiftc', '-parse-as-library', '-module-cache-path', '/tmp/v2ex-test-module-cache', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
