/// Data models for the AI Trading Companion app.

class PositionItem {
  final String symbol;
  final String assetClass;
  final double weight;
  final String weightPct;
  final double quantity;
  final double entryPrice;

  PositionItem({
    required this.symbol,
    required this.assetClass,
    required this.weight,
    required this.weightPct,
    required this.quantity,
    required this.entryPrice,
  });

  factory PositionItem.fromJson(Map<String, dynamic> json) {
    return PositionItem(
      symbol: json['symbol'] ?? '',
      assetClass: json['asset_class'] ?? 'crypto',
      weight: (json['weight'] as num?)?.toDouble() ?? 0.0,
      weightPct: json['weight_pct'] ?? '0.00%',
      quantity: (json['quantity'] as num?)?.toDouble() ?? 0.0,
      entryPrice: (json['entry_price'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class RiskMetricsData {
  final double cvar95;
  final double cvar99;
  final double volatility;
  final double var95;
  final double var99;

  RiskMetricsData({
    required this.cvar95,
    required this.cvar99,
    required this.volatility,
    required this.var95,
    required this.var99,
  });

  factory RiskMetricsData.fromJson(Map<String, dynamic> json) {
    return RiskMetricsData(
      cvar95: (json['cvar_95'] as num?)?.toDouble() ?? 0.0,
      cvar99: (json['cvar_99'] as num?)?.toDouble() ?? 0.0,
      volatility: (json['volatility'] as num?)?.toDouble() ?? 0.0,
      var95: (json['var_95'] as num?)?.toDouble() ?? 0.0,
      var99: (json['var_99'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class PortfolioResponse {
  final List<PositionItem> positions;
  final RiskMetricsData riskMetrics;
  final int totalAssets;
  final String timestamp;

  PortfolioResponse({
    required this.positions,
    required this.riskMetrics,
    required this.totalAssets,
    required this.timestamp,
  });

  factory PortfolioResponse.fromJson(Map<String, dynamic> json) {
    final list = (json['positions'] as List<dynamic>? ?? [])
        .map((e) => PositionItem.fromJson(e as Map<String, dynamic>))
        .toList();
    final risk = RiskMetricsData.fromJson(
        json['risk_metrics'] as Map<String, dynamic>? ?? {});
    return PortfolioResponse(
      positions: list,
      riskMetrics: risk,
      totalAssets: json['total_assets'] ?? list.length,
      timestamp: json['timestamp'] ?? '',
    );
  }
}

class SignalItem {
  final String symbol;
  final String direction;
  final double confidence;
  final double? riskScore;
  final String source;
  final String createdAt;

  SignalItem({
    required this.symbol,
    required this.direction,
    required this.confidence,
    this.riskScore,
    required this.source,
    required this.createdAt,
  });

  factory SignalItem.fromJson(Map<String, dynamic> json) {
    return SignalItem(
      symbol: json['symbol'] ?? '',
      direction: json['direction'] ?? 'neutral',
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
      riskScore: (json['risk_score'] as num?)?.toDouble(),
      source: json['source'] ?? 'ai_desk',
      createdAt: json['created_at'] ?? '',
    );
  }
}

class AuditBlockItem {
  final String txId;
  final int blockIndex;
  final String eventType;
  final String blockHash;
  final String createdAt;

  AuditBlockItem({
    required this.txId,
    required this.blockIndex,
    required this.eventType,
    required this.blockHash,
    required this.createdAt,
  });

  factory AuditBlockItem.fromJson(Map<String, dynamic> json) {
    return AuditBlockItem(
      txId: json['tx_id'] ?? '',
      blockIndex: json['block_index'] ?? 0,
      eventType: json['event_type'] ?? 'unknown',
      blockHash: json['block_hash'] ?? '',
      createdAt: json['created_at'] ?? '',
    );
  }
}
