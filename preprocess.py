import re
import ast

# ---------------------------------------------------------------------
# Config: add a currency here and the assignment regex below updates
# itself automatically (Phase 1, item 5).
# ---------------------------------------------------------------------
CURRENCY_SYMBOLS = ['₹', '$', '€', '£']
SYMBOL_TO_ISO = {'₹': 'INR', '$': 'USD', '€': 'EUR', '£': 'GBP'}

_SYMBOL_CLASS = "[" + "".join(re.escape(s) for s in CURRENCY_SYMBOLS) + "]"
# Every statement-matching regex below is anchored with \s*$ at the end.
# Earlier versions only anchored handle_arithmetic this way, which meant
# trailing garbage after a declaration/literal/input/output statement
# (e.g. "a = ₹100.00;a") was silently matched and dropped instead of being
# flagged — the same class of bug as the original "stray character" issue,
# just present in more handlers than first thought.
_CURRENCY_LITERAL_RE = re.compile(
    r'(\w+)\s*=\s*(' + _SYMBOL_CLASS + r')(-?\d+(\.\d+)?)\s*;\s*$'
)

# ---------------------------------------------------------------------
# Global state. reset_state() clears it so preprocess() can be called
# more than once in the same process (Phase 1, item 6) without old
# runs bleeding into new ones.
# ---------------------------------------------------------------------
symbol_table = {}
invalid_vars = set()
input_vars = []
var_diagnostics = {}       # var -> list of (level, text, line_no)
error_count = 0
warning_count = 0


def reset_state():
    global error_count, warning_count
    symbol_table.clear()
    invalid_vars.clear()
    input_vars.clear()
    var_diagnostics.clear()
    error_count = 0
    warning_count = 0


def iso(symbol):
    """Human-readable 'INR (₹)' form for a symbol, or '' if none."""
    if not symbol:
        return ''
    return f"{SYMBOL_TO_ISO.get(symbol, '?')} ({symbol})"


# ---------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------

def handle_currency_decl(line, symbol_table, messages):
    match = re.match(r'currency\s+(.+);\s*$', line)
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
    match = re.match(r'(int|float)\s+(.+);\s*$', line)
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
    match = _CURRENCY_LITERAL_RE.match(line)
    if match:
        var, symbol, value = match.group(1), match.group(2), match.group(3)

        if var in symbol_table:
            old_symbol = symbol_table[var].get('currency_symbol')
            if old_symbol and old_symbol != symbol:
                messages.append(("WARNING",
                    f"'{var}' previously held {iso(old_symbol)}; now reassigned to {iso(symbol)}."))
            symbol_table[var]['currency_symbol'] = symbol
        else:
            symbol_table[var] = {
                'source_type': 'currency',
                'target_type': 'float',
                'currency_symbol': symbol
            }

        messages.append(("INFO", f"Assigned currency literal {symbol}{value} to '{var}' ({iso(symbol)})."))
        return f"{var}={value}f;"
    return None


# ---------------------------------------------------------------------
# input / output
# ---------------------------------------------------------------------

def handle_input(line, symbol_table, messages):
    match = re.match(r'input\((\w+)\)\s*;\s*$', line)
    if match:
        var = match.group(1)
        c_type = symbol_table.get(var, {}).get('target_type', 'float')
        fmt = "%d" if c_type == 'int' else "%f"
        messages.append(("INFO", f"Reads a {c_type} into '{var}' at runtime (scanf \"{fmt}\")."))
        input_vars.append(var)
        return f'printf("Enter value for {var}: \\n"); scanf("{fmt}",&{var});'
    return None


def handle_output(line, symbol_table, messages):
    match = re.match(r'output\((\w+)\)\s*;\s*$', line)
    if match:
        var = match.group(1)
        if var in invalid_vars:
            # Phase 1, item 3 (continued): an output() of a variable whose last
            # assignment was a semantic ERROR must not print an uninitialized
            # or meaningless float. Say so instead of guessing a number.
            messages.append(("WARNING", f"'{var}' holds no valid value (last assignment had an ERROR); output skipped."))
            return f'printf("{var} = N/A (semantic error)\\n");'
        info = symbol_table.get(var, {})
        symbol = info.get('currency_symbol') or ''
        c_type = info.get('target_type', 'float')
        fmt = "%d" if c_type == 'int' else "%.2f"
        messages.append(("INFO", f"Prints '{var}' at runtime, formatted as {symbol or 'plain'}{fmt}."))
        return f'printf("{var} = {symbol}{fmt}\\n",{var});'
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
        return None  # not a parseable expression; let the caller fall through

    result_type = infer_type(tree.body, symbol_table, messages)
    has_error = any(level == "ERROR" for level, _ in messages)

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
        kind_desc += f" ({iso(result_type['symbol'])})"
    messages.append(("RESULT", f"'{result_var}' inferred as {kind_desc}."))

    if has_error:
        invalid_vars.add(result_var)
        # Phase 1, item 3: an ERROR must not reach the compiled program as
        # if it were valid C. Comment the statement out instead of emitting it.
        return f"/* ERROR: '{line}' skipped — see diagnostics for '{result_var}' */"
    else:
        invalid_vars.discard(result_var)

    return line


def infer_type(node, symbol_table, messages):
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
    """
    Currency semantic rules (see SPEC.md for the full table):
      currency (+/-) currency, same symbol   -> currency
      currency (+/-) currency, diff symbol   -> ERROR
      currency  /    currency, same symbol   -> float   (a ratio)
      currency  /    currency, diff symbol   -> ERROR   (mismatched units)
      currency  *    currency                -> ERROR   (always; no unit for money^2)
      currency (*//) int/float               -> currency
      currency (+/-) int/float                -> WARNING, treated as currency
    """
    l, r = left['kind'], right['kind']

    if l == 'currency' and r == 'currency':
        if op in ('+', '-'):
            if left['symbol'] != right['symbol']:
                messages.append(("ERROR", f"Currency mismatch: cannot use '{op}' between "
                                           f"{iso(left['symbol'])} and {iso(right['symbol'])} values."))
                return {'kind': 'currency', 'symbol': None}
            return {'kind': 'currency', 'symbol': left['symbol']}
        if op == '/':
            if left['symbol'] != right['symbol']:
                messages.append(("ERROR", f"Currency mismatch: cannot divide "
                                           f"{iso(left['symbol'])} by {iso(right['symbol'])} directly."))
                return {'kind': 'float', 'symbol': None}
            return {'kind': 'float', 'symbol': None}
        if op == '*':
            messages.append(("ERROR", "Cannot multiply two currency values."))
            return {'kind': 'currency', 'symbol': None}

    if l == 'currency' and r in ('int', 'float'):
        if op in ('*', '/'):
            return {'kind': 'currency', 'symbol': left['symbol']}
        messages.append(("WARNING", f"currency ({iso(left['symbol'])}) combined with a plain number using '{op}'."))
        return {'kind': 'currency', 'symbol': left['symbol']}

    if r == 'currency' and l in ('int', 'float'):
        if op == '*':
            return {'kind': 'currency', 'symbol': right['symbol']}
        messages.append(("WARNING", f"currency ({iso(right['symbol'])}) combined with a plain number using '{op}'."))
        return {'kind': 'currency', 'symbol': right['symbol']}

    kind = 'float' if 'float' in (l, r) else 'int'
    return {'kind': kind, 'symbol': None}


# ---------------------------------------------------------------------
# Symbol table + C file generation
# ---------------------------------------------------------------------

def print_symbol_table(symbol_table):
    print(f"\n{'Variable':<16}{'Source':<10}{'Target':<10}{'ISO':<8}Symbol")
    print("-" * 56)
    for var, info in symbol_table.items():
        symbol = info['currency_symbol']
        iso_code = SYMBOL_TO_ISO.get(symbol, '-') if symbol else '-'
        symbol_disp = symbol if symbol else "Not applicable"
        print(f"{var:<16}{info['source_type']:<10}{info['target_type']:<10}{iso_code:<8}{symbol_disp}")


def generate_c_file(translated_lines, filename="output.c"):
    with open(filename, "w", encoding="utf-8") as f:
        f.write("#include <stdio.h>\n")
        f.write("#ifdef _WIN32\n#include <windows.h>\n#endif\n\n")
        f.write("int main()\n{\n")
        f.write("#ifdef _WIN32\n    SetConsoleOutputCP(CP_UTF8);\n#endif\n")
        for line in translated_lines:
            f.write(f"    {line}\n")
        f.write("    return 0;\n}\n")


# ---------------------------------------------------------------------
# Pipeline — per-line diagnostic tracing, now with line numbers and a
# run summary (Phase 1, item 8).
# ---------------------------------------------------------------------

def preprocess(source_lines, reset=True):
    if reset:
        reset_state()

    global error_count, warning_count
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
            # Phase 1, item 2: unrecognized syntax is a WARNING, not a silent
            # pass-through, because it is very likely to break the C compile.
            translated = f"/* WARNING line {line_no}: unrecognized syntax, skipped -> {line} */"
            messages.append(("WARNING", "Unrecognized syntax; line skipped, not passed through."))

        output_lines.append(translated)

        for level, text in messages:
            if level == "ERROR":
                error_count += 1
            elif level == "WARNING":
                warning_count += 1
            # keep per-variable diagnostics with their line number attached
        result_var_match = re.match(r'(\w+)\s*=', line)
        if result_var_match:
            rv = result_var_match.group(1)
            relevant = [(level, text, line_no) for level, text in messages if level in ("ERROR", "WARNING")]
            if relevant:
                var_diagnostics[rv] = relevant
            else:
                var_diagnostics.pop(rv, None)

        print(f"[Line {line_no}] {line}")
        print(f"   translated -> {translated}")
        for level, text in messages:
            print(f"   {level:<7}: {text}")
        print()

    print(f"========== RUN SUMMARY: {error_count} error(s), {warning_count} warning(s) ==========\n")

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