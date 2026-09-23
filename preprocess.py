import re
import ast

CURRENCY_SYMBOLS = ['₹', '$', '€', '£']
symbol_table = {}
invalid_vars = set()      # variables whose last computed value came from a semantic ERROR
input_vars = []           # variables read via input(), in the order they appear
var_diagnostics = {}      # var -> list of (level, text) WARNING/ERROR messages from its last assignment


# ---------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------

def handle_currency_decl(line, symbol_table, messages):
    match = re.match(r'currency\s+(.+);', line)
    if match:
        var_list = [v.strip() for v in match.group(1).split(',')]
        for var in var_list:
            symbol_table[var] = {
                'source_type': 'currency',
                'target_type': 'float',
                'currency_symbol': None
            }
        messages.append(("INFO", f"Declared {', '.join(var_list)} as currency (-> float)."))
        return f"float {', '.join(var_list)};"
    return None


def handle_plain_decl(line, symbol_table, messages):
    match = re.match(r'(int|float)\s+(.+);', line)
    if match:
        var_type = match.group(1)
        var_list = [v.strip() for v in match.group(2).split(',')]
        for var in var_list:
            symbol_table[var] = {
                'source_type': var_type,
                'target_type': var_type,
                'currency_symbol': None
            }
        messages.append(("INFO", f"Declared {', '.join(var_list)} as plain {var_type}."))
        return line
    return None


# ---------------------------------------------------------------------
# Currency literal assignment
# ---------------------------------------------------------------------

def handle_currency_assignment(line, symbol_table, messages):
    pattern = r'(\w+)\s*=\s*([₹$€£])(\d+(\.\d+)?)\s*;'
    match = re.match(pattern, line)
    if match:
        var, symbol, value = match.group(1), match.group(2), match.group(3)

        if var in symbol_table:
            symbol_table[var]['currency_symbol'] = symbol
        else:
            symbol_table[var] = {
                'source_type': 'currency',
                'target_type': 'float',
                'currency_symbol': symbol
            }

        messages.append(("INFO", f"Assigned currency literal {symbol}{value} to '{var}'."))
        return f"{var}={value}f;"
    return None


# ---------------------------------------------------------------------
# input / output
# ---------------------------------------------------------------------

def handle_input(line, symbol_table, messages):
    match = re.match(r'input\((\w+)\)\s*;', line)
    if match:
        var = match.group(1)
        messages.append(("INFO", f"Reads a float into '{var}' at runtime (scanf)."))
        input_vars.append(var)
        # Prompt first, so the console is never silently blank while waiting.
        return f'printf("Enter value for {var}: \\n"); scanf("%f",&{var});'
    return None


def handle_output(line, symbol_table, messages):
    match = re.match(r'output\((\w+)\)\s*;', line)
    if match:
        var = match.group(1)
        symbol = symbol_table.get(var, {}).get('currency_symbol') or ''
        messages.append(("INFO", f"Prints '{var}' at runtime, formatted as {symbol or 'plain'}%.2f."))
        # Label with the variable name so the professor can tell values apart at a glance.
        return f'printf("{var} = {symbol}%.2f\\n",{var});'
    return None


# ---------------------------------------------------------------------
# Arithmetic expression assignment (ast-based type inference)
# ---------------------------------------------------------------------

def handle_arithmetic(line, symbol_table, messages):
    match = re.match(r'(\w+)\s*=\s*(.+);\s*$', line)
    if not match:
        return None

    result_var, expr_str = match.group(1), match.group(2)

    try:
        tree = ast.parse(expr_str, mode='eval')
    except SyntaxError:
        return None  # already handled elsewhere (e.g. currency literal)

    result_type = infer_type(tree.body, symbol_table, messages)

    if result_var in symbol_table:
        symbol_table[result_var]['currency_symbol'] = result_type['symbol']
    else:
        symbol_table[result_var] = {
            'source_type': result_type['kind'],
            'target_type': 'float' if result_type['kind'] == 'currency' else result_type['kind'],
            'currency_symbol': result_type['symbol']
        }

    kind_desc = result_type['kind']
    if result_type['symbol']:
        kind_desc += f" ({result_type['symbol']})"
    messages.append(("RESULT", f"'{result_var}' inferred as {kind_desc}."))

    # Track whether THIS line raised a semantic ERROR, so a downstream
    # runner can skip reporting back a value that's semantically meaningless.
    if any(level == "ERROR" for level, _ in messages):
        invalid_vars.add(result_var)
    else:
        invalid_vars.discard(result_var)  # a later valid assignment clears an earlier flag

    # Keep the actual WARNING/ERROR text so it can be shown again later
    # (e.g. in run_pipeline.py's combined report), not just a generic label.
    relevant = [(level, text) for level, text in messages if level in ("ERROR", "WARNING")]
    if relevant:
        var_diagnostics[result_var] = relevant
    else:
        var_diagnostics.pop(result_var, None)  # a later clean assignment clears old diagnostics

    return line  # C syntax is already valid


def infer_type(node, symbol_table, messages):
    """Recursively walks the expression tree, returning
    {'kind': 'currency'|'float'|'int', 'symbol': symbol or None}.
    Any warnings/errors triggered along the way are appended to `messages`."""

    if isinstance(node, ast.Name):
        info = symbol_table.get(node.id)
        if info is None:
            messages.append(("WARNING", f"'{node.id}' used before declaration; assuming float."))
            return {'kind': 'float', 'symbol': None}
        return {'kind': info['source_type'], 'symbol': info.get('currency_symbol')}

    if isinstance(node, ast.Constant):
        return {'kind': 'int' if isinstance(node.value, int) else 'float', 'symbol': None}

    if isinstance(node, ast.UnaryOp):
        return infer_type(node.operand, symbol_table, messages)

    if isinstance(node, ast.BinOp):
        left = infer_type(node.left, symbol_table, messages)
        right = infer_type(node.right, symbol_table, messages)
        op = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/'}.get(type(node.op))
        if op is None:
            messages.append(("WARNING", "Unsupported operator; assuming float."))
            return {'kind': 'float', 'symbol': None}
        return combine_types(left, right, op, messages)

    messages.append(("WARNING", "Unsupported expression syntax; assuming float."))
    return {'kind': 'float', 'symbol': None}


def combine_types(left, right, op, messages):
    """Semantic rule table. Appends WARNING/ERROR to `messages` (does not print directly),
    so the caller can show them attached to the correct source line."""
    l, r = left['kind'], right['kind']

    if l == 'currency' and r == 'currency':
        if op in ('+', '-'):
            if left['symbol'] != right['symbol']:
                messages.append(("ERROR", f"Currency mismatch: cannot use '{op}' between "
                                           f"{left['symbol']} and {right['symbol']} values."))
                return {'kind': 'currency', 'symbol': None}
            return {'kind': 'currency', 'symbol': left['symbol']}
        if op == '/':
            return {'kind': 'float', 'symbol': None}
        if op == '*':
            messages.append(("ERROR", "Cannot multiply two currency values."))
            return {'kind': 'currency', 'symbol': None}

    if l == 'currency' and r in ('int', 'float'):
        if op in ('*', '/'):
            return {'kind': 'currency', 'symbol': left['symbol']}
        messages.append(("WARNING", f"currency ({left['symbol']}) combined with a plain number using '{op}'."))
        return {'kind': 'currency', 'symbol': left['symbol']}

    if r == 'currency' and l in ('int', 'float'):
        if op == '*':
            return {'kind': 'currency', 'symbol': right['symbol']}
        messages.append(("WARNING", f"currency ({right['symbol']}) combined with a plain number using '{op}'."))
        return {'kind': 'currency', 'symbol': right['symbol']}

    kind = 'float' if 'float' in (l, r) else 'int'
    return {'kind': kind, 'symbol': None}


# ---------------------------------------------------------------------
# Symbol table + C file generation
# ---------------------------------------------------------------------

def print_symbol_table(symbol_table):
    print(f"\n{'Variable':<14}{'Source':<10}{'Target':<10}{'Symbol'}")
    print("-" * 44)
    for var, info in symbol_table.items():
        symbol = info['currency_symbol'] if info['currency_symbol'] else "Not applicable"
        print(f"{var:<14}{info['source_type']:<10}{info['target_type']:<10}{symbol}")


def generate_c_file(translated_lines, filename="output.c"):
    with open(filename, "w", encoding="utf-8") as f:
        f.write("#include <stdio.h>\n")
        # On Windows, the console defaults to a codepage that mangles UTF-8
        # currency symbols (₹, €, £) into garbage bytes. windows.h lets us
        # switch the console to UTF-8 at startup. This block is skipped
        # entirely on Linux/macOS (_WIN32 is only defined by Windows compilers).
        f.write("#ifdef _WIN32\n#include <windows.h>\n#endif\n\n")
        f.write("int main()\n{\n")
        f.write("#ifdef _WIN32\n    SetConsoleOutputCP(CP_UTF8);\n#endif\n")
        for line in translated_lines:
            f.write(f"    {line}\n")
        f.write("    return 0;\n}\n")


# ---------------------------------------------------------------------
# Pipeline — now with per-line diagnostic tracing
# ---------------------------------------------------------------------

def preprocess(source_lines):
    output_lines = []

    for line_no, raw_line in enumerate(source_lines, start=1):
        line = raw_line.strip()
        if line == "":
            continue

        messages = []  # diagnostics produced while processing THIS line only

        translated = handle_currency_decl(line, symbol_table, messages)
        if translated is None:
            translated = handle_plain_decl(line, symbol_table, messages)
        if translated is None:
            translated = handle_currency_assignment(line, symbol_table, messages)
        if translated is None:
            translated = handle_input(line, symbol_table, messages)
        if translated is None:
            translated = handle_output(line, symbol_table, messages)
        if translated is None:
            translated = handle_arithmetic(line, symbol_table, messages)
        if translated is None:
            translated = line
            messages.append(("INFO", "Unrecognized syntax; passed through unchanged."))

        output_lines.append(translated)

        # ---- per-line trace, printed immediately ----
        print(f"[Line {line_no}] {line}")
        print(f"   translated -> {translated}")
        for level, text in messages:
            print(f"   {level:<7}: {text}")
        print()

    return output_lines


if __name__ == "__main__":
    with open("input.txt", encoding="utf-8") as f:
        lines = f.readlines()

    print("========== LINE-BY-LINE TRACE ==========\n")
    result = preprocess(lines)

    generate_c_file(result, "output.c")

    print("========== FINAL TRANSLATED C ==========")
    for i in result:
        print(i)

    print_symbol_table(symbol_table)
    print("\nWrote output.c")