package com.vnss.feature.editor

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.vnss.feature.editor.check.IssueLevel
import com.vnss.feature.editor.check.TextIssue

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IssuesSheet(
    lint: LintResult,
    bodyText: String,
    onDismiss: () -> Unit,
    onJump: (offset: Int, length: Int) -> Unit,
) {
    // 体检结果对应的文本已经不是当前文本（刚打过字）：偏移不可信，先提示而不是跳错地方
    val fresh = lint.text == bodyText
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 16.dp)) {
            Text(
                if (lint.issues.isEmpty()) "没有发现笔误或标点问题" else "共 ${lint.issues.size} 处，点一条跳到原文",
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp),
                style = MaterialTheme.typography.titleMedium,
            )
            if (!fresh) {
                Text(
                    "正在重新检查…",
                    modifier = Modifier.padding(horizontal = 20.dp),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            LazyColumn {
                itemsIndexed(lint.issues) { index, issue ->
                    IssueRow(issue, enabled = fresh, onJump = { onJump(issue.offset, issue.length) })
                    if (index < lint.issues.lastIndex) HorizontalDivider()
                }
            }
        }
    }
}

@Composable
private fun IssueRow(issue: TextIssue, enabled: Boolean, onJump: () -> Unit) {
    var showBasis by remember { mutableStateOf(false) }
    val tag = when (issue.level) {
        IssueLevel.ERROR -> "错误" to MaterialTheme.colorScheme.error
        IssueLevel.WARN -> "提示" to MaterialTheme.colorScheme.tertiary
        IssueLevel.INFO -> "建议" to MaterialTheme.colorScheme.outline
    }
    Column(
        Modifier
            .fillMaxWidth()
            .clickable(enabled = enabled, onClick = onJump)
            .padding(horizontal = 20.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(tag.first, style = MaterialTheme.typography.labelMedium, color = tag.second)
            Text("第 ${issue.line} 行", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Text(issue.message, style = MaterialTheme.typography.bodyMedium)
        Text(
            "「${issue.snippet}」",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (issue.basis.isNotBlank()) {
            Text(
                if (showBasis) "依据：${issue.basis}" else "查看依据",
                modifier = Modifier.clickable { showBasis = !showBasis },
                style = MaterialTheme.typography.labelSmall,
                color = if (showBasis) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.primary,
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScenesSheet(
    lint: LintResult,
    bodyText: String,
    onDismiss: () -> Unit,
    onJump: (offset: Int) -> Unit,
) {
    val fresh = lint.text == bodyText
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 16.dp)) {
            val hasMarkers = lint.scenes.size > 1 || lint.scenes.any { it.explicit }
            Text(
                when {
                    lint.scenes.isEmpty() -> "本章还没有内容"
                    !hasMarkers -> "本章还没有分场（用 ◇◇◇ 或【场景名】分隔）"
                    else -> "共 ${lint.scenes.size} 个场景"
                },
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp),
                style = MaterialTheme.typography.titleMedium,
            )
            LazyColumn {
                itemsIndexed(lint.scenes) { index, scene ->
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clickable(enabled = fresh) { onJump(scene.from) }
                            .padding(horizontal = 20.dp, vertical = 12.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Text("${index + 1}", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                        Text(scene.title, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium, maxLines = 1)
                        Text("${scene.words} 字", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    if (index < lint.scenes.lastIndex) HorizontalDivider()
                }
            }
        }
    }
}