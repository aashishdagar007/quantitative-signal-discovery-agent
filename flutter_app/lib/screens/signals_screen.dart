import 'package:flutter/material.dart';
import '../models/models.dart';
import '../services/api_service.dart';

class SignalsScreen extends StatefulWidget {
  final ApiService apiService;

  const SignalsScreen({super.key, required this.apiService});

  @override
  State<SignalsScreen> createState() => _SignalsScreenState();
}

class _SignalsScreenState extends State<SignalsScreen> {
  late Future<List<SignalItem>> _signalsFuture;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  void _refresh() {
    setState(() {
      _signalsFuture = widget.apiService.getSignals();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('AI Desk Consensus Feed'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _refresh,
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: FutureBuilder<List<SignalItem>>(
        future: _signalsFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24.0),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.error_outline, size: 48, color: Colors.red),
                    const SizedBox(height: 12),
                    Text('Error: ${snapshot.error}', textAlign: TextAlign.center),
                    const SizedBox(height: 16),
                    FilledButton(onPressed: _refresh, child: const Text('Retry')),
                  ],
                ),
              ),
            );
          }

          final signals = snapshot.data ?? [];
          if (signals.isEmpty) {
            return const Center(
              child: Text('No AI signals recorded yet.'),
            );
          }

          return RefreshIndicator(
            onRefresh: () async => _refresh(),
            child: ListView.builder(
              padding: const EdgeInsets.all(16.0),
              itemCount: signals.length,
              itemBuilder: (context, index) {
                final sig = signals[index];
                return _buildSignalCard(context, sig);
              },
            ),
          );
        },
      ),
    );
  }

  Widget _buildSignalCard(BuildContext context, SignalItem sig) {
    final dir = sig.direction.toLowerCase();
    Color dirColor = Colors.grey;
    IconData dirIcon = Icons.remove;
    if (dir == 'long') {
      dirColor = Colors.green;
      dirIcon = Icons.trending_up;
    } else if (dir == 'short') {
      dirColor = Colors.red;
      dirIcon = Icons.trending_down;
    }

    return Card(
      margin: const EdgeInsets.only(bottom: 12.0),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  sig.symbol,
                  style: const TextStyle(fontSize: 17, fontWeight: FontWeight.bold),
                ),
                const Spacer(),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: dirColor.withAlpha(30),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: dirColor),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(dirIcon, size: 16, color: dirColor),
                      const SizedBox(width: 4),
                      Text(
                        sig.direction.toUpperCase(),
                        style: TextStyle(
                          color: dirColor,
                          fontWeight: FontWeight.bold,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                _buildChip(
                  Icons.psychology_outlined,
                  'Confidence: ${sig.confidence.toStringAsFixed(1)}%',
                ),
                const SizedBox(width: 8),
                if (sig.riskScore != null)
                  _buildChip(
                    Icons.security_outlined,
                    'CVaR: ${sig.riskScore!.toStringAsFixed(4)}',
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'Source: ${sig.source}',
                  style: TextStyle(fontSize: 12, color: Colors.grey[600]),
                ),
                Text(
                  sig.createdAt.split('T').first,
                  style: TextStyle(fontSize: 12, color: Colors.grey[500]),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildChip(IconData icon, String label) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.grey[100],
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: Colors.grey[700]),
          const SizedBox(width: 4),
          Text(label, style: TextStyle(fontSize: 12, color: Colors.grey[800])),
        ],
      ),
    );
  }
}
