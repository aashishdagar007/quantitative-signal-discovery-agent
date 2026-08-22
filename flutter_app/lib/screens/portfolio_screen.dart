import 'package:flutter/material.dart';
import '../models/models.dart';
import '../services/api_service.dart';

class PortfolioScreen extends StatefulWidget {
  final ApiService apiService;

  const PortfolioScreen({super.key, required this.apiService});

  @override
  State<PortfolioScreen> createState() => _PortfolioScreenState();
}

class _PortfolioScreenState extends State<PortfolioScreen> {
  late Future<PortfolioResponse> _portfolioFuture;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  void _refresh() {
    setState(() {
      _portfolioFuture = widget.apiService.getPortfolio();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Portfolio Allocation (HRP)'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _refresh,
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: FutureBuilder<PortfolioResponse>(
        future: _portfolioFuture,
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

          final data = snapshot.data!;
          final risk = data.riskMetrics;

          return RefreshIndicator(
            onRefresh: () async => _refresh(),
            child: ListView(
              padding: const EdgeInsets.all(16.0),
              children: [
                // Risk Metrics Card
                Card(
                  elevation: 2,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  child: Padding(
                    padding: const EdgeInsets.all(16.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(Icons.shield_outlined, color: Colors.indigo),
                            const SizedBox(width: 8),
                            Text(
                              'Risk Controls & CVaR',
                              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ],
                        ),
                        const Divider(height: 24),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceAround,
                          children: [
                            _buildMetricItem(context, 'CVaR (95%)', '${(risk.cvar95 * 100).toStringAsFixed(2)}%'),
                            _buildMetricItem(context, 'CVaR (99%)', '${(risk.cvar99 * 100).toStringAsFixed(2)}%'),
                            _buildMetricItem(context, 'Vol (Ann.)', '${(risk.volatility * 100).toStringAsFixed(1)}%'),
                            _buildMetricItem(context, 'VaR (95%)', '${(risk.var95 * 100).toStringAsFixed(2)}%'),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),

                // Positions Header
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4.0),
                  child: Text(
                    'Asset Allocations (${data.totalAssets})',
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.bold,
                      color: Colors.grey[700],
                    ),
                  ),
                ),
                const SizedBox(height: 8),

                // Position Items
                ...data.positions.map((pos) => _buildPositionTile(context, pos)),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildMetricItem(BuildContext context, String label, String value) {
    return Column(
      children: [
        Text(value, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        const SizedBox(height: 4),
        Text(label, style: TextStyle(fontSize: 11, color: Colors.grey[600])),
      ],
    );
  }

  Widget _buildPositionTile(BuildContext context, PositionItem pos) {
    final isCrypto = pos.assetClass.toLowerCase() == 'crypto';
    return Card(
      margin: const EdgeInsets.only(bottom: 8.0),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: isCrypto ? Colors.orange[100] : Colors.blue[100],
          child: Icon(
            isCrypto ? Icons.currency_bitcoin : Icons.euro,
            color: isCrypto ? Colors.orange[800] : Colors.blue[800],
          ),
        ),
        title: Text(
          pos.symbol,
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
        subtitle: Text(
          pos.assetClass.toUpperCase(),
          style: TextStyle(fontSize: 12, color: Colors.grey[600]),
        ),
        trailing: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(
              pos.weightPct,
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.indigo),
            ),
            const SizedBox(height: 2),
            Text(
              'Weight: ${pos.weight.toStringAsFixed(3)}',
              style: TextStyle(fontSize: 11, color: Colors.grey[600]),
            ),
          ],
        ),
      ),
    );
  }
}
