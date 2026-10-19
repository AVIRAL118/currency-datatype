# Limitations and Design Decisions

This preprocessor is a static, source-to-source translator. It analyzes the
program's *text* before any C code runs — it has no visibility into values
that only exist at runtime (anything read via `input()`).

## What it does NOT do

- **No currency conversion.** It detects a mismatch (e.g. `₹` + `$`) and
  reports an ERROR; it does not fetch exchange rates or convert values.
  (A live-rate conversion feature was discussed and scoped, but is not
  implemented in this version — see the project plan's Phase 4.)
- **No runtime symbol checking on `input()`.** `scanf("%f", &var)` can only
  parse a bare number. If a user types a currency symbol (`$510`) at an
  `input()` prompt, `scanf` fails to match, the variable is left at its
  previous value, and no error is printed by the C program itself. This is
  a known gap — see Phase 5 of the project plan for the planned fix (a
  custom `read_currency()` C helper).
- **No currency-aware output formatting beyond 2 decimal places.** All
  currency/float values print with exactly `%.2f`; there is no support for
  currencies with different conventional decimal places.
- **No comments in the source language.** A `//` or `#` in an input line
  is not recognized and will be treated as unrecognized syntax.
- **No compound assignment** (`+=`, `-=`) or comparison/boolean operators.
  The grammar only supports the arithmetic expressions in `SPEC.md`.

## Design decisions made along the way

- **ERRORs block code generation** for that one statement (commented out in
  the generated C) rather than being reported but still compiled and run.
  Earlier versions of this preprocessor reported an ERROR in the Python
  trace but still emitted and ran the faulty expression — meaning a
  mismatched `price1 + usPrice` would silently compile and print a
  confidently-formatted but meaningless number. This was treated as a bug,
  not a feature, and fixed.
- **`currency / currency` is valid only when symbols match** (see
  `SPEC.md` section 3, decision D1). Division across different currencies
  is an ERROR, consistent with "no conversion without exchange rates."
- **Negative currency literals are allowed** (decision D3) and are not
  treated as an error, since they can represent legitimate values (refunds,
  deficits, overdrafts).
- **Global state is reset at the start of every `preprocess()` call**
  (`reset_state()`), so the module can be re-run in the same process
  (e.g. from a test suite) without stale data from a previous run leaking
  into the new one.