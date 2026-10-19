package ai.voicepilot.voicepilot

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import java.util.concurrent.TimeUnit

/**
 * Foreground service that owns the microphone and the connection to the
 * backend, so listening keeps going after the app's screen is closed or
 * swiped away. It stops only when the user turns listening off (in the app
 * or from the notification) or force-stops the app.
 */
class ListeningService : Service() {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .build()

    private lateinit var prefs: AppPrefs
    private var socket: WebSocket? = null
    @Volatile private var socketReady = false
    private var captureThread: Thread? = null
    @Volatile private var capturing = false
    private var reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS

    override fun onCreate() {
        super.onCreate()
        prefs = AppPrefs(this)
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_REFRESH -> {
                if (isRunning) notificationManager().notify(NOTIFICATION_ID, buildNotification())
                return START_NOT_STICKY
            }
        }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            EventHub.emitError("Microphone permission is needed to listen.")
            stopSelf()
            return START_NOT_STICKY
        }

        ServiceCompat.startForeground(
            this,
            NOTIFICATION_ID,
            buildNotification(),
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0,
        )
        if (!isRunning) {
            isRunning = true
            EventHub.emitState(true)
            connect()
            startCapture()
        }
        // Not sticky: Android 14+ does not allow the microphone to be restarted
        // from the background, so a system restart would fail anyway.
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        isRunning = false
        capturing = false
        captureThread?.join(500)
        captureThread = null
        mainHandler.removeCallbacksAndMessages(null)
        socket?.send("""{"type":"stop"}""")
        socket?.close(1000, "listening turned off")
        socket = null
        socketReady = false
        client.dispatcher.executorService.shutdown()
        EventHub.emitState(false)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun connect() {
        val request = Request.Builder()
            .url(prefs.backendUrl)
            .header("Authorization", "Bearer ${prefs.appToken}")
            .build()
        socket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                socketReady = true
                reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                EventHub.emit(text)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                handleDisconnect(webSocket, null)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                handleDisconnect(webSocket, t.message ?: "connection failed")
            }
        })
    }

    private fun handleDisconnect(webSocket: WebSocket, error: String?) {
        mainHandler.post {
            if (webSocket != socket) return@post
            socketReady = false
            if (!isRunning) return@post
            if (error != null) EventHub.emitError("Backend connection lost: $error. Retrying.")
            mainHandler.postDelayed({ if (isRunning) connect() }, reconnectDelayMs)
            reconnectDelayMs = (reconnectDelayMs * 2).coerceAtMost(MAX_RECONNECT_DELAY_MS)
        }
    }

    private fun startCapture() {
        capturing = true
        captureThread = Thread({ captureLoop() }, "voicepilot-mic").also { it.start() }
    }

    private fun captureLoop() {
        val minBuffer = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL, ENCODING)
        val recorder = try {
            AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, SAMPLE_RATE, CHANNEL, ENCODING, maxOf(minBuffer, CHUNK_BYTES * 4))
        } catch (e: SecurityException) {
            EventHub.emitError("Microphone permission is needed to listen.")
            mainHandler.post { stopSelf() }
            return
        }
        if (recorder.state != AudioRecord.STATE_INITIALIZED) {
            recorder.release()
            EventHub.emitError("Could not open the microphone.")
            mainHandler.post { stopSelf() }
            return
        }

        val buffer = ByteArray(CHUNK_BYTES)
        recorder.startRecording()
        try {
            while (capturing) {
                val read = recorder.read(buffer, 0, buffer.size)
                if (read <= 0) continue
                val ws = socket
                // Drop audio while disconnected or when the network is too slow
                // to keep up, rather than building an ever-growing backlog.
                if (socketReady && ws != null && ws.queueSize() < MAX_QUEUED_BYTES) {
                    ws.send(buffer.toByteString(0, read))
                }
            }
        } finally {
            recorder.stop()
            recorder.release()
        }
    }

    private fun buildNotification(): Notification {
        val openApp = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this, 1,
            Intent(this, ListeningService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val voiceAssist = if (prefs.voiceAssist) "Voice assist on" else "Voice assist off"
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("VoicePilot is listening")
            .setContentText(voiceAssist)
            .setOngoing(true)
            .setContentIntent(openApp)
            .addAction(0, "Stop listening", stop)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(CHANNEL_ID, "Listening", NotificationManager.IMPORTANCE_LOW).apply {
            description = "Shown while VoicePilot is listening"
        }
        notificationManager().createNotificationChannel(channel)
    }

    private fun notificationManager() = getSystemService(NotificationManager::class.java)

    companion object {
        @Volatile
        var isRunning = false
            private set

        private const val ACTION_STOP = "ai.voicepilot.action.STOP"
        private const val ACTION_REFRESH = "ai.voicepilot.action.REFRESH"
        private const val CHANNEL_ID = "listening"
        private const val NOTIFICATION_ID = 1

        private const val SAMPLE_RATE = 16_000
        private const val CHANNEL = AudioFormat.CHANNEL_IN_MONO
        private const val ENCODING = AudioFormat.ENCODING_PCM_16BIT
        // 100 ms of 16 kHz, 16-bit mono audio.
        private const val CHUNK_BYTES = 3_200
        private const val MAX_QUEUED_BYTES = 256L * 1024
        private const val INITIAL_RECONNECT_DELAY_MS = 1_000L
        private const val MAX_RECONNECT_DELAY_MS = 30_000L

        fun start(context: Context) {
            ContextCompat.startForegroundService(context, Intent(context, ListeningService::class.java))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, ListeningService::class.java))
        }

        fun refreshNotification(context: Context) {
            if (isRunning) {
                context.startService(Intent(context, ListeningService::class.java).setAction(ACTION_REFRESH))
            }
        }
    }
}
