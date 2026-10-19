"""
Positive and negative test suite for the currency preprocessor, plus an
automated check that generated C actually compiles with GCC.

Run with:  pytest tests/
"""
import shutil
import subprocess
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import preprocess as pp


def run(lines):
    """Run the preprocessor fresh (reset=True) over a list of source lines."""
    return pp.preprocess(lines, reset=True)


# ---------------------------------------------------------------------
# Positive cases: these should type-check cleanly with no ERROR.
# ---------------------------------------------------------------------

def test_same_currency_addition_is_valid():
    run([
        "currency a, b, total;",
        "a = ₹100.00;",
        "b = ₹50.00;",
        "total = a + b;",
    ])
    assert "total" not in pp.invalid_vars
    assert pp.symbol_table["total"]["currency_symbol"] == "₹"
    assert pp.error_count == 0


def test_same_currency_division_yields_float_ratio():
    run([
        "currency a, b;",
        "float ratio;",
        "a = ₹100.00;",
        "b = ₹50.00;",
        "ratio = a / b;",
    ])
    assert pp.symbol_table["ratio"]["source_type"] == "float"
    assert pp.symbol_table["ratio"]["currency_symbol"] is None
    assert "ratio" not in pp.invalid_vars
    assert pp.error_count == 0


def test_currency_times_int_scales_correctly():
    run([
        "currency price;",
        "int qty;",
        "currency total;",
        "price = ₹10.00;",
        "qty = 3;",
        "total = price * qty;",
    ])
    assert pp.symbol_table["total"]["source_type"] == "currency"
    assert pp.symbol_table["total"]["currency_symbol"] == "₹"
    assert "total" not in pp.invalid_vars


def test_nested_parentheses_type_propagation():
    run([
        "currency a, b, c, result;",
        "a = ₹10.00;",
        "b = ₹5.00;",
        "c = ₹2.00;",
        "result = (a + b) - c;",
    ])
    assert pp.symbol_table["result"]["source_type"] == "currency"
    assert pp.symbol_table["result"]["currency_symbol"] == "₹"
    assert "result" not in pp.invalid_vars


def test_plain_int_and_float_arithmetic_unaffected():
    run([
        "int x, y, z;",
        "x = 4;",
        "y = 2;",
        "z = x + y;",
    ])
    assert pp.symbol_table["z"]["source_type"] == "int"
    assert pp.error_count == 0


# ---------------------------------------------------------------------
# Negative cases: these must be flagged as ERROR and must NOT reach the
# generated C as a real computation.
# ---------------------------------------------------------------------

def test_mismatched_currency_addition_is_an_error():
    translated = run([
        "currency a, b, total;",
        "a = ₹100.00;",
        "b = $50.00;",
        "total = a + b;",
    ])
    assert "total" in pp.invalid_vars
    assert pp.error_count == 1
    # the faulty line must be commented out, not emitted as real C
    last_line = translated[-1]
    assert last_line.strip().startswith("/* ERROR")
    assert "a + b" not in last_line or "/*" in last_line


def test_currency_times_currency_is_always_an_error():
    translated = run([
        "currency a, b, total;",
        "a = ₹100.00;",
        "b = ₹50.00;",
        "total = a * b;",
    ])
    assert "total" in pp.invalid_vars
    assert pp.error_count == 1
    assert translated[-1].strip().startswith("/* ERROR")


def test_mismatched_currency_division_is_an_error():
    translated = run([
        "currency a, b, total;",
        "a = ₹100.00;",
        "b = $50.00;",
        "total = a / b;",
    ])
    assert "total" in pp.invalid_vars
    assert pp.error_count == 1
    assert translated[-1].strip().startswith("/* ERROR")


def test_unrecognized_syntax_is_a_warning_and_is_commented_out():
    translated = run([
        "currency a;",
        "a = ₹100.00;a",   # stray trailing character, as seen in real use
    ])
    assert pp.warning_count >= 1
    assert translated[-1].strip().startswith("/*")


def test_output_of_invalid_var_does_not_crash_and_is_flagged():
    translated = run([
        "currency a, b, total;",
        "a = ₹100.00;",
        "b = $50.00;",
        "total = a + b;",
        "output(total);",
    ])
    output_line = translated[-1]
    assert "N/A" in output_line


# ---------------------------------------------------------------------
# Automated test: compile the generated C with GCC and confirm it builds
# cleanly, for both an all-valid program and a program containing errors
# (which must still compile, since the bad lines become comments).
# ---------------------------------------------------------------------

requires_gcc = pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc not installed")


@requires_gcc
def test_generated_c_compiles_for_valid_program(tmp_path):
    translated = run([
        "currency a, b, total;",
        "a = ₹100.00;",
        "b = ₹50.00;",
        "total = a + b;",
        "output(total);",
    ])
    c_file = tmp_path / "valid.c"
    pp.generate_c_file(translated, str(c_file))
    result = subprocess.run(
        ["gcc", str(c_file), "-o", str(tmp_path / "valid_exe")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == "", f"compiled with warnings: {result.stderr}"


@requires_gcc
def test_generated_c_compiles_even_with_semantic_errors(tmp_path):
    translated = run([
        "currency a, b, total;",
        "a = ₹100.00;",
        "b = $50.00;",
        "total = a + b;",
        "output(total);",
    ])
    c_file = tmp_path / "invalid.c"
    pp.generate_c_file(translated, str(c_file))
    result = subprocess.run(
        ["gcc", str(c_file), "-o", str(tmp_path / "invalid_exe")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    run_result = subprocess.run([str(tmp_path / "invalid_exe")], capture_output=True, text=True)
    assert "N/A" in run_result.stdout