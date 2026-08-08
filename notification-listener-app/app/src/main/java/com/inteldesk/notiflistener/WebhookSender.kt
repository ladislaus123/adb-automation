package com.inteldesk.notiflistener

import android.util.Log
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

object WebhookSender {
    private const val TAG = "WebhookSender"
    private const val CONNECT_TIMEOUT_MS = 10_000
    private const val READ_TIMEOUT_MS = 10_000

    fun postEvent(
        serverUrl: String,
        apiKey: String,
        payloadJson: String,
        mediaBytes: ByteArray?,
        mediaMimeType: String?,
    ): Boolean {
        val boundary = "----NotifListener${UUID.randomUUID()}"
        val url = URL(serverUrl.trimEnd('/') + "/api/notifications/ingest")
        val connection = url.openConnection() as HttpURLConnection

        return try {
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.connectTimeout = CONNECT_TIMEOUT_MS
            connection.readTimeout = READ_TIMEOUT_MS
            connection.setRequestProperty("X-API-Key", apiKey)
            connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")

            connection.outputStream.use { out ->
                writeFormField(out, boundary, "payload", payloadJson)
                if (mediaBytes != null) {
                    writeFormFile(
                        out,
                        boundary,
                        "media",
                        "media.bin",
                        mediaMimeType ?: "application/octet-stream",
                        mediaBytes,
                    )
                }
                out.write("--$boundary--\r\n".toByteArray(Charsets.UTF_8))
            }

            val code = connection.responseCode
            val ok = code in 200..299
            if (!ok) {
                Log.w(TAG, "Webhook ingest returned HTTP $code")
            }
            ok
        } catch (t: Throwable) {
            Log.w(TAG, "Failed to forward notification event", t)
            false
        } finally {
            connection.disconnect()
        }
    }

    private fun writeFormField(out: OutputStream, boundary: String, name: String, value: String) {
        out.write("--$boundary\r\n".toByteArray(Charsets.UTF_8))
        out.write("Content-Disposition: form-data; name=\"$name\"\r\n".toByteArray(Charsets.UTF_8))
        out.write("Content-Type: application/json; charset=UTF-8\r\n\r\n".toByteArray(Charsets.UTF_8))
        out.write(value.toByteArray(Charsets.UTF_8))
        out.write("\r\n".toByteArray(Charsets.UTF_8))
    }

    private fun writeFormFile(
        out: OutputStream,
        boundary: String,
        name: String,
        filename: String,
        mimeType: String,
        bytes: ByteArray,
    ) {
        out.write("--$boundary\r\n".toByteArray(Charsets.UTF_8))
        out.write(
            "Content-Disposition: form-data; name=\"$name\"; filename=\"$filename\"\r\n".toByteArray(Charsets.UTF_8),
        )
        out.write("Content-Type: $mimeType\r\n\r\n".toByteArray(Charsets.UTF_8))
        out.write(bytes)
        out.write("\r\n".toByteArray(Charsets.UTF_8))
    }
}
