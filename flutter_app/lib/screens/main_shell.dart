import 'package:flutter/material.dart';
import '../services/api_service.dart';
import 'portfolio_screen.dart';
import 'signals_screen.dart';
import 'audit_screen.dart';
import 'kill_switch_screen.dart';

class MainShell extends StatefulWidget {
  final ApiService apiService;
  final VoidCallback onLogout;

  const MainShell({
    super.key,
    required this.apiService,
    required this.onLogout,
  });

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int _currentIndex = 0;

  @override
  Widget build(BuildContext context) {
    final screens = [
      PortfolioScreen(apiService: widget.apiService),
      SignalsScreen(apiService: widget.apiService),
      AuditScreen(apiService: widget.apiService),
      KillSwitchScreen(apiService: widget.apiService, onLogout: widget.onLogout),
    ];

    return Scaffold(
      body: screens[_currentIndex],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (index) {
          setState(() {
            _currentIndex = index;
          });
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.pie_chart_outline),
            selectedIcon: Icon(Icons.pie_chart),
            label: 'Portfolio',
          ),
          NavigationDestination(
            icon: Icon(Icons.psychology_outlined),
            selectedIcon: Icon(Icons.psychology),
            label: 'AI Signals',
          ),
          NavigationDestination(
            icon: Icon(Icons.receipt_long_outlined),
            selectedIcon: Icon(Icons.receipt_long),
            label: 'Audit Log',
          ),
          NavigationDestination(
            icon: Icon(Icons.power_settings_new),
            selectedIcon: Icon(Icons.power_settings_new, color: Colors.red),
            label: 'Kill Switch',
          ),
        ],
      ),
    );
  }
}
