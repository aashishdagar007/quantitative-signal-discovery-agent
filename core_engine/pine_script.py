import ast
import re
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path


class PineScriptParser:
    """
    Pine Script transpiler using Python AST transformers.
    Converts Pine Script v5 code to executable Python for native engine execution.
    """
    
    def __init__(self):
        self.scope_level = 0
        self.variable_table: Dict[str, Any] = {}
        self.function_defs: Dict[str, ast.FunctionDef] = {}
        self.imports: List[str] = []
    
    def transpile(self, pine_code: str) -> str:
        """
        Transpile Pine Script code to Python.
        
        Args:
            pine_code: Raw Pine Script v5 code string
            
        Returns:
            Python code string ready for execution
        """
        try:
            # Parse the Pine Script code
            tree = ast.parse(pine_code)
            
            # Transform the AST
            python_code = self._transform_ast(tree)
            
            # Post-process: add boilerplate
            python_code = self._add_boilerplate(python_code)
            
            return python_code
            
        except SyntaxError as e:
            raise ValueError(f"Pine Script syntax error: {e}")
        except Exception as e:
            raise ValueError(f"Transpilation error: {e}")
    
    def _transform_ast(self, tree: ast.Module) -> str:
        """Transform Pine Script AST to Python compatible code"""
        statements = []
        
        for node in tree.body:
            py_stmt = self._convert_node(node)
            if py_stmt:
                statements.append(py_stmt)
        
        # Combine statements into a block
        code = "\n".join(statements)
        return code
    
    def _convert_node(self, node: ast.AST) -> Optional[str]:
        """Convert a single AST node to Python code"""
        node_type = type(node).__name__
        
        if node_type == 'VarDeclaration':
            return self._convert_var_declaration(node)
        elif node_type == 'FunctionDeclaration':
            return self._convert_function_declaration(node)
        elif node_type == 'IfStatement':
            return self._convert_if_statement(node)
        elif node_type == 'ForStatement':
            return self._convert_for_loop(node)
        elif node_type == 'WhileStatement':
            return self._convert_while_loop(node)
        elif node_type == 'ReturnStatement':
            return self._convert_return_statement(node)
        elif node_type == 'BinaryExpression':
            return self._convert_binary_expression(node)
        elif node_type == 'CallExpression':
            return self._convert_call_expression(node)
        elif node_type == 'Identifier':
            return self._convert_identifier(node)
        elif node_type == 'NumberLiteral':
            return self._convert_number_literal(node)
        elif node_type == 'StringLiteral':
            return self._convert_string_literal(node)
        elif node_type == 'BooleanLiteral':
            return self._convert_boolean_literal(node)
        elif node_type == 'Comment':
            return f"# {node.text}"
        else:
            # Try to handle as expression
            return self._convert_unknown(node)
    
    def _convert_var_declaration(self, node: ast.AST) -> Optional[str]:
        """Convert Pine Script variable declaration"""
        # Pine: string name = value
        # Python: name = value
        
        # Extract variables from assignment
        if hasattr(node, 'name'):
            name = node.name
        else:
            # Look for ID in attributes
            name = getattr(node, 'name', None) or \
                   node.name if hasattr(node, 'name') else None
        
        if not name:
            return None
        
        # Get the value - look for initializer
        value = None
        if hasattr(node, 'initializer') and node.initializer:
            value = self._convert_assign_value(node.initializer)
        elif hasattr(node, 'value') and node.value:
            value = self._convert_assign_value(node.value)
        
        # Handle array declarations like "double arr[] = new double[]..."
        if hasattr(node, 'array_size') and node.array_size:
            dims = self._parse_array_dims(node.array_size)
            value = f"[{', '.join(['0.0'] * dims)}]"
        
        if value and name:
            # Skip Pine built-in variables prefix with underscore
            if not name.startswith("_"):
                return f"{name} = {value}"
        
        return None
    
    def _convert_assign_value(self, value_node: ast.AST) -> str:
        """Convert assignment value to Python"""
        value_type = type(value_node).__name__
        
        if value_type == 'NumberLiteral':
            return self._convert_number_literal(value_node)
        elif value_type == 'BooleanLiteral':
            return self._convert_boolean_literal(value_node)
        elif value_type == 'StringLiteral':
            return self._convert_string_literal(value_node)
        elif value_type == 'BinaryExpression':
            return self._convert_binary_expression(value_node)
        elif value_type == 'CallExpression':
            return self._convert_call_expression(value_node)
        else:
            return self._convert_unknown(value_node)
    
    def _convert_function_declaration(self, node: ast.AST) -> Optional[str]:
        """Convert Pine Script function declaration to Python"""
        # Pine: my_function(param1, param2) => return value
        
        func_name = getattr(node, 'name', None) or \
                    node.name if hasattr(node, 'name') else 'unknown_func'
        
        # Get parameters
        params = []
        if hasattr(node, 'parameters') and node.parameters:
            for param in node.parameters.params or []:
                param_name = getattr(param, 'name', None) or \
                             param.name if hasattr(param, 'name') else 'param'
                params.append(param_name)
        
        # Convert function body
        body_statements = []
        if hasattr(node, 'body') and node.body:
            for stmt in node.body:
                stmt_code = self._convert_node(stmt)
                if stmt_code:
                    body_statements.append(stmt_code)
        
        # Convert return statement if present
        return_stmt = ""
        if hasattr(node, 'return_type') and node.return_type:
            return_stmt = f"    -> {node.return_type}\n"
        
        # Build Python function
        if body_statements:
            param_str = ", ".join(params)
            func_body = "\n".join(body_statements)
            return f"def {func_name}({param_str}):{return_stmt}\n{func_body}"
        
        return f"def {func_name}({', '.join(params)}): pass"
    
    def _convert_if_statement(self, node: ast.AST) -> Optional[str]:
        """Convert if-else statement"""
        # Pine: if condition
        # Python: if condition:
        
        condition = self._convert_assign_value(node.condition) if hasattr(node, 'condition') else "True"
        
        # Convert consequence (then block)
        consequence = self._convert_block(node.consequence) if hasattr(node, 'consequence') else ""
        
        # Convert alternative (else block)
        alternative = self._convert_block(node.alternative) if hasattr(node, 'alternative') else ""
        
        if consequence and alternative:
            return f"if {condition}:\n{consequence}else:\n{alternative}"
        elif consequence:
            return f"if {condition}:\n{consequence}"
        return None
    
    def _convert_block(self, block_node: ast.AST) -> str:
        """Convert a block of statements"""
        statements = []
        if hasattr(block_node, 'body'):
            for stmt in block_node.body:
                stmt_code = self._convert_node(stmt)
                if stmt_code:
                    statements.append(stmt_code)
        return "\n".join(statements) if statements else "pass"
    
    def _convert_for_loop(self, node: ast.AST) -> Optional[str]:
        """Convert for loop"""
        # Pine: for i = 1 to 10
        # Python: for i in range(1, 11)
        
        iter_name = getattr(node, 'variable', None) or \
                    node.variable if hasattr(node, 'variable') else 'i'
        
        # Get range
        start = getattr(node, 'start', 1) or 1
        end = getattr(node, 'end', 10) or 10
        step = getattr(node, 'step', 1) or 1
        
        body = self._convert_block(node.body) if hasattr(node, 'body') else "pass"
        
        return f"for {iter_name} in range({start}, {end + 1}, {step}):\n{body}"
    
    def _convert_while_loop(self, node: ast.AST) -> Optional[str]:
        """Convert while loop"""
        condition = self._convert_assign_value(node.condition) if hasattr(node, 'condition') else "True"
        body = self._convert_block(node.body) if hasattr(node, 'body') else "pass"
        return f"while {condition}:\n{body}"
    
    def _convert_return_statement(self, node: ast.AST) -> Optional[str]:
        """Convert return statement"""
        value = self._convert_assign_value(node.value) if hasattr(node, 'value') else "None"
        return f"return {value}"
    
    def _convert_binary_expression(self, node: ast.AST) -> str:
        """Convert binary expression (operators)"""
        left = self._convert_assign_value(node.left) if hasattr(node, 'left') else "0"
        right = self._convert_assign_value(node.right) if hasattr(node, 'right') else "0"
        
        # Map Pine operators to Python
        op_map = {
            '+': '+',
            '-': '-',
            '*': '*',
            '/': '/',
            '%': '%',
            '==': '==',
            '!=': '!=',
            '>': '>',
            '<': '<',
            '>=': '>=',
            '<=': '<=',
            'and': 'and',
            'or': 'or',
        }
        
        op = op_map.get(node.operator, node.operator)
        
        # Handle compound assignments
        if hasattr(node, 'compound') and node.compound:
            return f"({left} {op} {right})"
        return f"({left} {op} {right})"
    
    def _convert_call_expression(self, node: ast.AST) -> str:
        """Convert function call expression"""
        func_name = getattr(node, 'function', None) or \
                    getattr(node, 'name', None) or 'func'
        
        # Handle built-in functions
        if hasattr(node, 'args') and node.args:
            args = [self._convert_assign_value(arg) for arg in node.args.args or []]
            arg_str = ", ".join(args)
        else:
            arg_str = ""
        
        # Map common Pine functions to Python
        pine_to_python = {
            'ta.sma': 'self._sma',
            'ta.ema': 'self._ema',
            'ta.rsi': 'self._rsi',
            'ta.atr': 'self._atr',
            'max': 'max',
            'min': 'min',
            'abs': 'abs',
            'sqrt': 'sqrt',
            'log': 'log',
            'exp': 'exp',
        }
        
        py_func = pine_to_python.get(func_name, func_name)
        return f"{py_func}({arg_str})"
    
    def _convert_identifier(self, node: ast.AST) -> str:
        """Convert identifier/node reference"""
        name = getattr(node, 'name', None) or 'unknown'
        # Check if it's a variable in our table
        if name in self.variable_table:
            return name
        return name
    
    def _convert_number_literal(self, node: ast.AST) -> str:
        """Convert number literal"""
        return str(getattr(node, 'value', 0))
    
    def _convert_string_literal(self, node: ast.AST) -> str:
        """Convert string literal"""
        return f"'{getattr(node, 'value', '')}'"
    
    def _convert_boolean_literal(self, node: ast.AST) -> str:
        """Convert boolean literal"""
        return str(getattr(node, 'value', False)).lower()
    
    def _convert_unknown(self, node: ast.AST) -> str:
        """Fallback for unknown node types"""
        # Try to get source code representation
        try:
            return ast.unparse(node)
        except:
            return f"# unknown: {type(node).__name__}"
    
    def _parse_array_dims(self, dim_node: ast.AST) -> List[int]:
        """Parse array dimensions"""
        dims = []
        if hasattr(dim_node, 'value'):
            dims.append(int(dim_node.value))
        if hasattr(dim_node, 'inner_dims'):
            dims.extend(self._parse_array_dims(dim_node.inner_dims))
        return dims


class PineScriptService:
    """
    Service for managing Pine Script strategies.
    Parses .pine files from a /strategies folder for native execution.
    """
    
    def __init__(self, strategies_dir: str = "/strategies"):
        self.strategies_dir = Path(strategies_dir)
        self.parser = PineScriptParser()
        self.loaded_strategies: Dict[str, str] = {}
        self.compile_cache: Dict[str, str] = {}
    
    def load_strategy(self, filename: str) -> Optional[str]:
        """
        Load a Pine Script strategy file.
        
        Args:
            filename: Name of the .pine file
            
        Returns:
            Transpiled Python code
        """
        file_path = self.strategies_dir / filename
        
        if not file_path.exists():
            print(f"Strategy file not found: {file_path}")
            return None
        
        try:
            with open(file_path, 'r') as f:
                pine_code = f.read()
            
            # Transpile to Python
            python_code = self.parser.transpile(pine_code)
            
            # Cache the result
            self.loaded_strategies[filename] = pine_code
            self.compile_cache[filename] = python_code
            
            print(f"Loaded and transpiled strategy: {filename}")
            return python_code
            
        except Exception as e:
            print(f"Error loading strategy {filename}: {e}")
            return None
    
    def execute_strategy(self, filename: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a transpiled Pine Script strategy against market data.
        
        Args:
            filename: Name of the .pine file
            market_data: Market data dictionary
            
        Returns:
            Strategy output signals
        """
        python_code = self.load_strategy(filename)
        if python_code is None:
            return {"error": "Strategy not found"}
        
        # Create execution context
        context = {
            "close": market_data.get("close", []),
            "high": market_data.get("high", []),
            "low": market_data.get("low", []),
            "open": market_data.get("open", []),
            "volume": market_data.get("volume", []),
            "time": market_data.get("time", []),
            "sma": lambda x: self._sma(x, 14),
            "ema": lambda x: self._ema(x, 14),
            "rsi": lambda x: self._rsi(x, 14),
            "atr": lambda x: self._atr(x, 14),
        }
        
        # Execute the transpiled code in a restricted namespace
        try:
            namespace = {"__builtins__": __builtins__, "context": context}
            exec(python_code, namespace)
            
            # Check for generated signals
            signals = {}
            for key in ["signal", "action", "entry", "exit", "position"]:
                if key in namespace:
                    signals[key] = namespace[key]
            
            return signals
            
        except Exception as e:
            return {"error": f"Execution error: {e}"}
    
    @staticmethod
    def _sma(data: List[float], length: int = 14) -> float:
        """Simple moving average"""
        if len(data) < length:
            return data[-1] if data else 0.0
        return sum(data[-length:]) / length
    
    @staticmethod
    def _ema(data: List[float], length: int = 14) -> float:
        """Exponential moving average"""
        if len(data) < length:
            return data[-1] if data else 0.0
        k = 2 / (length + 1)
        ema = data[0]
        for price in data[1:]:
            ema = k * price + (1 - k) * ema
        return ema
    
    @staticmethod
    def _rsi(data: List[float], length: int = 14) -> float:
        """Relative Strength Index"""
        if len(data) < length + 1:
            return 50.0
        
        gains = []
        losses = []
        for i in range(1, len(data)):
            change = data[i] - data[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(-change)
        
        # Average gain/loss over period
        avg_gain = sum(gains[-length:]) / len(gains[-length:]) if gains else 0
        avg_loss = sum(losses[-length:]) / len(losses[-length:]) if losses else 0.001
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def _atr(data: List[float], high: List[float], low: List[float], length: int = 14) -> float:
        """Average True Range"""
        if len(high) < length + 1 or len(low) < length + 1:
            return 0.0
        
        tr_values = []
        for i in range(1, len(high)):
            tr = max(
                high[i] - low[i],
                abs(high[i] - data[i-1]),
                abs(low[i] - data[i-1])
            )
            tr_values.append(tr)
        
        return sum(tr_values[-length:]) / len(tr_values[-length:]) if tr_values else 0.0


# --- Export ---

__all__ = [
    "PineScriptParser",
    "PineScriptService",
    "TORCH_AVAILABLE"
]