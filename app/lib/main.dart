import 'dart:async';

import 'package:flutter/material.dart';

import 'native_bridge.dart';

void main() {
  runApp(VoicePilotApp(bridge: NativeBridge()));
}

class VoicePilotApp extends StatelessWidget {
  const VoicePilotApp({super.key, required this.bridge});

  final NativeBridge bridge;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'VoicePilot',
      theme: ThemeData(colorSchemeSeed: Colors.indigo, useMaterial3: true),
      darkTheme: ThemeData(
        colorSchemeSeed: Colors.indigo,
        brightness: Brightness.dark,
        useMaterial3: true,
      ),
      home: HomeScreen(bridge: bridge),
    );
  }
}

class TranscriptLine {
  const TranscriptLine(this.text, this.speaker);

  final String text;
  final int? speaker;
}

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.bridge});

  final NativeBridge bridge;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with WidgetsBindingObserver {
  static const _maxLines = 50;

  final _backendUrl = TextEditingController();
  final _appToken = TextEditingController();
  final List<TranscriptLine> _lines = [];
  StreamSubscription<Map<String, dynamic>>? _events;

  bool _loaded = false;
  bool _listening = false;
  bool _voiceAssist = true;
  String _interim = '';
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _events = widget.bridge.events().listen(_onEvent);
    _refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _events?.cancel();
    _backendUrl.dispose();
    _appToken.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Listening may have been stopped from the notification while away.
    if (state == AppLifecycleState.resumed) _refresh();
  }

  Future<void> _refresh() async {
    final state = await widget.bridge.getState();
    if (!mounted) return;
    setState(() {
      _listening = state.listening;
      _voiceAssist = state.voiceAssist;
      if (!_loaded) {
        _backendUrl.text = state.backendUrl;
        _appToken.text = state.appToken;
      }
      _loaded = true;
    });
  }

  void _onEvent(Map<String, dynamic> event) {
    setState(() {
      switch (event['type']) {
        case 'state':
          _listening = event['listening'] as bool? ?? false;
          if (!_listening) _interim = '';
        case 'ready':
          _error = null;
        case 'error':
          _error = event['message'] as String?;
        case 'transcript':
          final text = event['text'] as String? ?? '';
          if (event['is_final'] == true) {
            _interim = '';
            _lines.insert(0, TranscriptLine(text, event['speaker'] as int?));
            if (_lines.length > _maxLines) _lines.removeLast();
          } else {
            _interim = text;
          }
      }
    });
  }

  Future<void> _setListening(bool on) async {
    setState(() => _error = null);
    if (on) {
      await _saveConfig();
      final started = await widget.bridge.startListening();
      if (!started && mounted) {
        setState(() => _error = 'Microphone permission is needed to listen.');
      }
    } else {
      await widget.bridge.stopListening();
    }
  }

  Future<void> _setVoiceAssist(bool on) async {
    setState(() => _voiceAssist = on);
    await widget.bridge.setVoiceAssist(on);
  }

  Future<void> _saveConfig() => widget.bridge.saveConfig(
    backendUrl: _backendUrl.text.trim(),
    appToken: _appToken.text.trim(),
  );

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('VoicePilot')),
      body: !_loaded
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              children: [
                SwitchListTile(
                  key: const Key('listening-switch'),
                  title: const Text('Background listening'),
                  subtitle: const Text(
                    'Keeps listening after you close the app',
                  ),
                  value: _listening,
                  onChanged: _setListening,
                ),
                SwitchListTile(
                  key: const Key('voice-assist-switch'),
                  title: const Text('Voice assist'),
                  subtitle: const Text('Speak answers in your earphones'),
                  value: _voiceAssist,
                  onChanged: _setVoiceAssist,
                ),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text(
                      _error!,
                      style: TextStyle(color: theme.colorScheme.error),
                    ),
                  ),
                ExpansionTile(
                  title: const Text('Backend connection'),
                  children: [
                    TextField(
                      controller: _backendUrl,
                      decoration: const InputDecoration(
                        labelText: 'Backend URL',
                      ),
                      keyboardType: TextInputType.url,
                      onSubmitted: (_) => _saveConfig(),
                    ),
                    TextField(
                      controller: _appToken,
                      decoration: const InputDecoration(labelText: 'App token'),
                      obscureText: true,
                      onSubmitted: (_) => _saveConfig(),
                    ),
                    const SizedBox(height: 8),
                  ],
                ),
                const SizedBox(height: 16),
                Text('Live transcript', style: theme.textTheme.titleMedium),
                const SizedBox(height: 8),
                if (_interim.isNotEmpty)
                  Text(
                    _interim,
                    style: TextStyle(color: theme.colorScheme.outline),
                  ),
                if (_lines.isEmpty && _interim.isEmpty)
                  Text(
                    _listening
                        ? 'Listening…'
                        : 'Turn on background listening to start.',
                    style: TextStyle(color: theme.colorScheme.outline),
                  ),
                for (final line in _lines)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Text(
                      line.speaker == null
                          ? line.text
                          : 'Speaker ${line.speaker}: ${line.text}',
                    ),
                  ),
              ],
            ),
    );
  }
}
