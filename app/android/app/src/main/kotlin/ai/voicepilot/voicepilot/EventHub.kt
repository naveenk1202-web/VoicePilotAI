package ai.voicepilot.voicepilot

import android.os.Handler
import android.os.Looper
import org.json.JSONObject

/**
 * Passes events from [ListeningService] to the Flutter UI when it is open.
 * Each event is a JSON string; with no screen attached, events are dropped.
 */
object EventHub {
    private val mainHandler = Handler(Looper.getMainLooper())

    @Volatile
    var listener: ((String) -> Unit)? = null

    fun emit(json: String) {
        mainHandler.post { listener?.invoke(json) }
    }

    fun emitState(listening: Boolean) {
        emit(JSONObject().put("type", "state").put("listening", listening).toString())
    }

    fun emitError(message: String) {
        emit(JSONObject().put("type", "error").put("message", message).toString())
    }
}
