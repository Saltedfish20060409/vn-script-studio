package com.vnss.feature.settings

import android.Manifest
import android.app.TimePickerDialog
import android.content.Context
import android.net.Uri
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.browser.customtabs.CustomTabsIntent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.vnss.core.designsystem.ErrorBanner
import com.vnss.core.designsystem.InfoBanner
import com.vnss.core.designsystem.InlineSpinner
import com.vnss.core.model.AccountSettings
import com.vnss.core.model.LocalSettings
import com.vnss.core.model.ThemeMode
import com.vnss.core.model.UsageOverview
import com.vnss.core.model.UsageTotals

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsRoute(onBack: () -> Unit, viewModel: SettingsViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val local by viewModel.local.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var confirmLogout by remember { mutableStateOf(false) }

    // Android 13+ 的通知权限：开启提醒时才申请；被拒绝就把开关退回去，而不是假装开启
    val notifPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        viewModel.setReminderEnabled(granted)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("设置") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回") }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            state.message?.let { InfoBanner(it, onDismiss = viewModel::dismissMessage) }

            // ---------------------------------------------------------------- 账号
            Section("账号")
            Text(viewModel.username ?: "已登录", style = MaterialTheme.typography.bodyLarge)
            viewModel.email?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            Text("服务器：${viewModel.serverOrigin}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedButton(onClick = { confirmLogout = true }, enabled = !state.loggingOut) {
                if (state.loggingOut) InlineSpinner() else Text("退出登录")
            }
            HorizontalDivider()

            // ---------------------------------------------------------------- 外观
            Section("外观")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ThemeMode.entries.forEach { mode ->
                    FilterChip(
                        selected = local.themeMode == mode,
                        onClick = { viewModel.setTheme(mode) },
                        label = { Text(themeLabel(mode)) },
                    )
                }
            }
            // 拖动过程中只改本地状态，松手才落库（否则每一帧都写一次 DataStore 并重排提醒任务）
            var scale by remember(local.fontScale) { mutableFloatStateOf(local.fontScale) }
            Text("字号 ${"%.0f".format(scale * 100)}%", style = MaterialTheme.typography.labelLarge)
            Slider(
                value = scale,
                onValueChange = { scale = it },
                onValueChangeFinished = { viewModel.setFontScale(scale) },
                valueRange = 0.85f..1.4f,
            )
            HorizontalDivider()

            // ---------------------------------------------------------------- 写作
            Section("写作")
            GoalField(local, viewModel)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("每日写作提醒")
                    Text(
                        "今天还没写时在设定时间提醒一次；已经写过就不打扰。",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Switch(
                    checked = local.reminderEnabled,
                    onCheckedChange = { on ->
                        if (on && Build.VERSION.SDK_INT >= 33) {
                            notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                        } else {
                            viewModel.setReminderEnabled(on)
                        }
                    },
                )
            }
            if (local.reminderEnabled) {
                OutlinedButton(onClick = { pickTime(context, local, viewModel) }) {
                    Text("提醒时间 %02d:%02d".format(local.reminderHour, local.reminderMinute))
                }
            }
            HorizontalDivider()

            // ---------------------------------------------------------------- 隐私
            Section("隐私")
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("防截屏 / 隐藏最近任务预览")
                    Text("开启后无法截图，多任务界面也不显示稿子内容。", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Switch(checked = local.secureWindow, onCheckedChange = viewModel::setSecureWindow)
            }
            HorizontalDivider()

            // ---------------------------------------------------------------- AI 模型
            Section("AI 模型")
            AccountModelSection(state.account, state.accountError, state.savingAccount, viewModel)
            LocalKeySection(local, state.hasLocalKey, viewModel)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedButton(onClick = viewModel::testLlm, enabled = !state.testing) {
                    if (state.testing) InlineSpinner() else Text("测试连接")
                }
                state.testResult?.let {
                    val text = if (it.ok) "连接正常 · ${it.latencyMs}ms${it.model?.let { m -> " · $m" } ?: ""}" else "失败：${it.error ?: "未知错误"}"
                    Text(text, style = MaterialTheme.typography.labelMedium, color = if (it.ok) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error)
                }
                state.testError?.let { Text(it, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.error) }
            }
            HorizontalDivider()

            // ---------------------------------------------------------------- 用量
            Section("用量")
            UsageSection(state.usage, state.usageError)
            HorizontalDivider()

            // ---------------------------------------------------------------- 网页端 / 关于
            Section("更多功能")
            Text(
                "项目设定、剧本引擎、导出、完整的一致性分析等在网页端完成，手机端专注写作与查看。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { openWeb(context, viewModel.serverOrigin) }) { Text("在网页端打开") }
                OutlinedButton(onClick = { openWeb(context, viewModel.serverOrigin.trimEnd('/') + "/guide") }) { Text("使用指南") }
            }
            Text(
                "版本 ${versionName(context)}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 24.dp),
            )
        }
    }

    if (confirmLogout) {
        AlertDialog(
            onDismissRequest = { confirmLogout = false },
            title = { Text("退出登录？") },
            text = {
                Text(
                    if (state.pendingCount > 0) {
                        "还有 ${state.pendingCount} 章没有同步。会先尝试上传；上传不了的稿子会保留在手机上，用同一账号重新登录后继续同步。"
                    } else {
                        "稿子都已同步，退出后会清除手机上的本地缓存。"
                    },
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    confirmLogout = false
                    viewModel.logout {}
                }) { Text("退出") }
            },
            dismissButton = { TextButton(onClick = { confirmLogout = false }) { Text("取消") } },
        )
    }
}

@Composable
private fun Section(title: String) {
    Text(title, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(top = 8.dp))
}

private fun themeLabel(mode: ThemeMode) = when (mode) {
    ThemeMode.SYSTEM -> "跟随系统"
    ThemeMode.LIGHT -> "浅色"
    ThemeMode.DARK -> "深色"
}

private fun pickTime(context: Context, local: LocalSettings, vm: SettingsViewModel) {
    TimePickerDialog(context, { _, h, m -> vm.setReminderTime(h, m) }, local.reminderHour, local.reminderMinute, true).show()
}

private fun openWeb(context: Context, url: String) {
    // Custom Tabs：用户的浏览器里已登录的会话可复用，不用在 App 内嵌 WebView（也就不会碰到令牌）
    runCatching { CustomTabsIntent.Builder().build().launchUrl(context, Uri.parse(url)) }
}

private fun versionName(context: Context): String = runCatching {
    context.packageManager.getPackageInfo(context.packageName, 0).versionName
}.getOrNull() ?: "未知"

// -------------------------------------------------------------------- 写作目标

@Composable
private fun GoalField(local: LocalSettings, vm: SettingsViewModel) {
    // 用本地 text 状态承载输入，避免每敲一个字都经 DataStore 往返导致光标跳动
    var text by remember { mutableStateOf(if (local.dailyGoalWords > 0) local.dailyGoalWords.toString() else "") }
    OutlinedTextField(
        value = text,
        onValueChange = {
            text = it.filter { c -> c.isDigit() }.take(6)
            vm.setDailyGoal(text)
        },
        modifier = Modifier.fillMaxWidth(),
        label = { Text("每日目标字数（0 或留空 = 不设）") },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
    )
}

// -------------------------------------------------------------------- 账号级模型配置

@Composable
private fun AccountModelSection(
    account: AccountSettings?,
    error: String?,
    saving: Boolean,
    vm: SettingsViewModel,
) {
    Text("账号里保存的模型配置（网页端同步使用）", style = MaterialTheme.typography.labelLarge)
    error?.let { ErrorBanner(it, onRetry = vm::refreshRemote) }
    if (account == null) {
        if (error == null) Text("加载中…", style = MaterialTheme.typography.bodySmall)
        return
    }
    var baseUrl by remember(account) { mutableStateOf(account.apiBaseUrl) }
    var model by remember(account) { mutableStateOf(account.apiModel) }
    var key by remember(account) { mutableStateOf("") }
    Text(
        "当前生效：${account.activeModel.ifBlank { "未配置" }}（来源：${sourceLabel(account.credentialSource)}）",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    OutlinedTextField(baseUrl, { baseUrl = it }, Modifier.fillMaxWidth(), label = { Text("API 地址") }, singleLine = true)
    OutlinedTextField(model, { model = it }, Modifier.fillMaxWidth(), label = { Text("模型名") }, singleLine = true)
    OutlinedTextField(
        value = key,
        onValueChange = { key = it },
        modifier = Modifier.fillMaxWidth(),
        label = { Text(if (account.hasApiKey) "API Key（已保存 ${account.apiKeyMasked}，留空不修改）" else "API Key") },
        singleLine = true,
        visualTransformation = PasswordVisualTransformation(),
    )
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(
            onClick = {
                vm.saveAccount(apiKey = key.trim().ifEmpty { null }, baseUrl = baseUrl, model = model)
                key = ""
            },
            enabled = !saving,
        ) { if (saving) InlineSpinner() else Text("保存") }
        if (account.hasApiKey) {
            TextButton(onClick = { vm.saveAccount(apiKey = "", baseUrl = baseUrl, model = model) }, enabled = !saving) { Text("清除已存的 Key") }
        }
    }
}

private fun sourceLabel(source: String) = when (source) {
    "server" -> "服务器默认"
    "account", "user" -> "账号设置"
    "request", "local" -> "本机 Key"
    else -> source
}

// -------------------------------------------------------------------- 仅本机 Key

@Composable
private fun LocalKeySection(local: LocalSettings, hasKey: Boolean, vm: SettingsViewModel) {
    var key by remember { mutableStateOf("") }
    var baseUrl by remember(local.localLlmBaseUrl) { mutableStateOf(local.localLlmBaseUrl) }
    var model by remember(local.localLlmModel) { mutableStateOf(local.localLlmModel) }

    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 8.dp)) {
        Column(Modifier.weight(1f)) {
            Text("仅用这台手机上的 Key")
            Text(
                "Key 只加密保存在本机，不上传账号；每次请求随连接发给你的服务器转发给模型厂商。",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Switch(checked = local.localLlmEnabled, onCheckedChange = vm::setLocalLlmEnabled)
    }
    if (local.localLlmEnabled) {
        OutlinedTextField(baseUrl, { baseUrl = it }, Modifier.fillMaxWidth(), label = { Text("API 地址") }, singleLine = true)
        OutlinedTextField(model, { model = it }, Modifier.fillMaxWidth(), label = { Text("模型名") }, singleLine = true)
        OutlinedTextField(
            value = key,
            onValueChange = { key = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text(if (hasKey) "API Key（已保存，留空不修改）" else "API Key") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                vm.setLocalLlmBaseUrl(baseUrl)
                vm.setLocalLlmModel(model)
                if (key.isNotBlank()) vm.saveLocalKey(key)
                key = ""
            }) { Text("保存到本机") }
            if (hasKey) TextButton(onClick = { vm.saveLocalKey("") }) { Text("清除本机 Key") }
        }
        if (!hasKey) {
            Text("还没有保存 Key，开关不会生效。", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
        }
    }
}

// -------------------------------------------------------------------- 用量

@Composable
private fun UsageSection(usage: UsageOverview?, error: String?) {
    error?.let { Text("用量加载失败：$it", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
    if (usage == null) {
        if (error == null) Text("加载中…", style = MaterialTheme.typography.bodySmall)
        return
    }
    UsageRow("今日", usage.today)
    UsageRow("累计", usage.total)
}

@Composable
private fun UsageRow(label: String, t: UsageTotals) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, style = MaterialTheme.typography.bodyMedium)
        Text(
            "${t.calls} 次调用 · ${formatTokens(t.totalTokens)} tokens（输入 ${formatTokens(t.promptTokens)} / 输出 ${formatTokens(t.completionTokens)}）",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

internal fun formatTokens(n: Long): String = when {
    n >= 1_000_000 -> "%.1fM".format(n / 1_000_000.0)
    n >= 1_000 -> "%.1fk".format(n / 1_000.0)
    else -> n.toString()
}