import 'package:flutter/material.dart';
import 'screens/login_screen.dart';
import 'screens/main_shell.dart';
import 'services/api_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final apiService = ApiService();
  await apiService.init();
  runApp(TradingCompanionApp(apiService: apiService));
}

class TradingCompanionApp extends StatefulWidget {
  final ApiService apiService;

  const TradingCompanionApp({super.key, required this.apiService});

  @override
  State<TradingCompanionApp> createState() => _TradingCompanionAppState();
}

class _TradingCompanionAppState extends State<TradingCompanionApp> {
  bool _loggedIn = false;

  @override
  void initState() {
    super.initState();
    _loggedIn = widget.apiService.isAuthenticated;
  }

  void _onLoginSuccess() {
    setState(() {
      _loggedIn = true;
    });
  }

  void _onLogout() async {
    await widget.apiService.logout();
    setState(() {
      _loggedIn = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AI Trading Companion',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.indigo,
          brightness: Brightness.light,
        ),
      ),
      darkTheme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.indigo,
          brightness: Brightness.dark,
        ),
      ),
      themeMode: ThemeMode.system,
      home: _loggedIn
          ? MainShell(
              apiService: widget.apiService,
              onLogout: _onLogout,
            )
          : LoginScreen(
              apiService: widget.apiService,
              onLoginSuccess: _onLoginSuccess,
            ),
    );
  }
}
