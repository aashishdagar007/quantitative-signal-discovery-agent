import 'package:flutter/material.dart';
import '../services/api_service.dart';

class KillSwitchScreen extends StatefulWidget {
  final ApiService apiService;
  final VoidCallback onLogout;

  const KillSwitchScreen({
    super.key,
    required this.apiService,
    required this.onLogout,
  });

  @override
  State<KillSwitchScreen> createState() => _KillSwitchScreenState();
}

class _KillSwitchScreenState extends State<KillSwitchScreen> {
  String _currentMode = 'LOADING';
  bool _isLoading = false;
  String? _statusMessage;

  @override
  void initState() {
    super.initState();
    _fetchMode();
  }

  Future<void> _fetchMode() async {
    setState(() {
      _isLoading = true;
    });
    try {
      final mode = await widget.apiService.getEngineMode();
      if (mounted) {
        setState(() {
          _currentMode = mode;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _currentMode = 'ERROR';
          _isLoading = false;
          _statusMessage = 'Error: $e';
        });
      }
    }
  }

  Future<void> _toggleMode(String targetMode) async {
    // Double-confirmation dialog before destructive/state action
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Row(
          children: [
            Icon(
              targetMode == 'PAPER' ? Icons.warning_amber_rounded : Icons.flash_on,
              color: targetMode == 'PAPER' ? Colors.orange : Colors.red,
            ),
            const SizedBox(width: 8),
            Text('Confirm: Switch to $targetMode'),
          ],
        ),
        content: Text(
          targetMode == 'PAPER'
              ? 'EMERGENCY KILL SWITCH: This will immediately halt all live order routing and force the engine into simulated PAPER mode. All state changes are immutably recorded in the blockchain audit ledger.'
              : 'CAUTION: Switching to LIVE mode allows real orders to be placed on Binance and MT5 Forex brokers. Risk limits will be actively enforced.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: targetMode == 'PAPER' ? Colors.red : Colors.indigo,
            ),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(targetMode == 'PAPER' ? 'EMERGENCY STOP (PAPER)' : 'ACTIVATE LIVE'),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    setState(() {
      _isLoading = true;
      _statusMessage = null;
    });

    try {
      final result = await widget.apiService.setEngineMode(targetMode);
      if (mounted) {
        setState(() {
          _currentMode = result['mode'] ?? targetMode;
          _isLoading = false;
          _statusMessage = 'Engine mode updated to $_currentMode. Tx: ${result['tx_id'] ?? 'recorded'}';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _statusMessage = 'Failed to switch mode: $e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final isLive = _currentMode.toUpperCase() == 'LIVE';

    return Scaffold(
      appBar: AppBar(
        title: const Text('Emergency Kill Switch & Mode'),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Sign Out',
            onPressed: widget.onLogout,
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(24.0),
        children: [
          // Current Status Banner
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: isLive ? Colors.red[50] : Colors.green[50],
              borderRadius: BorderRadius.circular(16),
              border: Border.all(
                color: isLive ? Colors.red[300]! : Colors.green[300]!,
                width: 2,
              ),
            ),
            child: Column(
              children: [
                Icon(
                  isLive ? Icons.radio_button_checked : Icons.shield_outlined,
                  size: 48,
                  color: isLive ? Colors.red : Colors.green,
                ),
                const SizedBox(height: 12),
                Text(
                  'CURRENT ENGINE MODE: $_currentMode',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    color: isLive ? Colors.red[900] : Colors.green[900],
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  isLive
                      ? 'REAL orders actively routed to Binance & MetaTrader 5'
                      : 'Simulated mode — no live funds or venue orders sent',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 13,
                    color: isLive ? Colors.red[700] : Colors.green[700],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),

          if (_statusMessage != null) ...[
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.blue[50],
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.blue[200]!),
              ),
              child: Text(
                _statusMessage!,
                style: TextStyle(color: Colors.blue[900], fontSize: 13),
              ),
            ),
            const SizedBox(height: 20),
          ],

          // Kill Switch Button (Large, prominent)
          FilledButton.icon(
            onPressed: _isLoading ? null : () => _toggleMode('PAPER'),
            icon: const Icon(Icons.power_settings_new, size: 28),
            label: const Text(
              'KILL SWITCH -> FORCE PAPER MODE',
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold),
            ),
            style: FilledButton.styleFrom(
              backgroundColor: Colors.red[700],
              padding: const EdgeInsets.symmetric(vertical: 20),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            ),
          ),
          const SizedBox(height: 16),

          // Activate Live Button
          OutlinedButton.icon(
            onPressed: _isLoading ? null : () => _toggleMode('LIVE'),
            icon: const Icon(Icons.flash_on),
            label: const Text('SWITCH TO LIVE TRADING'),
            style: OutlinedButton.styleFrom(
              foregroundColor: Colors.indigo,
              side: const BorderSide(color: Colors.indigo, width: 1.5),
              padding: const EdgeInsets.symmetric(vertical: 16),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            ),
          ),
          const SizedBox(height: 24),

          // Audit trail notice
          Card(
            elevation: 0,
            color: Colors.grey[100],
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            child: const Padding(
              padding: EdgeInsets.all(16.0),
              child: Row(
                children: [
                  Icon(Icons.info_outline, color: Colors.grey, size: 20),
                  SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      'Every mode toggle is recorded with an Ed25519-signed state change in the tamper-evident SQLite Merkle chain.',
                      style: TextStyle(fontSize: 12, color: Colors.black87),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
