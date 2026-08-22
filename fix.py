import sys

with open('core_engine/pine_script.py', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# The exact string to find and replace
old = """        lines = pine_code.splitlines()
        python_lines: List[str] = [
            "# Auto-transpiled from Pine Script v5",
            "import math",
            "from core_engine.pine_stdlib import PineStdLib as _pine",
            "",
        ]"""

new = """        lines = pine_code.splitlines()

        # Join any line that has an unclosed '(' with the next line.
        # Pine Script strategy()/indicator() headers often span multiple
        # physical lines, and joining them prevents invalid Python output.
        joined: List[str] = []
        idx = 0
        while idx < len(lines):
            line = lines[idx] if idx < len(lines) else ''
            # Count parentheses depth
            depth = 0
            for c in line:
                if c in '({':
                    depth += 1
                elif c in ')}':
                    depth -= 1
            if depth > 0 and i + 1 < len(lines):
                # Merge this line with the next
                merged = line + " " + lines[i + 1].strip()
                # Check if still unclosed
                depth2 = 0
                for ch in merged:
                    if ch in "({":
                        depth2 += 1
                    elif ch in ")}":
                        depth2 -= 1
                if depth2 > 0 and i + 2 < len(lines):
                    # Keep merging until depth is 0
                    j = i + 1
                    merged = line.strip()
                    while j < len(lines) and depth2 > 0:
                        depth2 = 0
                        for ch in lines[j]:
                            if ch in "({":
                                depth2 += 1
                            elif ch in ")}":
                                depth2 -= 1
                        merged += " " + lines[j].strip()
                        j += 1
                    joined.append(merged)
                    idx = j
                else:
                    joined.append(merged)
                    idx += 1
            else:
                joined.append(line)
                idx += 1
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
    # Show what's around line 118
    lines = content.split('\n')
    for i in range(115, 125):
        print(f"{i+1}: {lines[i] if i < len(lines) else 'MISSING'}")
PYEOF