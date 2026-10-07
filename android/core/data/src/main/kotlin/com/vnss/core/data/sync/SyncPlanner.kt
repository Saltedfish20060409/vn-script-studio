package com.vnss.core.data.sync

import com.vnss.core.common.ThreeWayMerge

/**
 * 一章该如何同步：纯函数，方便单测。
 *
 * [remote] 为 null 表示服务端还没有这一章（本地新建）。
 */
object SyncPlanner {

    sealed interface Decision {
        data object UploadLocal : Decision
        data class UploadMerged(val prose: String, val title: String) : Decision
        data object Conflict : Decision
        /** 本地与服务端已经一致，只需把标记清成已同步。 */
        data object AlreadyEqual : Decision
    }

    fun decide(
        baseProse: String,
        baseTitle: String,
        localProse: String,
        localTitle: String,
        remoteProse: String?,
        remoteTitle: String?,
    ): Decision {
        if (remoteProse == null) return Decision.UploadLocal
        val rTitle = remoteTitle.orEmpty()
        if (localProse == remoteProse && localTitle == rTitle) return Decision.AlreadyEqual
        if (remoteProse == baseProse && rTitle == baseTitle) return Decision.UploadLocal

        val title = mergeTitle(baseTitle, localTitle, rTitle) ?: return Decision.Conflict
        when (val prose = ThreeWayMerge.merge(baseProse, localProse, remoteProse)) {
            is ThreeWayMerge.Result.Clean -> {
                return if (prose.text == localProse && title == localTitle) {
                    Decision.UploadLocal
                } else {
                    Decision.UploadMerged(prose.text, title)
                }
            }
            is ThreeWayMerge.Result.Conflict -> Decision.Conflict
        }
        return Decision.Conflict
    }

    fun keepBoth(localProse: String, remoteProse: String): String {
        if (remoteProse.isBlank()) return localProse
        if (localProse.isBlank()) return remoteProse
        return localProse.trimEnd() + "\n\n———————— 网页端版本 ————————\n\n" + remoteProse.trimStart()
    }

    fun keepBothTitle(localTitle: String, remoteTitle: String): String {
        if (localTitle == remoteTitle || remoteTitle.isBlank()) return localTitle
        if (localTitle.isBlank()) return remoteTitle
        return localTitle
    }

    private fun mergeTitle(base: String, local: String, remote: String): String? = when {
        local == remote -> local
        local == base -> remote
        remote == base -> local
        else -> null
    }
}
