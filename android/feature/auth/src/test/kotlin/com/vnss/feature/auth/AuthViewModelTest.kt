package com.vnss.feature.auth

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AuthViewModelTest {

    @Test
    fun emailCheck() {
        assertTrue(AuthViewModel.looksLikeEmail("a@b.com"))
        assertTrue(AuthViewModel.looksLikeEmail(" user@example.cn "))
        assertFalse(AuthViewModel.looksLikeEmail("abc"))
        assertFalse(AuthViewModel.looksLikeEmail("a@b"))
        assertFalse(AuthViewModel.looksLikeEmail("a b@c.com"))
        assertFalse(AuthViewModel.looksLikeEmail("@c.com"))
    }

    @Test
    fun serverUrlNormalization() {
        assertEquals("", AuthViewModel.normalizeServerUrl("  "))
        assertEquals("https://example.com", AuthViewModel.normalizeServerUrl("example.com"))
        assertEquals("https://example.com", AuthViewModel.normalizeServerUrl("https://example.com/"))
        assertEquals("https://example.com", AuthViewModel.normalizeServerUrl("https://example.com/api/v1/"))
        assertEquals("http://10.0.2.2:8000", AuthViewModel.normalizeServerUrl("http://10.0.2.2:8000"))
    }
}
