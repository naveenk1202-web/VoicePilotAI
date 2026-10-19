import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:voicepilot/main.dart';
import 'package:voicepilot/native_bridge.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const control = MethodChannel('voicepilot/control');
  const events = EventChannel('voicepilot/events');
  late List<MethodCall> calls;
  late bool listening;

  setUp(() {
    calls = [];
    listening = false;
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(control, (call) async {
      calls.add(call);
      switch (call.method) {
        case 'getState':
          return {
            'listening': listening,
            'voiceAssist': true,
            'backendUrl': 'ws://example.test/ws/session',
            'appToken': 'secret',
          };
        case 'startListening':
          listening = true;
          return true;
      }
      return null;
    });
    messenger.setMockStreamHandler(events, null);
  });

  testWidgets('shows both switches and the saved backend URL', (tester) async {
    await tester.pumpWidget(VoicePilotApp(bridge: NativeBridge()));
    await tester.pumpAndSettle();

    expect(find.text('Background listening'), findsOneWidget);
    expect(find.text('Voice assist'), findsOneWidget);
    await tester.tap(find.text('Backend connection'));
    await tester.pumpAndSettle();
    expect(find.text('ws://example.test/ws/session'), findsOneWidget);
  });

  testWidgets('turning listening on saves config then starts the service', (
    tester,
  ) async {
    await tester.pumpWidget(VoicePilotApp(bridge: NativeBridge()));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('listening-switch')));
    await tester.pumpAndSettle();

    final methods = calls.map((c) => c.method).toList();
    expect(methods, containsAllInOrder(['saveConfig', 'startListening']));
  });

  testWidgets('turning voice assist off is sent to native code', (
    tester,
  ) async {
    await tester.pumpWidget(VoicePilotApp(bridge: NativeBridge()));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('voice-assist-switch')));
    await tester.pumpAndSettle();

    final call = calls.lastWhere((c) => c.method == 'setVoiceAssist');
    expect(call.arguments, {'enabled': false});
  });

  testWidgets('shows final transcripts from the service', (tester) async {
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockStreamHandler(
      events,
      MockStreamHandler.inline(
        onListen: (args, sink) {
          sink.success(jsonEncode({'type': 'state', 'listening': true}));
          sink.success(
            jsonEncode({
              'type': 'transcript',
              'text': 'What time is the meeting?',
              'is_final': true,
              'speech_final': true,
              'speaker': 1,
            }),
          );
        },
      ),
    );

    await tester.pumpWidget(VoicePilotApp(bridge: NativeBridge()));
    await tester.pumpAndSettle();

    expect(find.text('Speaker 1: What time is the meeting?'), findsOneWidget);
  });
}
