package com.vnss.core.designsystem

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.LineBreak
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import com.vnss.core.model.ThemeMode

/** 与网页端 `globals.css` 对齐的品牌色：日间 Klein 蓝，夜间绯红。 */
object VnssColors {
    val Klein = Color(0xFF002FA7)
    val KleinDeep = Color(0xFF0A4BD0)
    val Ink = Color(0xFF0A0E1A)
    val InkSoft = Color(0xFF4A5568)
    val Paper = Color(0xFFF4F6FA)
    val PaperDeep = Color(0xFFE6EBF4)
    val Line = Color(0xFF1A2338)
    val Crimson = Color(0xFFE11D48)
    val NightPaper = Color(0xFF0A0507)
    val NightInk = Color(0xFFFFE8EC)
    val NightLine = Color(0xFF4A1824)
    val Ok = Color(0xFF0F766E)
    val Danger = Color(0xFFBE123C)
}

private val LightColors = lightColorScheme(
    primary = VnssColors.Klein,
    onPrimary = Color(0xFFF8FAFC),
    primaryContainer = Color(0xFFD6E0F7),
    onPrimaryContainer = VnssColors.Ink,
    secondary = VnssColors.KleinDeep,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE8EEF8),
    onSecondaryContainer = VnssColors.Ink,
    tertiary = Color(0xFF0F766E),
    background = VnssColors.Paper,
    onBackground = VnssColors.Ink,
    surface = VnssColors.Paper,
    onSurface = VnssColors.Ink,
    surfaceVariant = VnssColors.PaperDeep,
    onSurfaceVariant = VnssColors.InkSoft,
    outline = VnssColors.Line.copy(alpha = 0.35f),
    error = VnssColors.Danger,
    onError = Color.White,
)

private val DarkColors = darkColorScheme(
    primary = VnssColors.Crimson,
    onPrimary = Color(0xFFFFF5F7),
    primaryContainer = Color(0xFF4A1824),
    onPrimaryContainer = VnssColors.NightInk,
    secondary = Color(0xFFFF6B9D),
    onSecondary = VnssColors.NightPaper,
    secondaryContainer = Color(0xFF160A0F),
    onSecondaryContainer = VnssColors.NightInk,
    tertiary = Color(0xFF34D399),
    background = VnssColors.NightPaper,
    onBackground = VnssColors.NightInk,
    surface = VnssColors.NightPaper,
    onSurface = VnssColors.NightInk,
    surfaceVariant = Color(0xFF160A0F),
    onSurfaceVariant = Color(0xFFC49AA3),
    outline = VnssColors.NightLine,
    error = Color(0xFFFB7185),
    onError = VnssColors.NightPaper,
)

val VnssShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(20.dp),
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
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as? Activity)?.window ?: return@SideEffect
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = !dark
            WindowCompat.getInsetsController(window, view).isAppearanceLightNavigationBars = !dark
        }
    }
    CompositionLocalProvider(LocalDensity provides scaled) {
        MaterialTheme(
            colorScheme = if (dark) DarkColors else LightColors,
            typography = AppTypography,
            shapes = VnssShapes,
            content = content,
        )
    }
}
