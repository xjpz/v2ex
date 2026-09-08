import SwiftUI

/// 「我的 → 内容与屏蔽」。把屏蔽名单、被举报隐藏的内容、以及举报记录
/// 摆在同一页 —— 用户按下举报之后，唯一能反悔的地方就是这里。
struct ModerationSettingsView: View {
    @EnvironmentObject private var moderation: ModerationStore
    @EnvironmentObject private var session: V2EXSessionStore
    @Environment(\.openURL) private var openURL

    @State private var newUsername = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                moderationSummary
                HStack {
                    Text(moderation.websiteListMessage ?? "官网名单尚未读取")
                        .font(Type.meta(12))
                        .foregroundStyle(Theme.muted)
                    Spacer()
                    if moderation.isRefreshingWebsite {
                        ProgressView()
                    } else {
                        Button("刷新") {
                            Task { await moderation.refreshWebsiteBlocks(session: session) }
                        }
                        .font(Type.meta(12))
                    }
                }
                .padding(.horizontal, Theme.Metric.headerPadding)

                usernameSection
                hiddenSection
                reportSection

                Text("屏蔽统一使用 V2EX 官网名单，需网页登录。操作经官网确认后生效，可下拉刷新名单。")
                    .font(Type.meta(12))
                    .lineSpacing(3)
                    .foregroundStyle(Theme.faint)
                    .padding(.horizontal, Theme.Metric.headerPadding)
            }
            .readableColumn()
            .padding(.top, 8)
            .padding(.bottom, 40)
        }
        .scrollIndicators(.hidden)
        .background(Theme.canvas)
        .navigationTitle("内容与屏蔽")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .task { await moderation.refreshWebsiteBlocks(session: session) }
        .refreshable { await moderation.refreshWebsiteBlocks(session: session) }
    }

    // MARK: 概览

    private var moderationSummary: some View {
        CardSection(padding: 18) {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 13) {
                    Image(systemName: "checkmark.shield.fill")
                        .font(.system(size: 21, weight: .semibold))
                        .foregroundStyle(Theme.accent)
                        .frame(width: 50, height: 50)
                        .background(Theme.accentSoft, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("你的内容边界")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(Theme.ink)
                        Text("屏蔽名单与当前 V2EX 账号保持一致。")
                            .font(Type.meta(12))
                            .foregroundStyle(Theme.muted)
                    }
                }
                .accessibilityElement(children: .combine)

                HStack(spacing: 0) {
                    summaryMetric(moderation.blockedUserCount, label: "官网屏蔽")
                    summaryMetric(moderation.hiddenTopicIDs.count + moderation.hiddenReplyIDs.count, label: "已隐藏")
                    summaryMetric(moderation.pendingReportCount, label: "待送达")
                }
            }
        }
    }

    private func summaryMetric(_ value: Int, label: String) -> some View {
        VStack(spacing: 3) {
            Text(value.formatted())
                .font(Type.number(19, weight: .bold))
                .foregroundStyle(value == 0 ? Theme.faint : Theme.ink)
                .contentTransition(.numericText(value: Double(value)))
            Text(label)
                .font(Type.label(10))
                .foregroundStyle(Theme.muted)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 9)
        .background(Theme.inset, in: RoundedRectangle(cornerRadius: 11, style: .continuous))
        .padding(.horizontal, 3)
        .accessibilityElement(children: .combine)
    }

    // MARK: 屏蔽名单

    private var usernameSection: some View {
        VStack(alignment: .leading, spacing: 0) {
            GroupHeader(title: "官网屏蔽的用户")
            if !session.isLoggedIn {
                CardSection(padding: 16) {
                    NavigationLink(value: Route.v2exLogin) {
                        Label("网页登录后管理屏蔽名单", systemImage: "person.crop.circle")
                            .font(Type.body(15))
                            .foregroundStyle(Theme.accent)
                    }
                }
            } else {
                CardSection {
                    HStack(spacing: 8) {
                        TextField("输入要屏蔽的用户名", text: $newUsername)
                            .font(Type.body(15))
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .onSubmit { addUser() }
                        Button("屏蔽") { addUser() }
                            .disabled(newUsername.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !moderation.syncingUsers.isEmpty)
                    }
                    .padding(16)
                    if !moderation.syncingUsers.isEmpty {
                        HStack {
                            ProgressView()
                            Text("正在等待官网确认…").font(Type.meta(12))
                        }
                        .padding(.horizontal, 16)
                        .padding(.bottom, 12)
                    }
                    ForEach(moderation.usernames, id: \.self) { username in
                        RowSeparator()
                        HStack {
                            Text(username).font(Type.body(16))
                            Spacer()
                            Button("取消屏蔽") {
                                moderation.unblock(username: username, session: session)
                            }
                            .font(Type.meta(13))
                            .foregroundStyle(Theme.accent)
                            .disabled(moderation.syncingUsers.contains(username.lowercased()))
                        }
                        .padding(16)
                    }
                    ForEach(moderation.unavailableBlockedIDs, id: \.self) { id in
                        RowSeparator()
                        VStack(alignment: .leading, spacing: 4) {
                            Text("用户 #\(String(id))").font(Type.body(16))
                            Text("官网用户资料不可用，屏蔽记录仍保留")
                                .font(Type.meta(12))
                                .foregroundStyle(Theme.muted)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(16)
                    }
                    if moderation.blockedUserCount == 0, !moderation.isRefreshingWebsite {
                        Text("当前没有已读取的官网屏蔽用户")
                            .font(Type.meta(13))
                            .foregroundStyle(Theme.muted)
                            .padding(16)
                    }
                }
            }
        }
    }

    private func addUser() {
        moderation.block(username: newUsername, session: session)
    }

    // MARK: 被举报隐藏的内容

    @ViewBuilder
    private var hiddenSection: some View {
        let hiddenTopics = moderation.hiddenTopicIDs.sorted(by: >)
        let hiddenReplies = moderation.hiddenReplyIDs.sorted(by: >)
        if !hiddenTopics.isEmpty || !hiddenReplies.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                GroupHeader(title: "已隐藏的内容")
                CardSection {
                    ForEach(Array(hiddenTopics.enumerated()), id: \.element) { index, id in
                        hiddenRow(title: "话题 #\(id)", isFirst: index == 0) {
                            moderation.unhideTopic(id)
                        }
                    }
                    ForEach(Array(hiddenReplies.enumerated()), id: \.element) { index, id in
                        hiddenRow(
                            title: "回复 #\(id)",
                            isFirst: index == 0 && hiddenTopics.isEmpty
                        ) {
                            moderation.unhideReply(id)
                        }
                    }
                }
            }
        }
    }

    private func hiddenRow(title: String, isFirst: Bool, onRestore: @escaping () -> Void) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            if !isFirst { RowSeparator(leadingInset: Theme.Metric.cardPadding) }
            HStack {
                Text(title)
                    .font(Type.body(16))
                    .foregroundStyle(Theme.ink)
                Spacer()
                Button("恢复显示") {
                    withAnimation(.snappy) { onRestore() }
                }
                .font(Type.meta(13))
                .foregroundStyle(Theme.accent)
                .buttonStyle(.plain)
            }
            .padding(.horizontal, Theme.Metric.cardPadding)
            .frame(minHeight: 48)
        }
    }

    // MARK: 举报记录

    @ViewBuilder
    private var reportSection: some View {
        if !moderation.reports.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                GroupHeader(title: "举报记录")
                CardSection {
                    ForEach(Array(moderation.reports.prefix(30).enumerated()), id: \.element.id) { index, report in
                        if index > 0 { RowSeparator(leadingInset: Theme.Metric.cardPadding) }
                        reportRow(report)
                    }
                }
                if moderation.pendingReportCount > 0 {
                    Text("有 \(moderation.pendingReportCount) 条举报还没送达开发者，App 会自动重试。急需处理可以点这条记录用邮件直接发送。")
                        .font(Type.meta(12))
                        .lineSpacing(3)
                        .foregroundStyle(Theme.muted)
                        .padding(.horizontal, Theme.Metric.headerPadding)
                        .padding(.top, 8)
                }
            }
        }
    }

    private func reportRow(_ report: ContentReport) -> some View {
        Button {
            guard let url = ReportService.mailtoURL(for: report) else { return }
            openURL(url)
        } label: {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: report.kind == .block ? "nosign" : "flag")
                    .font(.system(size: 15))
                    .foregroundStyle(Theme.accent)
                    .frame(width: 20)
                    .padding(.top, 2)
                VStack(alignment: .leading, spacing: 3) {
                    Text(report.summary)
                        .font(Type.body(15))
                        .foregroundStyle(Theme.ink)
                    Text("\(report.kind == .block ? "屏蔽记录" : report.reason.title) · \(RelativeTime.string(from: report.createdAt))")
                        .font(Type.meta(12))
                        .foregroundStyle(Theme.muted)
                }
                Spacer(minLength: 8)
                Text(report.isDelivered ? "已送达" : "待发送")
                    .font(Type.label(11))
                    .foregroundStyle(report.isDelivered ? Theme.muted : Theme.accent)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(
                        report.isDelivered ? AnyShapeStyle(Theme.inset) : AnyShapeStyle(Theme.accentSoft),
                        in: Capsule()
                    )
                    .padding(.top, 1)
            }
            .padding(.horizontal, Theme.Metric.cardPadding)
            .padding(.vertical, 12)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

}
