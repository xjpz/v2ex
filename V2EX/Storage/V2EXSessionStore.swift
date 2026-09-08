import Foundation
import Security
import SwiftUI

/// V2EX 网页会话（cookie）。官方 API 没有发帖/回复接口，只有网页表单能写——
/// 用户用账号密码在 app 内登录一次，拿到 `PB3_SESSION` 会话 cookie 存进
/// Keychain，之后发回复直接带这个 cookie 模拟网页提交。
///
/// 与 `TokenStore` 互不相关：token 是 API 2.0 只读凭证，cookie 是网页写权限。
@MainActor
final class V2EXSessionStore: ObservableObject {
    @Published private(set) var cookie: String = ""
    @Published private(set) var username: String = ""

    private let cookieService = "com.vibe.v2ex.session"
    private let usernameService = "com.vibe.v2ex.session.username"
    private let account = "default"

    var isLoggedIn: Bool { !cookie.isEmpty }

    init() {
        #if DEBUG && targetEnvironment(simulator)
        if let scenario = ModerationReplay.scenario {
            cookie = "moderation-response-replay"
            username = scenario.account
            return
        }
        #endif
        cookie = read(service: cookieService) ?? ""
        username = read(service: usernameService) ?? ""
    }

    func save(cookie: String, username: String) {
        self.cookie = cookie
        self.username = username
        write(cookie, service: cookieService)
        write(username, service: usernameService)
    }

    func clear() {
        cookie = ""
        username = ""
        delete(service: cookieService)
        delete(service: usernameService)
    }

    private func read(service: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private func write(_ value: String, service: String) {
        delete(service: service)
        guard !value.isEmpty, let data = value.data(using: .utf8) else { return }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    private func delete(service: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
