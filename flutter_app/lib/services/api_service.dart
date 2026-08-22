import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/models.dart';

class ApiService {
  static const String _defaultBaseUrl = 'http://127.0.0.1:8000';
  String baseUrl;
  String? _token;

  ApiService({this.baseUrl = _defaultBaseUrl});

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString('access_token');
    baseUrl = prefs.getString('base_url') ?? _defaultBaseUrl;
  }

  bool get isAuthenticated => _token != null && _token!.isNotEmpty;

  Map<String, String> _headers({bool isForm = false}) {
    final headers = <String, String>{
      'Accept': 'application/json',
    };
    if (isForm) {
      headers['Content-Type'] = 'application/x-www-form-urlencoded';
    } else {
      headers['Content-Type'] = 'application/json';
    }
    if (_token != null) {
      headers['Authorization'] = 'Bearer $_token';
    }
    return headers;
  }

  Future<bool> login(String username, String password) async {
    try {
      final uri = Uri.parse('$baseUrl/auth/token');
      final response = await http.post(
        uri,
        headers: _headers(isForm: true),
        body: {'username': username, 'password': password},
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        _token = data['access_token'];
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString('access_token', _token!);
        await prefs.setString('username', username);
        return true;
      }
      return false;
    } catch (e) {
      return false;
    }
  }

  Future<void> logout() async {
    _token = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('access_token');
    await prefs.remove('username');
  }

  Future<PortfolioResponse> getPortfolio() async {
    final uri = Uri.parse('$baseUrl/portfolio/positions');
    final response = await http.get(uri, headers: _headers());
    if (response.statusCode == 200) {
      return PortfolioResponse.fromJson(jsonDecode(response.body));
    }
    throw Exception('Failed to fetch portfolio: ${response.statusCode}');
  }

  Future<List<SignalItem>> getSignals() async {
    final uri = Uri.parse('$baseUrl/signals/latest');
    final response = await http.get(uri, headers: _headers());
    if (response.statusCode == 200) {
      final list = jsonDecode(response.body) as List<dynamic>;
      return list.map((e) => SignalItem.fromJson(e)).toList();
    }
    throw Exception('Failed to fetch signals: ${response.statusCode}');
  }

  Future<List<AuditBlockItem>> getAuditLog({int page = 1, int limit = 50}) async {
    final uri = Uri.parse('$baseUrl/audit/log?page=$page&limit=$limit');
    final response = await http.get(uri, headers: _headers());
    if (response.statusCode == 200) {
      final list = jsonDecode(response.body) as List<dynamic>;
      return list.map((e) => AuditBlockItem.fromJson(e)).toList();
    }
    throw Exception('Failed to fetch audit log: ${response.statusCode}');
  }

  Future<String> getEngineMode() async {
    final uri = Uri.parse('$baseUrl/engine/mode');
    final response = await http.get(uri, headers: _headers());
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data['mode'] ?? 'PAPER';
    }
    throw Exception('Failed to get engine mode: ${response.statusCode}');
  }

  Future<Map<String, dynamic>> setEngineMode(String mode) async {
    final uri = Uri.parse('$baseUrl/engine/mode');
    final response = await http.post(
      uri,
      headers: _headers(),
      body: jsonEncode({'mode': mode.toUpperCase()}),
    );
    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }
    throw Exception('Failed to set engine mode: ${response.statusCode} - ${response.body}');
  }
}
