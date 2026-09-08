import SwiftUI

@MainActor
final class NotificationsViewModel: ObservableObject {
    @Published private(set) var items: [V2Notification] = []
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?
    @Published var scope: V2Notification.Kind? = .reply

    @Published private(set) var officialUnreadCount: Int?
    @Published private(set) var syncMessage: String?
    @Published private(set) var isSyncing = false
    private var generation = UUID()
    private var identity = ""
    private var account: String?

    var unreadCount: Int { officialUnreadCount ?? 0 }

    func visible(in scope: V2Notification.Kind?) -> [V2Notification] {
        guard let scope else { return items }
        return items.filter { $0.kind == scope }
    }

    func refresh(token: String, session: V2EXSessionStore) async {
        let key = token + ":" + session.cookie
        if key == identity && isSyncing { return }
        if key != identity {
            identity = key
            items = []
            officialUnreadCount = nil
            account = nil
        }
        let request = UUID()
        generation = request
        let cookie = session.cookie
        guard !token.isEmpty else {
            isLoading = false
            syncMessage = nil
            return
        }
        isLoading = true
        errorMessage = nil
        defer { if generation == request { isLoading = false } }
        do {
            let member = try await V2EXClient.shared.currentMember(token: token)
            let result = try await V2EXClient.shared.notifications(page: 1, token: token)
            guard generation == request else { return }
            account = member.username
            items = result
            if cookie.isEmpty {
                officialUnreadCount = nil
                syncMessage = "登录同一账号的网页会话后，可同步官网未读数量和全部已读状态。"
            } else {
                do {
                    let state = try await V2EXClient.shared.notificationReadState(cookie: cookie, account: member.username)
                    guard generation == request else { return }
                    officialUnreadCount = state.unreadCount
                    syncMessage = nil
                } catch {
                    guard generation == request else { return }
                    officialUnreadCount = nil
                    syncMessage = error.localizedDescription
                }
            }
            await backfillAvatars()
        } catch {
            guard generation == request else { return }
            errorMessage = error.localizedDescription
        }
    }

    func markAllRead(session: V2EXSessionStore) async {
        guard !isSyncing, !isLoading, let account else { return }
        let request = generation
        let cookie = session.cookie
        guard !cookie.isEmpty else {
            syncMessage = "请先登录网页账号，再同步全部已读。"
            return
        }
        isSyncing = true
        defer { isSyncing = false }
        do {
            let state = try await V2EXClient.shared.markNotificationsRead(cookie: cookie, account: account)
            guard generation == request else { return }
            officialUnreadCount = state.unreadCount
            syncMessage = state.unreadCount == 0 ? "已同步官网：全部已读" : "官网仍有新提醒，请刷新后重试。"
        } catch {
            guard generation == request else { return }
            syncMessage = "已读同步失败：" + error.localizedDescription
        }
    }

    /// Notification members only carry `username` — fetch the avatar from API
    /// 1.0 once per user (cached) and patch it into the rows.
    private var avatarCache: [String: String] = [:]

    private func backfillAvatars() async {
        let request = generation
        // Re-apply cached avatars to the fresh rows first — every refresh
        // replaces `items` with a payload that never carries avatar fields,
        // so without this the avatars get wiped on each refresh.
        for index in items.indices {
            guard let member = items[index].member,
                  member.avatarURL == nil,
                  let cached = avatarCache[member.username] else { continue }
            items[index].member?.avatarLarge = cached
        }
        // Then fetch whatever is still missing, once per user.
        for item in items {
            guard let member = item.member,
                  member.avatarURL == nil,
                  !member.username.isEmpty,
                  avatarCache[member.username] == nil else { continue }
            guard let fetched = try? await V2EXClient.shared.member(username: member.username),
                  let url = fetched.avatarURL?.absoluteString else { continue }
            guard generation == request else { return }
            avatarCache[member.username] = url
            for index in items.indices where items[index].member?.username == member.username {
                items[index].member?.avatarLarge = url
            }
        }
    }

    func delete(_ item: V2Notification, token: String) async {
        guard !token.isEmpty else { return }
        let request = generation
        do {
            try await V2EXClient.shared.deleteNotification(id: item.id, token: token)
            guard generation == request else { return }
            items.removeAll { $0.id == item.id }
        } catch {
            guard generation == request else { return }
            syncMessage = "删除失败：" + error.localizedDescription
        }
    }

}

struct NotificationsView: View {
    @EnvironmentObject private var model: NotificationsViewModel
    @EnvironmentObject private var token: TokenStore
    @EnvironmentObject private var session: V2EXSessionStore
    @EnvironmentObject private var moderation: ModerationStore

    /// Per-scope scroll offsets, so swiping between scopes doesn't lose your place.
    @State private var scrollPositions: [V2Notification.Kind?: ScrollPosition] = [:]

    private let scopes: [(kind: V2Notification.Kind?, title: String)] = [
        (.reply, "回复我的"), (.mention, "@ 我的"), (.thanks, "感谢"), (nil, "全部"),
    ]

    var body: some View {
        // One page per scope: swiping and the system segmented control stay in
        // sync through the shared `model.scope` selection.
        TabView(selection: $model.scope) {
            ForEach(Array(scopes.enumerated()), id: \.offset) { _, scope in
                page(for: scope.kind)
                    .tag(scope.kind)
            }
        }
        .tabViewStyle(.page(indexDisplayMode: .never))
        // Let the list scroll under the floating tab bar instead of stopping above it.
        .ignoresSafeArea(edges: .bottom)
        .background(Theme.canvas)
        .navigationTitle("通知")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("全部已读") {
                    Task { await model.markAllRead(session: session) }
                }
                .disabled(model.isSyncing || model.isLoading || !session.isLoggedIn || model.officialUnreadCount == nil || model.unreadCount == 0)
            }
        }
        .topSafeAreaBar(spacing: 0) { scopePicker }
        .task { await model.refresh(token: token.token, session: session) }
    }

    private var scopePicker: some View {
        Picker("通知类型", selection: $model.scope) {
            ForEach(Array(scopes.enumerated()), id: \.offset) { _, scope in
                Text(scopeLabel(scope.kind, title: scope.title))
                    .tag(scope.kind)
            }
        }
        .pickerStyle(.segmented)
        .padding(.horizontal, Theme.Metric.screenPadding)
        .padding(.vertical, 8)
        .readableColumn()
    }

    private func scopeLabel(_ kind: V2Notification.Kind?, title: String) -> String {
        title
    }

    private func page(for kind: V2Notification.Kind?) -> some View {
        let visible = model.visible(in: kind).filter { !moderation.isHidden(notification: $0) }
        return ScrollView {
            LazyVStack(spacing: 10) {
                if !token.hasToken {
                    tokenPrompt
                } else if model.isLoading && model.items.isEmpty {
                    LoadingCard()
                } else if let message = model.errorMessage, model.items.isEmpty {
                    EmptyStateCard(icon: "exclamationmark.triangle", title: "没能读取通知", message: message,
                                   actionTitle: "重试") {
                        Task { await model.refresh(token: token.token, session: session) }
                    }
                } else if visible.isEmpty {
                    EmptyStateCard(icon: "bell.slash", title: "没有新通知")
                } else {
                    CardSection {
                        ForEach(Array(visible.enumerated()), id: \.element.id) { index, item in
                            row(item)
                            if index < visible.count - 1 {
                                RowSeparator(leadingInset: 62)
                            }
                        }
                    }
                }
            }
            .readableColumn()
            // Room for the floating tab bar + home indicator at the bottom.
            .padding(.bottom, 100)
        }
        .scrollIndicators(.hidden)
        .pullToRefresh(isEnabled: model.scope == kind) {
            await model.refresh(token: token.token, session: session)
        }
        .scrollPosition(scrollBinding(for: kind))
    }

    private func scrollBinding(for kind: V2Notification.Kind?) -> Binding<ScrollPosition> {
        Binding(
            get: { scrollPositions[kind] ?? ScrollPosition() },
            set: { scrollPositions[kind] = $0 }
        )
    }

    private var tokenPrompt: some View {
        EmptyStateCard(
            icon: "key",
            title: "通知需要 Access Token",
            message: "V2EX 只在 API 2.0 提供通知，需要在 v2ex.com/settings/tokens 生成一个 Personal Access Token。",
            actionTitle: "去填写"
        ) { }
        .overlay {
            NavigationLink(value: Route.tokenSetup) {
                // Color.clear is transparent to hit-testing by default — the
                // shape makes the whole card tappable.
                Color.clear.contentShape(Rectangle())
            }
                .buttonStyle(.plain)
        }
    }

    private func row(_ item: V2Notification) -> some View {
        let parsed = item.parsed

        return Group {
            if let topicID = parsed.topicID {
                NavigationLink(value: Route.topic(topicID)) { rowContent(item, parsed: parsed) }
                    .buttonStyle(.row)

            } else {
                rowContent(item, parsed: parsed)
            }
        }
        .contextMenu {
            Button(role: .destructive) {
                Task { await model.delete(item, token: token.token) }
            } label: {
                Label("删除", systemImage: "trash")
            }
        }
    }

    private func rowContent(
        _ item: V2Notification,
        parsed: (action: String, topicTitle: String?, topicID: Int?)
    ) -> some View {
        HStack(alignment: .top, spacing: 11) {
            IdentitySquare(text: item.authorName, size: 34, imageURL: item.member?.avatarURL)

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    Text(item.authorName)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(Theme.ink)
                    Text(parsed.action)
                        .font(.system(size: 13))
                        .foregroundStyle(Theme.muted)
                    Spacer(minLength: 4)
                    Text(RelativeTime.string(from: item.date))
                        .font(.system(size: 12))
                        .foregroundStyle(Theme.muted)
                }

                if let payload = item.displayPayload, !payload.isEmpty {
                    Text(HTMLText.plain(payload))
                        .font(.system(size: 15))
                        .lineSpacing(3)
                        .foregroundStyle(Theme.body)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if let title = parsed.topicTitle {
                    Text("在「\(title)」")
                        .font(.system(size: 12))
                        .foregroundStyle(Theme.muted)
                        .lineLimit(1)
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .contentShape(Rectangle())
    }
}
