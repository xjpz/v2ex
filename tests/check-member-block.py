#!/usr/bin/env python3
"""Run the production block parser/request flow with URLProtocol fixtures, without a V2EX account.
Usage: python3 tests/check-member-block.py
The app has no test target; compile the relevant production declarations in an isolated harness.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'V2EX/Networking/V2EXClient.swift').read_text()
errors = source[source.index('enum V2EXError:'):source.index('/// API 2.0 wraps')]
endpoint = source[source.index('enum V2EXEndpoint {'):source.index('actor V2EXClient {')]
flow = source[source.index('    func setMemberBlocked('):source.index('    /// 主题页收藏区')]
parser = source[source.index('struct MemberBlockPage {'):]
harness = r'''
import Foundation

final class StubProtocol: URLProtocol, @unchecked Sendable {
    struct Step {
        let path: String
        let body: String
        var status = 200
        var finalPath: String? = nil
    }
    static var steps: [Step] = []
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        precondition(!Self.steps.isEmpty, "Unexpected request")
        let step = Self.steps.removeFirst()
        precondition(request.url!.path + (request.url!.query.map { "?" + $0 } ?? "") == step.path)
        precondition(request.httpMethod == "GET")
        precondition(request.value(forHTTPHeaderField: "Cookie") == "PB3_SESSION=test")
        precondition(request.cachePolicy == .reloadIgnoringLocalCacheData)
        if step.path.hasPrefix("/block/") || step.path.hasPrefix("/unblock/") {
            precondition(request.value(forHTTPHeaderField: "Referer") == "https://www.v2ex.com/member/test_user")
        }
        let url = step.finalPath.map { V2EXEndpoint.url($0) } ?? request.url!
        client!.urlProtocol(self, didReceive: HTTPURLResponse(url: url, statusCode: step.status, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client!.urlProtocol(self, didLoad: Data(step.body.utf8))
        client!.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@main struct Checks {
    static func page(_ action: String, id: Int = 42) -> String {
        "<input type=\"button\" value=\"\(action == "block" ? "Block" : "Unblock")\" onclick=\"if (confirm('sure?')) { location.href = '/\(action)/\(id)?once=123'; }\" />"
    }
    static func main() async throws {
        precondition(WebsiteBlockList.ids(from: "<script>const blocked = [240807,253365,275429,93264];</script>") == [93264,240807,253365,275429])
        precondition(WebsiteBlockList.ids(from: "<script>\nvar blocked = [ ];</script>") == [])
        precondition(WebsiteBlockList.ids(from: "<script>let blocked = [42,42,7];</script>") == [7,42])
        for invalid in ["Sign In", "<script>const ignored_topics = [];</script>", "<p>const blocked = [42];</p>", "<script>const blocked = [0];</script>", "<script>const blocked = [1,];</script>", "<script>const blocked = [1];\nconst blocked = [2];</script>"] {
            precondition(WebsiteBlockList.ids(from: invalid) == nil, "Accepted invalid: \(invalid)")
        }
        print("PASS website list parser: four users, empty, duplicates, invalid/login pages")
        let block = page("block"), unblock = page("unblock")
        precondition(MemberBlockPage(html: block)?.blocked == false)
        precondition(MemberBlockPage(html: unblock)?.blocked == true)
        precondition(MemberBlockPage(html: block)?.memberID == "42")
        for bad in ["<html>Sign In</html>", "/block/42?once=1", block + unblock,
                    block.replacingOccurrences(of: "'/block/", with: "'https://evil.example/block/"),
                    block.replacingOccurrences(of: "'/block/", with: "'//evil.example/block/"),
                    block.replacingOccurrences(of: "?once=123", with: ""),
                    block.replacingOccurrences(of: "?once=123", with: "?once=123&redirect=evil"),
                    block.replacingOccurrences(of: "value=\"Block\"", with: "value=\"Unblock\""),
                    "&lt;input value=\"Block\" onclick=\"location.href='/block/42?once=1'\"&gt;"] {
            precondition(MemberBlockPage(html: bad) == nil, "Accepted invalid page: \(bad)")
        }
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubProtocol.self]
        let client = V2EXClient(webSession: URLSession(configuration: config))
        func run(_ name: String, blocked: Bool, steps: [StubProtocol.Step], succeeds: Bool,
                 username: String = "test_user", cookie: String = "PB3_SESSION=test") async {
            StubProtocol.steps = steps
            do {
                try await client.setMemberBlocked(username: username, blocked: blocked, cookie: cookie)
                precondition(succeeds, "Unexpected success: \(name)")
            } catch {
                precondition(!succeeds, "Unexpected failure: \(name): \(error)")
            }
            precondition(StubProtocol.steps.isEmpty, "Missing requests: \(name)")
            print("PASS \(name)")
        }
        await run("block and verify", blocked: true, steps: [.init(path: "/member/test_user", body: block), .init(path: "/block/42?once=123", body: unblock), .init(path: "/member/test_user", body: unblock)], succeeds: true)
        await run("unblock and verify", blocked: false, steps: [.init(path: "/member/test_user", body: unblock), .init(path: "/unblock/42?once=123", body: block), .init(path: "/member/test_user", body: block)], succeeds: true)
        await run("already blocked", blocked: true, steps: [.init(path: "/member/test_user", body: unblock)], succeeds: true)
        await run("already unblocked", blocked: false, steps: [.init(path: "/member/test_user", body: block)], succeeds: true)
        await run("HTTP 200 without state change", blocked: true, steps: [.init(path: "/member/test_user", body: block), .init(path: "/block/42?once=123", body: block), .init(path: "/member/test_user", body: block)], succeeds: false)
        await run("wrong member after mutation", blocked: true, steps: [.init(path: "/member/test_user", body: block), .init(path: "/block/42?once=123", body: unblock), .init(path: "/member/test_user", body: page("unblock", id: 99))], succeeds: false)
        await run("login redirect", blocked: true, steps: [.init(path: "/member/test_user", body: "Sign In", finalPath: "/signin")], succeeds: false)
        await run("missing button", blocked: true, steps: [.init(path: "/member/test_user", body: "No button")], succeeds: false)
        await run("forbidden mutation", blocked: true, steps: [.init(path: "/member/test_user", body: block), .init(path: "/block/42?once=123", body: "Forbidden", status: 403)], succeeds: false)
        await run("empty cookie", blocked: true, steps: [], succeeds: false, cookie: "")
        await run("unsafe username", blocked: true, steps: [], succeeds: false, username: "../settings")
        StubProtocol.steps = [
            .init(path: "/", body: "<script>const blocked = [7,42,99];</script>"),
            .init(path: "/api/members/show.json?id=7", body: "{\"id\":7,\"username\":\"first\"}"),
            .init(path: "/api/members/show.json?id=42", body: "{\"status\":\"error\",\"message\":\"Object Not Found\"}", status: 404),
            .init(path: "/api/members/show.json?id=99", body: "{\"id\":99,\"username\":\"last\"}")
        ]
        let snapshot = try await client.blockedUsers(cookie: "PB3_SESSION=test")
        precondition(snapshot.usernames == ["first", "last"] && snapshot.unavailableIDs == [42])
        precondition(StubProtocol.steps.isEmpty)
        print("PASS one missing user does not abort or truncate the official list")
        StubProtocol.steps = [.init(path: "/", body: "<script>const blocked = [42];</script>"), .init(path: "/api/members/show.json?id=42", body: "unavailable", status: 503)]
        do {
            _ = try await client.blockedUsers(cookie: "PB3_SESSION=test")
            preconditionFailure("503 must not be mistaken for an unavailable user")
        } catch {}
        precondition(StubProtocol.steps.isEmpty)
        print("PASS other network errors still fail safely")
        print("PASS parser validation and 13 request scenarios")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='v2ex-block-tests-') as directory:
    path = Path(directory)
    swift = path / 'Checks.swift'
    swift.write_text('import Foundation\n' + errors + endpoint + '\nstruct V2Member: Decodable { let id: Int?; let username: String }\nactor V2EXClient {\nlet webSession: URLSession\nstatic let mobileUserAgent = "test"\nstatic let desktopUserAgent = "test-desktop"\ninit(webSession: URLSession) { self.webSession = webSession }\n' + flow + r'''
    private func getV1<T: Decodable>(_ path: String, query: [String: String]) async throws -> T {
        var request = URLRequest(url: V2EXEndpoint.url(path + "?id=" + query["id"]!), cachePolicy: .reloadIgnoringLocalCacheData)
        request.setValue("PB3_SESSION=test", forHTTPHeaderField: "Cookie")
        let (data, response) = try await webSession.data(for: request)
        let status = (response as! HTTPURLResponse).statusCode
        guard status == 200 else { throw V2EXError.badStatus(status) }
        return try JSONDecoder().decode(T.self, from: data)
    }
''' + '\n}\n'  + parser + harness)
    subprocess.run(['swiftc', '-parse-as-library', '-module-cache-path', str(path / 'cache'), str(swift), '-o', str(path / 'checks')], check=True)
    subprocess.run([str(path / 'checks')], check=True)
