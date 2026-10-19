package ai.voicepilot.voicepilot

import android.content.Context

/**
 * Settings shared by the Flutter UI and [ListeningService]. Kept natively so
 * the service can read them after the app's screen is closed.
 */
class AppPrefs(context: Context) {
    private val prefs = context.getSharedPreferences("voicepilot", Context.MODE_PRIVATE)

    var backendUrl: String
        get() = prefs.getString(KEY_BACKEND_URL, DEFAULT_BACKEND_URL) ?: DEFAULT_BACKEND_URL
        set(value) = prefs.edit().putString(KEY_BACKEND_URL, value).apply()

    var appToken: String
        get() = prefs.getString(KEY_APP_TOKEN, "") ?: ""
        set(value) = prefs.edit().putString(KEY_APP_TOKEN, value).apply()

    var voiceAssist: Boolean
        get() = prefs.getBoolean(KEY_VOICE_ASSIST, true)
        set(value) = prefs.edit().putBoolean(KEY_VOICE_ASSIST, value).apply()

    companion object {
        // 10.0.2.2 is the host computer as seen from the Android emulator.
        const val DEFAULT_BACKEND_URL = "ws://10.0.2.2:8000/ws/session"
        private const val KEY_BACKEND_URL = "backend_url"
        private const val KEY_APP_TOKEN = "app_token"
        private const val KEY_VOICE_ASSIST = "voice_assist"
    }
}
