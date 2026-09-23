

import re
import subprocess
import sys

import preprocess as pp  # reuses your existing handlers, symbol table, etc.


C_FILE = "output.c"
EXE_FILE = "output_exe.exe" if sys.platform.startswith("win") else "./output_exe"


RESULT_LINE = re.compile(r'^([A-Za-z_]\w*)\s*=\s*([₹$€£]?)(-?\d+\.\d+)$')


def compile_c(source=C_FILE, exe=EXE_FILE):
    print(f"\n========== COMPILING {source} ==========")
    result = subprocess.run(
        ["gcc", source, "-o", exe.lstrip("./")],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("Compilation FAILED:")
        print(result.stderr)
        return False
    print("Compiled successfully.")
    return True


def run_c(exe=EXE_FILE, needed_inputs=None):
   
    needed_inputs = needed_inputs or []
    stdin_data = ""
    if needed_inputs:
        print("\nThis program will read input for:", ", ".join(needed_inputs))
        values = [input(f"  Enter value for {var}: ") for var in needed_inputs]
        stdin_data = "\n".join(values) + "\n"

    print("\n========== RUNNING COMPILED PROGRAM ==========")
    result = subprocess.run(
        [exe], input=stdin_data, capture_output=True, text=True, encoding="utf-8"
    )
    print(result.stdout, end="")
    if result.returncode != 0:
        print(f"(program exited with code {result.returncode})")
        print(result.stderr)
    return result.stdout


def parse_runtime_values(program_output):
    values = {}
    for line in program_output.splitlines():
        match = RESULT_LINE.match(line.strip())
        if match:
            var, symbol, number = match.groups()
            values[var] = f"{symbol}{number}"
    return values


def print_combined_report(runtime_values):
    print("\n========== COMBINED REPORT (preprocessor + runtime) ==========")
    print(f"{'Variable':<16}{'Status':<26}{'Value':<14}{'Message'}")
    print("-" * 90)
    for var in pp.symbol_table:
        diagnostics = pp.var_diagnostics.get(var, [])
        message_text = "; ".join(text for _, text in diagnostics)

        if var in pp.invalid_vars:
            status = "SKIPPED (semantic error)"
            value = "N/A"
        elif var in runtime_values:
            status = "OK (with warning)" if diagnostics else "OK"
            value = runtime_values[var]
        else:
            status = "(not printed via output())"
            value = "-"

        print(f"{var:<16}{status:<26}{value:<14}{message_text}")


def main():
    with open("input.txt", encoding="utf-8") as f:
        lines = f.readlines()

    print("========== LINE-BY-LINE TRACE ==========\n")
    translated = pp.preprocess(lines)
    pp.generate_c_file(translated, C_FILE)

    print("\n========== FINAL TRANSLATED C ==========")
    for line in translated:
        print(line)
    pp.print_symbol_table(pp.symbol_table)

    if not compile_c():
        return

    output_text = run_c(needed_inputs=pp.input_vars)
    runtime_values = parse_runtime_values(output_text)
    print_combined_report(runtime_values)


if __name__ == "__main__":
    main()