package com.vnss.core.network

import okhttp3.Headers
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RefreshCookieTest {
    @Test
    fun parsesNameValueBeforeAttributes() {
        val raw = "vnss_refresh=abc.def.ghi; Path=/api/v1/auth/refresh; HttpOnly; SameSite=Strict"
        assertEquals("abc.def.ghi", RefreshCookie.parse(raw))
    }

    @Test
    fun ignoresOtherCookies() {
        assertNull(RefreshCookie.parse("session=xyz; Path=/"))
    }

    @Test
    fun fromHeadersPicksRefresh() {
        val headers = Headers.Builder()
            .add("Set-Cookie", "other=1; Path=/")
            .add("Set-Cookie", "vnss_refresh=token123; Path=/api/v1/auth/refresh; HttpOnly")
            .build()
        assertEquals("token123", RefreshCookie.fromHeaders(headers))
    }
}
