package com.inteldesk.notiflistener

import android.content.Context
import android.content.SharedPreferences

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
}
