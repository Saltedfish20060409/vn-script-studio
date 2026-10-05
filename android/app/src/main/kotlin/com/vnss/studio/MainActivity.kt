package com.vnss.studio

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.vnss.core.designsystem.LoadingBox
import com.vnss.core.designsystem.VnssTheme
import com.vnss.core.model.SessionState
import com.vnss.feature.auth.AuthRoute
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    private val viewModel: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val session by viewModel.session.collectAsStateWithLifecycle()
            val settings by viewModel.settings.collectAsStateWithLifecycle()

            // 「防截屏 / 隐藏最近任务缩略图」：写作内容属于隐私，用户可在设置里开启
            LaunchedEffect(settings.secureWindow) {
                if (settings.secureWindow) {
                    window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)
                } else {
                    window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
                }
            }

            VnssTheme(themeMode = settings.themeMode, fontScale = settings.fontScale) {
                when (session) {
                    SessionState.Loading -> LoadingBox()
                    SessionState.SignedOut -> AuthRoute()
                    is SessionState.SignedIn -> AppNavHost()
                }
            }
        }
    }
}
