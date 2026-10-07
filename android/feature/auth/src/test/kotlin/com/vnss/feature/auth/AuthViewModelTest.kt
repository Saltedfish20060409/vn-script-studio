package com.vnss.feature.auth

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

}
