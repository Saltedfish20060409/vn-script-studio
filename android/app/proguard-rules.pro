# kotlinx.serialization：保留生成的 serializer
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt
-keepclassmembers class kotlinx.serialization.json.** { *** Companion; }
-keepclasseswithmembers class kotlinx.serialization.json.** { kotlinx.serialization.KSerializer serializer(...); }
-keep,includedescriptorclasses class com.vnss.**$$serializer { *; }
-keepclassmembers class com.vnss.** { *** Companion; }
-keepclasseswithmembers class com.vnss.** { kotlinx.serialization.KSerializer serializer(...); }

# Retrofit 接口方法的泛型签名
-keepattributes Signature, Exceptions
-keep,allowobfuscation interface com.vnss.core.network.api.*
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**

# security-crypto → Tink 的可选依赖（运行时不会走到），R8 对缺失类会报错而不是警告
-dontwarn com.google.errorprone.annotations.**
-dontwarn javax.annotation.**
-dontwarn com.google.api.client.**
-dontwarn org.joda.time.**

# 崩溃栈可读
-keepattributes SourceFile, LineNumberTable
-renamesourcefileattribute SourceFile
