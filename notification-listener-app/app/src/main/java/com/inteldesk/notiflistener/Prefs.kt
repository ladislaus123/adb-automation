package com.inteldesk.notiflistener

import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.provider.Settings

object Prefs {
    private const val FILE_NAME = "notif_forwarder_prefs"
    private const val KEY_SERVER_URL = "server_url"
    private const val KEY_API_KEY = "api_key"
    private const val KEY_DEVICE_LABEL = "device_label"

    fun get(context: Context): SharedPreferences =
        context.getSharedPreferences(FILE_NAME, Context.MODE_PRIVATE)

    fun serverUrl(prefs: SharedPreferences): String = prefs.getString(KEY_SERVER_URL, "") ?: ""

    fun apiKey(prefs: SharedPreferences): String = prefs.getString(KEY_API_KEY, "") ?: ""

    fun deviceLabel(prefs: SharedPreferences): String = prefs.getString(KEY_DEVICE_LABEL, "") ?: ""

    fun save(prefs: SharedPreferences, serverUrl: String, apiKey: String, deviceLabel: String) {
        prefs.edit()
            .putString(KEY_SERVER_URL, serverUrl)
            .putString(KEY_API_KEY, apiKey)
            .putString(KEY_DEVICE_LABEL, deviceLabel)
            .apply()
    }

    /**
     * Seeds server URL / API key (baked in at build time from BACKEND_URL /
     * ADB_AUTOMATION_API_KEY) and device label (the phone's own device name) the
     * first time the app runs, so the listener works right after notification
     * access is granted — no manual entry or Save tap required.
     */
    fun ensureDefaults(context: Context, prefs: SharedPreferences) {
        val editor = prefs.edit()
        var changed = false

        if (serverUrl(prefs).isBlank() && BuildConfig.DEFAULT_SERVER_URL.isNotBlank()) {
            editor.putString(KEY_SERVER_URL, BuildConfig.DEFAULT_SERVER_URL)
            changed = true
        }
        if (apiKey(prefs).isBlank() && BuildConfig.DEFAULT_API_KEY.isNotBlank()) {
            editor.putString(KEY_API_KEY, BuildConfig.DEFAULT_API_KEY)
            changed = true
        }
        if (deviceLabel(prefs).isBlank()) {
            editor.putString(KEY_DEVICE_LABEL, defaultDeviceName(context))
            changed = true
        }

        if (changed) editor.apply()
    }

    private fun defaultDeviceName(context: Context): String {
        val deviceName = Settings.Global.getString(context.contentResolver, Settings.Global.DEVICE_NAME)
        return deviceName?.takeIf { it.isNotBlank() } ?: Build.MODEL.orEmpty()
    }
}
