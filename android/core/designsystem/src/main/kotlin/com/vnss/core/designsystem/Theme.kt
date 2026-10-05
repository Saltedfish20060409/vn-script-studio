package com.vnss.core.designsystem

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.LineBreak
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.sp
import com.vnss.core.model.ThemeMode

private val LightColors = lightColorScheme(
    primary = Color(0xFF5B4FCF),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFE5E0FF),
    onPrimaryContainer = Color(0xFF1B1259),
    secondary = Color(0xFF6B5E8A),
    background = Color(0xFFFAF8FF),
    surface = Color(0xFFFAF8FF),
    surfaceVariant = Color(0xFFE8E3F2),
    error = Color(0xFFBA1A1A),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFC7BFFF),
    onPrimary = Color(0xFF2D2182),
    primaryContainer = Color(0xFF443AA8),
    onPrimaryContainer = Color(0xFFE5E0FF),
    secondary = Color(0xFFCDC1EA),
    background = Color(0xFF131218),
    surface = Color(0xFF131218),
    surfaceVariant = Color(0xFF48454F),
    error = Color(0xFFFFB4AB),
)

/** 中文正文排版：略大的行距，并开启中文标点避头尾的断行策略。 */
val ProseTextStyle = TextStyle(
    fontFamily = FontFamily.Default,
    fontSize = 17.sp,
    lineHeight = 29.sp,
    letterSpacing = 0.2.sp,
    lineBreak = LineBreak.Paragraph,
)

private val AppTypography = Typography()

@Composable
fun VnssTheme(
    themeMode: ThemeMode = ThemeMode.SYSTEM,
    fontScale: Float = 1.0f,
    content: @Composable () -> Unit,
) {
    val dark = when (themeMode) {
        ThemeMode.SYSTEM -> isSystemInDarkTheme()
        ThemeMode.LIGHT -> false
        ThemeMode.DARK -> true
    }
    val density = LocalDensity.current
    val scaled = Density(density.density, density.fontScale * fontScale.coerceIn(0.8f, 1.6f))
    CompositionLocalProvider(LocalDensity provides scaled) {
        MaterialTheme(
            colorScheme = if (dark) DarkColors else LightColors,
            typography = AppTypography,
            content = content,
        )
    }
}
