package com.vnss.core.model

import com.vnss.core.common.Outcome
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

/**
 * 仓库接口（domain 层契约）。feature 只依赖这些接口，实现在 core:data。
 */

interface AuthRepository {
    val session: StateFlow<SessionState>

    /** 冷启动时调用：用本地 refresh token 换 access token，决定进登录页还是主页。 */
    suspend fun restoreSession()

    suspend fun login(identifier: String, password: String): Outcome<Unit>
    suspend fun register(username: String, email: String, password: String): Outcome<String>
    suspend fun resendVerification(identifier: String): Outcome<String>
    suspend fun forgotPassword(identifier: String): Outcome<String>
    suspend fun logout()
}

interface ProjectRepository {
    fun observeProjects(): Flow<List<ProjectSummary>>
    fun observeProject(projectId: String): Flow<Project?>
    fun observeChapters(projectId: String): Flow<List<ChapterSummary>>
    fun observeChapter(chapterId: String): Flow<Chapter?>

    /** 拉项目列表（只更新元数据，不拉正文）。 */
    suspend fun refreshProjects(): Outcome<Unit>

    /** 拉单个项目全量（章节正文入库）；本地有未同步修改的章节不会被覆盖。 */
    suspend fun refreshProject(projectId: String): Outcome<Unit>

    suspend fun createProject(title: String): Outcome<String>

    /** 在项目里新建一章（本地先落库，等同步上传）。返回新章节 id。 */
    suspend fun createChapter(projectId: String, title: String): String

    /**
     * 保存草稿：只写本地 Room，并把章节标记为 DIRTY、调度后台同步。
     * 绝不依赖网络——这是「离线也不丢字」的保证。
     */
    suspend fun saveDraft(chapterId: String, title: String, prose: String)
}

interface SyncRepository {
    /** 待同步（DIRTY）+ 冲突（CONFLICT）的章节总数，用于顶栏角标。 */
    fun observePendingCount(): Flow<Int>

    suspend fun syncProject(projectId: String): SyncReport
    suspend fun syncAll(): SyncReport

    suspend fun loadConflict(chapterId: String): ChapterConflict?
    suspend fun resolveConflict(chapterId: String, resolution: ConflictResolution): Outcome<Unit>
}

interface SyncScheduler {
    /** 调度一次（带少量延迟去抖的）后台同步。 */
    fun scheduleSync(delaySeconds: Long = 8)

    /** 注册周期性兜底同步。 */
    fun ensurePeriodicSync()
}

interface AgentRepository {
    suspend fun listConversations(projectId: String): Outcome<List<AgentConversationSummary>>
    suspend fun createConversation(projectId: String, title: String?): Outcome<AgentConversation>
    suspend fun loadConversation(projectId: String, conversationId: String): Outcome<AgentConversation>
    suspend fun saveConversation(
        projectId: String,
        conversationId: String,
        messages: List<AgentMessage>,
    ): Outcome<Unit>

    /**
     * 流式运行 Agent。运行前会先把本地未同步的章节推上去，
     * 运行后若服务端应用了改动，会重新拉取项目（见实现）。
     */
    fun run(request: AgentRunRequest): Flow<AgentEvent>
}

interface LedgerRepository {
    fun observeLedger(projectId: String): Flow<Ledger>
    suspend fun refresh(projectId: String): Outcome<Unit>
}

interface CollabRepository {
    suspend fun members(projectId: String): Outcome<List<Member>>
    suspend fun locks(projectId: String): Outcome<List<ChapterLock>>
    suspend fun comments(projectId: String, chapterId: String?): Outcome<List<Comment>>
    suspend fun addComment(
        projectId: String,
        chapterId: String,
        text: String,
        anchor: String,
        parentId: String?,
    ): Outcome<Comment>

    suspend fun setResolved(projectId: String, commentId: String, resolved: Boolean): Outcome<Comment>
    suspend fun deleteComment(projectId: String, commentId: String): Outcome<Unit>

    /** 协作事件流（自动重连）；订阅者取消即断开。 */
    fun events(projectId: String): Flow<CollabEvent>
}

interface SettingsRepository {
    val local: Flow<LocalSettings>
    suspend fun updateLocal(transform: (LocalSettings) -> LocalSettings)

    /** 本机 Key 读写（加密存储）。 */
    suspend fun localLlmKey(): String
    suspend fun setLocalLlmKey(key: String)

    suspend fun account(): Outcome<AccountSettings>
    suspend fun updateAccount(update: AccountSettingsUpdate): Outcome<AccountSettings>
    suspend fun usage(): Outcome<UsageOverview>
    suspend fun testLlm(): Outcome<TestLlmResult>
}

interface ReminderScheduler {
    /** 按设置重新安排（或取消）每日写作提醒。 */
    fun apply(settings: LocalSettings)
}

// ---------------------------------------------------------------- 低层契约（network / datastore 共用）

/** 令牌存取。实现放在加密存储里（core:datastore）。 */
interface TokenStore {
    fun accessToken(): String?
    fun refreshToken(): String?
    fun save(accessToken: String, refreshToken: String?)
    fun clear()
}

/** 服务端地址提供者；每次请求都会读取，因此切换服务器无需重建网络栈。 */
interface ServerUrlProvider {
    /** 形如 https://host[:port]，不含 /api/v1。 */
    fun origin(): String
}

/** 本机 Key 模式下随请求附带的 LLM 凭据（未启用返回 null）。 */
interface LocalLlmCredentialsProvider {
    fun current(): LocalLlmCredentials?
}

data class LocalLlmCredentials(val apiKey: String, val baseUrl: String, val model: String)
