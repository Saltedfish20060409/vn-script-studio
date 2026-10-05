package com.vnss.feature.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.vnss.core.designsystem.ErrorBanner
import com.vnss.core.designsystem.InlineSpinner

/** 登录 / 注册 / 找回。登录成功后会话状态变化，由外层导航自动切走。 */
@Composable
fun AuthRoute(viewModel: AuthViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    AuthScreen(
        state = state,
        onMode = viewModel::setMode,
        onIdentifier = viewModel::onIdentifier,
        onEmail = viewModel::onEmail,
        onPassword = viewModel::onPassword,
        onServerUrl = viewModel::onServerUrl,
        onSubmit = viewModel::submit,
        onDismissError = viewModel::dismissError,
    )
}

@Composable
fun AuthScreen(
    state: AuthUiState,
    onMode: (AuthMode) -> Unit,
    onIdentifier: (String) -> Unit,
    onEmail: (String) -> Unit,
    onPassword: (String) -> Unit,
    onServerUrl: (String) -> Unit,
    onSubmit: () -> Unit,
    onDismissError: () -> Unit,
) {
    var showAdvanced by remember { mutableStateOf(false) }

    Surface(Modifier.fillMaxSize()) {
        Column(
            Modifier
                .safeDrawingPadding()
                .imePadding()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp, vertical = 32.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("VN Script Studio", style = MaterialTheme.typography.headlineMedium)
            Text(
                when (state.mode) {
                    AuthMode.LOGIN -> "登录后继续你的创作"
                    AuthMode.REGISTER -> "创建账号"
                    AuthMode.FORGOT -> "找回密码：我们会向注册邮箱发送重置链接"
                    AuthMode.RESEND -> "重新发送验证邮件"
                },
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            state.error?.let { ErrorBanner(it, onDismiss = onDismissError) }
            state.info?.let {
                Surface(color = MaterialTheme.colorScheme.primaryContainer, shape = MaterialTheme.shapes.medium) {
                    Text(
                        it,
                        Modifier.fillMaxWidth().padding(12.dp),
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }

            val submitOnDone = KeyboardActions(onDone = { onSubmit() })

            if (state.mode == AuthMode.LOGIN || state.mode == AuthMode.REGISTER) {
                OutlinedTextField(
                    value = state.identifier,
                    onValueChange = onIdentifier,
                    label = { Text(if (state.mode == AuthMode.LOGIN) "用户名或邮箱" else "用户名") },
                    singleLine = true,
                    enabled = !state.busy,
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                )
            }
            if (state.mode != AuthMode.LOGIN) {
                OutlinedTextField(
                    value = state.email,
                    onValueChange = onEmail,
                    label = { Text("邮箱") },
                    singleLine = true,
                    enabled = !state.busy,
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Email,
                        imeAction = if (state.mode == AuthMode.REGISTER) ImeAction.Next else ImeAction.Done,
                    ),
                    keyboardActions = if (state.mode == AuthMode.REGISTER) KeyboardActions.Default else submitOnDone,
                )
            }
            if (state.mode == AuthMode.LOGIN || state.mode == AuthMode.REGISTER) {
                OutlinedTextField(
                    value = state.password,
                    onValueChange = onPassword,
                    label = { Text("密码") },
                    singleLine = true,
                    enabled = !state.busy,
                    visualTransformation = PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                    keyboardActions = submitOnDone,
                )
            }

            Button(onClick = onSubmit, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) {
                if (state.busy) InlineSpinner() else Text(
                    when (state.mode) {
                        AuthMode.LOGIN -> "登录"
                        AuthMode.REGISTER -> "注册"
                        AuthMode.FORGOT -> "发送重置邮件"
                        AuthMode.RESEND -> "发送验证邮件"
                    },
                )
            }

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                when (state.mode) {
                    AuthMode.LOGIN -> {
                        TextButton(onClick = { onMode(AuthMode.REGISTER) }) { Text("注册账号") }
                        TextButton(onClick = { onMode(AuthMode.FORGOT) }) { Text("忘记密码") }
                    }
                    else -> TextButton(onClick = { onMode(AuthMode.LOGIN) }) { Text("返回登录") }
                }
            }
            if (state.mode == AuthMode.LOGIN) {
                TextButton(onClick = { onMode(AuthMode.RESEND) }) { Text("没收到验证邮件？") }
            }

            TextButton(onClick = { showAdvanced = !showAdvanced }) {
                Text(if (showAdvanced) "收起服务器设置" else "服务器设置（自建部署）")
            }
            if (showAdvanced) {
                OutlinedTextField(
                    value = state.serverUrl,
                    onValueChange = onServerUrl,
                    label = { Text("服务器地址") },
                    placeholder = { Text("留空使用默认服务器") },
                    supportingText = { Text("例如 https://example.com，不要带 /api/v1") },
                    singleLine = true,
                    enabled = !state.busy,
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Done),
                )
            }
        }
    }
}
