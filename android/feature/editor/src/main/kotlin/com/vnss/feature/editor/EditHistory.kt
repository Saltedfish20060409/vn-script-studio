package com.vnss.feature.editor

/** 撤销 / 重做栈。不依赖 Compose，便于单测。 */
class EditHistory(
    private val limit: Int = 100,
    /** 这段时间内的连续输入合并为一个撤销步（否则每个字都要撤销一次）。 */
    private val coalesceMs: Long = 800,
) {
    data class Snapshot(val text: String, val selStart: Int, val selEnd: Int)

    private val undoStack = ArrayDeque<Snapshot>()
    private val redoStack = ArrayDeque<Snapshot>()
    private var lastEditAt = Long.MIN_VALUE

    val canUndo: Boolean get() = undoStack.isNotEmpty()
    val canRedo: Boolean get() = redoStack.isNotEmpty()

    /** 在应用一次修改**之前**调用，传入修改前的状态。 */
    fun record(before: Snapshot, nowMs: Long) {
        val startsNewStep = undoStack.isEmpty() || lastEditAt == Long.MIN_VALUE || nowMs - lastEditAt > coalesceMs
        if (startsNewStep) {
            undoStack.addLast(before)
            while (undoStack.size > limit) undoStack.removeFirst()
        }
        lastEditAt = nowMs
        redoStack.clear()
    }

    fun undo(current: Snapshot): Snapshot? {
        val prev = undoStack.removeLastOrNull() ?: return null
        redoStack.addLast(current)
        lastEditAt = Long.MIN_VALUE // 撤销之后的下一次输入必须开新的一步
        return prev
    }

    fun redo(current: Snapshot): Snapshot? {
        val next = redoStack.removeLastOrNull() ?: return null
        undoStack.addLast(current)
        lastEditAt = Long.MIN_VALUE
        return next
    }

    fun clear() {
        undoStack.clear()
        redoStack.clear()
        lastEditAt = Long.MIN_VALUE
    }
}
