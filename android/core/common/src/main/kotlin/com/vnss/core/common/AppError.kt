package com.vnss.core.common

/**
 * 全 App 统一的错误模型。
 *
 * 为什么不直接把 HttpException / IOException 往上抛：UI 层要的是「能直接给人看的一句话」
 * 与「该不该重试 / 该不该跳登录」这两个判断，而不是协议细节。网络层负责把底层异常翻译成它。
 */
sealed class AppError(
    override val message: String,
    override val cause: Throwable? = null,
) : Exception(message, cause) {

    /** 连不上服务端（断网 / DNS / 拒绝连接）。可重试。 */
    class Network(message: String = "连接不上服务端：请检查网络后重试。", cause: Throwable? = null) :
        AppError(message, cause)

    /** 客户端等待超时。服务端可能仍在处理——文案不要说「后端挂了」。 */
    class Timeout(message: String, cause: Throwable? = null) : AppError(message, cause)

    /** 未登录或登录已过期（刷新令牌也失败）。需要回登录页。 */
    class Unauthorized(message: String = "未登录或登录已过期") : AppError(message)

    /** 无权限（只读成员、账号停用、邮箱未验证等）。 */
    class Forbidden(message: String) : AppError(message)

    /** 资源不存在（项目被删 / 无权访问）。 */
    class NotFound(message: String = "项目不存在或已被删除") : AppError(message)

    /** 章节被其他成员锁定（HTTP 423）。稍后重试即可。 */
    class Locked(message: String) : AppError(message)

    /** 项目在别处被修改（HTTP 409 project_conflict）。 */
    class Conflict(message: String, val serverUpdatedAt: String? = null) : AppError(message)

    /** 限流（HTTP 429）。 */
    class RateLimited(message: String) : AppError(message)

    /** 其它 4xx / 5xx，服务端给了人话就原样带上。 */
    class Http(val code: Int, message: String) : AppError(message)

    /** 本地逻辑错误（数据损坏、不应发生的状态）。 */
    class Local(message: String, cause: Throwable? = null) : AppError(message, cause)

    /** 是否值得自动重试（WorkManager 据此决定 retry / failure）。 */
    val isRetryable: Boolean
        get() = when (this) {
            is Network, is Timeout, is Locked, is RateLimited -> true
            is Http -> code >= 500
            else -> false
        }
}

/** 把任意异常收敛成 [AppError]（已经是的原样返回）。 */
fun Throwable.asAppError(): AppError = when (this) {
    is AppError -> this
    else -> AppError.Local(message ?: "未知错误", this)
}
