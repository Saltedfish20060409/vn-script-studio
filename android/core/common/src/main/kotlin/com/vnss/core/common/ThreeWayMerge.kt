package com.vnss.core.common

/**
 * 按「行（段落）」做三方合并（diff3 思路）。
 *
 * 场景：用户在手机上改了某章（local），同时 Web 端也改了同一章（remote），二者的共同祖先是
 * 上次同步时的版本（base）。只要双方改的是**互不重叠**的段落，就能自动合成一份，不打扰用户；
 * 重叠改动才进入「冲突」交给用户裁决。小说正文天然以段落为单位，所以行级粒度比字符级更符合直觉，
 * 也避免把一句话从中间拼坏。
 *
 * 算法：分别求 base↔local、base↔remote 的 LCS，两边都**原样保留**的 base 行作为「稳定锚点」；
 * 相邻锚点之间的三段（base/local/remote）按规则取舍：
 * - 一边没改（等于 base）→ 取另一边；
 * - 两边改得一样 → 取其一；
 * - 两边改得不一样 → 冲突。
 */
object ThreeWayMerge {

    sealed interface Result {
        data class Clean(val text: String) : Result
        data class Conflict(val hunks: Int) : Result
    }

    /** 去掉公共前后缀后的 LCS 矩阵上限（行数乘积），超过就放弃自动合并以保护内存。 */
    private const val MAX_CELLS = 4_000_000L

    fun merge(base: String, local: String, remote: String): Result {
        if (local == remote) return Result.Clean(local)
        if (local == base) return Result.Clean(remote)
        if (remote == base) return Result.Clean(local)

        val b = base.split("\n")
        val l = local.split("\n")
        val r = remote.split("\n")

        val matchL = align(b, l) ?: return Result.Conflict(1)
        val matchR = align(b, r) ?: return Result.Conflict(1)

        val out = ArrayList<String>(maxOf(l.size, r.size))
        var conflicts = 0
        var bi = 0
        var li = 0
        var ri = 0

        fun resolveChunk(bEnd: Int, lEnd: Int, rEnd: Int) {
            val bc = b.subList(bi, bEnd)
            val lc = l.subList(li, lEnd)
            val rc = r.subList(ri, rEnd)
            when {
                lc == bc -> out.addAll(rc)
                rc == bc -> out.addAll(lc)
                lc == rc -> out.addAll(lc)
                else -> conflicts++
            }
        }

        for (i in b.indices) {
            val ml = matchL[i]
            val mr = matchR[i]
            if (ml < 0 || mr < 0) continue // 不是稳定锚点
            resolveChunk(bEnd = i, lEnd = ml, rEnd = mr)
            out.add(b[i])
            bi = i + 1
            li = ml + 1
            ri = mr + 1
        }
        resolveChunk(bEnd = b.size, lEnd = l.size, rEnd = r.size)

        return if (conflicts == 0) Result.Clean(out.joinToString("\n")) else Result.Conflict(conflicts)
    }

    /**
     * 返回 `match[i] = base 第 i 行在 other 里对应的行号`（-1 表示该行被改动/删除）。
     * 矩阵过大时返回 null。
     */
    private fun align(base: List<String>, other: List<String>): IntArray? {
        val match = IntArray(base.size) { -1 }

        // 公共前缀 / 后缀：长文只改几处时，中间要做 DP 的部分很小
        var prefix = 0
        while (prefix < base.size && prefix < other.size && base[prefix] == other[prefix]) {
            match[prefix] = prefix
            prefix++
        }
        var suffix = 0
        while (
            suffix < base.size - prefix &&
            suffix < other.size - prefix &&
            base[base.size - 1 - suffix] == other[other.size - 1 - suffix]
        ) {
            match[base.size - 1 - suffix] = other.size - 1 - suffix
            suffix++
        }

        val bMid = base.size - prefix - suffix
        val oMid = other.size - prefix - suffix
        if (bMid == 0 || oMid == 0) return match
        if (bMid.toLong() * oMid.toLong() > MAX_CELLS) return null

        // dp[i][j] = base[prefix+i..) 与 other[prefix+j..) 的 LCS 长度
        val dp = Array(bMid + 1) { IntArray(oMid + 1) }
        for (i in bMid - 1 downTo 0) {
            for (j in oMid - 1 downTo 0) {
                dp[i][j] = if (base[prefix + i] == other[prefix + j]) {
                    dp[i + 1][j + 1] + 1
                } else {
                    maxOf(dp[i + 1][j], dp[i][j + 1])
                }
            }
        }
        var i = 0
        var j = 0
        while (i < bMid && j < oMid) {
            when {
                base[prefix + i] == other[prefix + j] -> {
                    match[prefix + i] = prefix + j
                    i++
                    j++
                }
                dp[i + 1][j] >= dp[i][j + 1] -> i++
                else -> j++
            }
        }
        return match
    }
}
