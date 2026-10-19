package ai.voicepilot.voicepilot

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private lateinit var prefs: AppPrefs
    private var pendingStart: MethodChannel.Result? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        prefs = AppPrefs(this)
        val messenger = flutterEngine.dartExecutor.binaryMessenger

        MethodChannel(messenger, "voicepilot/control").setMethodCallHandler { call, result ->
            when (call.method) {
                "getState" -> result.success(
                    mapOf(
                        "listening" to ListeningService.isRunning,
                        "voiceAssist" to prefs.voiceAssist,
                        "backendUrl" to prefs.backendUrl,
                        "appToken" to prefs.appToken,
                    )
                )
                "saveConfig" -> {
                    prefs.backendUrl = call.argument<String>("backendUrl") ?: AppPrefs.DEFAULT_BACKEND_URL
                    prefs.appToken = call.argument<String>("appToken") ?: ""
                    result.success(null)
                }
                "setVoiceAssist" -> {
                    prefs.voiceAssist = call.argument<Boolean>("enabled") ?: true
                    ListeningService.refreshNotification(this)
                    result.success(null)
                }
                "startListening" -> startListening(result)
                "stopListening" -> {
                    ListeningService.stop(this)
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }

        EventChannel(messenger, "voicepilot/events").setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
                EventHub.listener = { json -> events.success(json) }
            }

            override fun onCancel(arguments: Any?) {
                EventHub.listener = null
            }
        })
    }

    private fun startListening(result: MethodChannel.Result) {
        val missing = requiredPermissions().filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isEmpty()) {
            ListeningService.start(this)
            result.success(true)
            return
        }
        pendingStart?.success(false)
        pendingStart = result
        ActivityCompat.requestPermissions(this, missing.toTypedArray(), PERMISSION_REQUEST)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != PERMISSION_REQUEST) return
        val result = pendingStart ?: return
        pendingStart = null
        // Only the microphone is essential; notifications are optional.
        val micGranted = ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        if (micGranted) ListeningService.start(this)
        result.success(micGranted)
    }

    private fun requiredPermissions(): List<String> {
        val permissions = mutableListOf(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions += Manifest.permission.POST_NOTIFICATIONS
        }
        return permissions
    }

    companion object {
        private const val PERMISSION_REQUEST = 1001
    }
}
