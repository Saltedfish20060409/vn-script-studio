package com.vnss.core.common

import kotlinx.coroutines.CancellationException

/** 带类型化错误的结果；比 kotlin.Result 多一层「错误必须是 AppError」的约束。 */
sealed interface Outcome<out T> {
    data class Success<T>(val value: T) : Outcome<T>
    data class Failure(val error: AppError) : Outcome<Nothing>

    val isSuccess: Boolean get() = this is Success

    fun getOrNull(): T? = (this as? Success)?.value
    fun errorOrNull(): AppError? = (this as? Failure)?.error
}

inline fun <T, R> Outcome<T>.map(transform: (T) -> R): Outcome<R> = when (this) {
    is Outcome.Success -> Outcome.Success(transform(value))
    is Outcome.Failure -> this
}

inline fun <T> Outcome<T>.onSuccess(block: (T) -> Unit): Outcome<T> {
    if (this is Outcome.Success) block(value)
    return this
}

inline fun <T> Outcome<T>.onFailure(block: (AppError) -> Unit): Outcome<T> {
    if (this is Outcome.Failure) block(error)
    return this
}

/**
 * 执行并把异常收敛成 [Outcome.Failure]。
 *
 * 协程取消必须继续向上抛：吞掉 CancellationException 会让「用户离开页面」被当成一次失败，
 * 进而触发重试或弹错。
 */
inline fun <T> outcomeOf(block: () -> T): Outcome<T> = try {
    Outcome.Success(block())
} catch (e: CancellationException) {
    throw e
} catch (e: Throwable) {
    Outcome.Failure(e.asAppError())
}
