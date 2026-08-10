package com.inteldesk.notiflistener

import android.content.Intent
import android.content.SharedPreferences
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationManagerCompat

class MainActivity : AppCompatActivity() {

    private lateinit var prefs: SharedPreferences

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs.get(this)
        Prefs.ensureDefaults(this, prefs)

        val serverUrlInput = findViewById<EditText>(R.id.serverUrlInput)
        val apiKeyInput = findViewById<EditText>(R.id.apiKeyInput)
        val deviceLabelInput = findViewById<EditText>(R.id.deviceLabelInput)
        val saveButton = findViewById<Button>(R.id.saveButton)
        val openSettingsButton = findViewById<Button>(R.id.openSettingsButton)

        serverUrlInput.setText(Prefs.serverUrl(prefs))
        apiKeyInput.setText(Prefs.apiKey(prefs))
        deviceLabelInput.setText(Prefs.deviceLabel(prefs))

        saveButton.setOnClickListener {
            Prefs.save(
                prefs,
                serverUrlInput.text.toString().trim(),
                apiKeyInput.text.toString().trim(),
                deviceLabelInput.text.toString().trim(),
            )
            Toast.makeText(this, R.string.status_saved, Toast.LENGTH_SHORT).show()
        }

        openSettingsButton.setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }

        updateStatus()
    }

    override fun onResume() {
        super.onResume()
        updateStatus()
    }

    private fun updateStatus() {
        val statusText = findViewById<TextView>(R.id.statusText)
        val enabledPackages = NotificationManagerCompat.getEnabledListenerPackages(this)
        val granted = enabledPackages.contains(packageName)
        statusText.setText(if (granted) R.string.status_access_granted else R.string.status_access_denied)
    }
}
