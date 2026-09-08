#!/usr/bin/env python3
"""Run production website pagination/parser against fixtures or supplied public captures."""
from pathlib import Path
import subprocess
import sys
import tempfile
root = Path(__file__).resolve().parents[1]
s = (root / 'V2EX/Networking/V2EXClient.swift').read_text()
models = (root / 'V2EX/Models/Models.swift').read_text().split('// MARK: - Reply')[0]
page = s[s.index('    struct TopicPage {'):s.index('    /// `/api/topics/hot.json`')]
parser = s[s.index('    private static func topicRows'):s.index('    func topics(inNode')]
match = s[s.index('    private static func matches'):s.index('    /// Publishes a new topic')]
field = s[s.index('    private static func htmlField'):s.index('/// 只接受官网 Block')].rsplit('}',1)[0]
code = models + r'''
enum HTMLText { static func plain(_ s: String) -> String { s.replacingOccurrences(of: "&amp;", with: "&") } }
enum V2EXError: Error { case decoding(String) }
actor Client {
    static let desktopUserAgent = "fixture"
    let html: String
    init(_ html: String) { self.html = html }
    func webHTML(path: String, userAgent: String) async throws -> String { html }
''' + page + parser + match + field + '\n}\n' + r'''
@main struct Checks {
    static func main() async throws {
        let row = "<div class=\"cell item\"><a href=\"/t/7#reply2\" class=\"topic-link\">Title</a><strong><a href=\"/member/test\">test</a></strong></div>"
        let first = try await Client(row + "<a href=\"/recent?p=2\">2</a>").publicTopicPage(page: 1)
        assert(first.topics.map(\.id) == [7] && first.hasMore)
        let last = try await Client(row).publicTopicPage(page: 2)
        assert(!last.hasMore)
        let nodeRow = row.replacingOccurrences(of: "cell item", with: "cell from_42 t_7")
        let node = try await Client(nodeRow + "<a href=\"/go/swift?p=3\">3</a>").publicTopicPage(node: "swift", page: 2)
        assert(node.topics.count == 1 && node.hasMore)
        do { _ = try await Client("<html>Sign in</html>").publicTopicPage(page: 1); fatalError("accepted invalid page") } catch {}
        for path in CommandLine.arguments.dropFirst() {
            let html = try String(contentsOfFile: path, encoding: .utf8)
            let result = try await Client(html).publicTopicPage(node: path.contains("node") ? "swift" : nil, page: 2)
            assert(result.topics.count > 10 && result.hasMore)
            print("PASS: captured page, \(result.topics.count) topics, next page available")
        }
        print("PASS: recent/node row templates, next/end detection, invalid page rejection")
    }
}
'''
with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp) / 'checks.swift'
    source.write_text(code)
    binary = Path(tmp) / 'checks'
    subprocess.run(['swiftc', '-parse-as-library', '-module-cache-path', '/tmp/v2ex-test-module-cache', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary), *sys.argv[1:]], check=True)
