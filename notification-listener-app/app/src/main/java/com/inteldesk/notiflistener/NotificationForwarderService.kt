package com.inteldesk.notiflistener

import android.app.Notification
import android.content.SharedPreferences
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class NotificationForwarderService : NotificationListenerService() {

    private lateinit var executor: ExecutorService
    private lateinit var prefs: SharedPreferences

    companion object {
        private const val TAG = "NotifForwarder"
        private val WATCHED_PACKAGES = setOf("com.whatsapp", "com.whatsapp.w4b")
    }

    override fun onCreate() {
        super.onCreate()
        executor = Executors.newSingleThreadExecutor()
        prefs = Prefs.get(this)
    }

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName !in WATCHED_PACKAGES) return

        val serverUrl = Prefs.serverUrl(prefs)
        val apiKey = Prefs.apiKey(prefs)
        if (serverUrl.isBlank() || apiKey.isBlank()) {
            Log.w(TAG, "Server URL / API key not configured, dropping notification")
            return
        }
        val deviceLabel = Prefs.deviceLabel(prefs)

        val extras = sbn.notification.extras
        val messages = extractMessages(extras)
        val conversationTitle = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()
            ?: extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE)?.toString()

        val payloadMessages = JSONArray()
        var mediaBytes: ByteArray? = null
        var mediaMimeType: String? = null

        if (messages.isNotEmpty()) {
            for (message in messages) {
                val entry = JSONObject()
                entry.put("sender", messageSender(message) ?: JSONObject.NULL)
                entry.put("text", message.text?.toString() ?: "")
                entry.put("timestamp_ms", message.timestamp)

                val dataUri = message.dataUri
                entry.put("has_media", dataUri != null)
                entry.put("mime_type", message.dataMimeType ?: JSONObject.NULL)
                payloadMessages.put(entry)

                if (dataUri != null && mediaBytes == null) {
                    mediaBytes = readUriBytes(dataUri)
                    mediaMimeType = message.dataMimeType
                }
            }
        } else {
            val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()
                ?: extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()
                ?: ""
            val entry = JSONObject()
            entry.put("sender", conversationTitle ?: JSONObject.NULL)
            entry.put("text", text)
            entry.put("timestamp_ms", sbn.postTime)
            entry.put("has_media", false)
            entry.put("mime_type", JSONObject.NULL)
            payloadMessages.put(entry)
        }

        val payload = JSONObject()
        payload.put("device_label", deviceLabel)
        payload.put("package", sbn.packageName)
        payload.put("conversation_title", conversationTitle ?: JSONObject.NULL)
        payload.put("post_time_ms", sbn.postTime)
        payload.put("messages", payloadMessages)

        val payloadJson = payload.toString()
        val finalMediaBytes = mediaBytes
        val finalMediaMimeType = mediaMimeType

        executor.execute {
            try {
                WebhookSender.postEvent(serverUrl, apiKey, payloadJson, finalMediaBytes, finalMediaMimeType)
            } catch (t: Throwable) {
                Log.w(TAG, "Failed to forward notification", t)
            }
        }
    }

    private fun messageSender(message: Notification.MessagingStyle.Message): String? {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            message.senderPerson?.name?.toString() ?: legacySender(message)
        } else {
            legacySender(message)
        }
    }

    @Suppress("DEPRECATION")
    private fun legacySender(message: Notification.MessagingStyle.Message): String? = message.sender?.toString()

    @Suppress("DEPRECATION")
    private fun extractMessages(extras: Bundle): List<Notification.MessagingStyle.Message> {
        return try {
            val parcelableArray = extras.getParcelableArray(Notification.EXTRA_MESSAGES) ?: return emptyList()
            Notification.MessagingStyle.Message.getMessagesFromBundleArray(parcelableArray).toList()
        } catch (t: Throwable) {
            Log.w(TAG, "Could not parse MessagingStyle messages", t)
            emptyList()
        }
    }

    private fun readUriBytes(uri: Uri): ByteArray? {
        return try {
            contentResolver.openInputStream(uri)?.use { it.readBytes() }
        } catch (t: Throwable) {
            Log.w(TAG, "Could not read attached media for $uri", t)
            null
        }
    }
}
