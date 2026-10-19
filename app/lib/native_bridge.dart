import 'dart:convert';

import 'package:flutter/services.dart';

/// Settings and state held by the native Android side.
class NativeState {
  const NativeState({
    required this.listening,
    required this.voiceAssist,
    required this.backendUrl,
    required this.appToken,
  });

  final bool listening;
  final bool voiceAssist;
  final String backendUrl;
  final String appToken;

  factory NativeState.fromMap(Map<Object?, Object?> map) => NativeState(
    listening: map['listening'] as bool? ?? false,
    voiceAssist: map['voiceAssist'] as bool? ?? true,
    backendUrl: map['backendUrl'] as String? ?? '',
    appToken: map['appToken'] as String? ?? '',
  );
}

/// Talks to the Kotlin code in MainActivity and ListeningService.
class NativeBridge {
  NativeBridge({MethodChannel? control, EventChannel? events})
    : _control = control ?? const MethodChannel('voicepilot/control'),
      _events = events ?? const EventChannel('voicepilot/events');

  final MethodChannel _control;
  final EventChannel _events;

  Future<NativeState> getState() async {
    final map = await _control.invokeMapMethod<Object?, Object?>('getState');
    return NativeState.fromMap(map ?? const {});
  }

  /// Returns false if the user denied microphone permission.
  Future<bool> startListening() async =>
      await _control.invokeMethod<bool>('startListening') ?? false;

  Future<void> stopListening() => _control.invokeMethod<void>('stopListening');

  Future<void> setVoiceAssist(bool enabled) =>
      _control.invokeMethod<void>('setVoiceAssist', {'enabled': enabled});

  Future<void> saveConfig({
    required String backendUrl,
    required String appToken,
  }) => _control.invokeMethod<void>('saveConfig', {
    'backendUrl': backendUrl,
    'appToken': appToken,
  });

  /// Events from the listening service, decoded from JSON.
  Stream<Map<String, dynamic>> events() => _events.receiveBroadcastStream().map(
    (raw) => jsonDecode(raw as String) as Map<String, dynamic>,
  );
}
