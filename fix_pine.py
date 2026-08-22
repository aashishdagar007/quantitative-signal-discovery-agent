#!/usr/bin/env python
with open('core_engine/pine_script.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Simple fix: join line with next if it has unclosed parenthesis
old = """    def transpile(self, pine_code: str) -> str:
        """Main entry: transpile full Pine Script source to Python."""
        lines = pine_code.splitlines()
        python_lines: List[str] = [
            "# Auto-transpiled from Pine Script v5",
            "import math",
            "from core_engine.pine_stdlib import PineStdLib as _pine",
            "",
        ]"""

new = """    def transpile(self, pine_code: str) -> str:
        """Main entry: transpile full Pine Script source to Python."""
        lines = pine_code.splitlines()

        # Join any line that has an unclosed '(' with the next line.
        # Pine Script strategy()/indicator() headers often span multiple
        # physical lines, and joining them prevents invalid Python output.
        joined: List[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Count parentheses depth
            depth = 0
            for ch in line:
                if ch in "({":
                    depth += 1
                elif ch in ")}":
                    depth -= 1
            if depth > 0 and i + 1 < len(lines):
                # Merge this line with the next
                merged = line + " " + lines[i + 1].strip()
                joined.append(merged)
                i += 2
            else:
                joined.append(line)
                i += 1
        lines = joined

        python_lines: List[str] = [
            "# Auto-transpiled from Pine Script v5",
            "import math",
            "from core_engine.pine_stdlib import PineStdLib as _pine",
            "",
        ]"""

if old in content:
    content = content.replace(old, new)
    with open('core_engine/pine_script.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("SUCCESS")
else:
    print("ERROR: Could not find target string")