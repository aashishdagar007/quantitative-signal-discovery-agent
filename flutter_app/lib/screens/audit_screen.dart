import 'package:flutter/material.dart';
import '../models/models.dart';
import '../services/api_service.dart';

class AuditScreen extends StatefulWidget {
  final ApiService apiService;

  const AuditScreen({super.key, required this.apiService});

  @override
  State<AuditScreen> createState() => _AuditScreenState();
}

class _AuditScreenState extends State<AuditScreen> {
  late Future<List<AuditBlockItem>> _auditFuture;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  void _refresh() {
    setState(() {
      _auditFuture = widget.apiService.getAuditLog();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Blockchain Audit Trail'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _refresh,
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: FutureBuilder<List<AuditBlockItem>>(
        future: _auditFuture,
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

          final blocks = snapshot.data ?? [];
          if (blocks.isEmpty) {
            return const Center(
              child: Text('No audit blocks in ledger.'),
            );
          }

          return RefreshIndicator(
            onRefresh: () async => _refresh(),
            child: ListView.builder(
              padding: const EdgeInsets.all(16.0),
              itemCount: blocks.length,
              itemBuilder: (context, index) {
                final block = blocks[index];
                return _buildBlockCard(context, block);
              },
            ),
          );
        },
      ),
    );
  }

  Widget _buildBlockCard(BuildContext context, AuditBlockItem block) {
    Color typeColor = Colors.blueGrey;
    if (block.eventType == 'state_change') {
      typeColor = Colors.deepOrange;
    } else if (block.eventType == 'trade') {
      typeColor = Colors.teal;
    } else if (block.eventType == 'consensus') {
      typeColor = Colors.purple;
    }

    final hashSnippet = block.blockHash.length > 16
        ? '${block.blockHash.substring(0, 8)}...${block.blockHash.substring(block.blockHash.length - 8)}'
        : block.blockHash;

    return Card(
      margin: const EdgeInsets.only(bottom: 10.0),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: typeColor.withAlpha(40),
          child: Text(
            '#${block.blockIndex}',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.bold,
              color: typeColor,
            ),
          ),
        ),
        title: Row(
          children: [
            Text(
              block.eventType.toUpperCase(),
              style: TextStyle(
                fontWeight: FontWeight.bold,
                fontSize: 14,
                color: typeColor,
              ),
            ),
          ],
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 4),
            Text(
              'Hash: $hashSnippet',
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
            Text(
              'Tx: ${block.txId}',
              style: TextStyle(fontSize: 11, color: Colors.grey[600]),
            ),
          ],
        ),
        trailing: const Icon(Icons.verified_outlined, color: Colors.green, size: 20),
      ),
    );
  }
}
