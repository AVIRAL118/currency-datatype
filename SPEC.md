# Specification: Extended-C `currency` Type

## 1. Lexical elements

| Token | Pattern | Example |
|---|---|---|
| `CURRENCY_KEYWORD` | `currency` | `currency price;` |
| `CURRENCY_SYMBOL` | one of `₹ $ € £` | `₹500.00` |
| `IDENTIFIER` | `[A-Za-z_]\w*` | `price1` |
| `INTEGER_LITERAL` | `\d+` | `4` |
| `FLOAT_LITERAL` | `\d+\.\d+` | `0.18` |
| `ASSIGN` | `=` | |
| `PLUS` / `MINUS` / `MULTIPLY` / `DIVIDE` | `+ - * /` | |
| `LEFT_PAREN` / `RIGHT_PAREN` | `( )` | |
| `COMMA` / `SEMICOLON` | `, ;` | |
| `INPUT_KEYWORD` | `input` | `input(price);` |
| `OUTPUT_KEYWORD` | `output` | `output(price);` |

Adding a currency symbol only requires editing `CURRENCY_SYMBOLS` in `preprocess.py` — the literal-matching regex is built from that list at import time.

## 2. Grammar (informal)

```
decl        := "currency" identlist ";"  |  ("int"|"float") identlist ";"
identlist   := IDENTIFIER ("," IDENTIFIER)*
literal     := CURRENCY_SYMBOL NUMBER
assignment  := IDENTIFIER "=" (literal | expr) ";"
expr        := term (("+"|"-") term)*
term        := factor (("*"|"/") factor)*
factor      := IDENTIFIER | NUMBER | "(" expr ")"
io_stmt     := ("input"|"output") "(" IDENTIFIER ")" ";"
```

## 3. Currency operation rules

| Left | Op | Right | Result | Notes |
|---|---|---|---|---|
| currency | `+` `-` | currency, **same symbol** | currency (same symbol) | |
| currency | `+` `-` | currency, **different symbol** | **ERROR** | currency mismatch |
| currency | `/` | currency, **same symbol** | float | a unit-less ratio |
| currency | `/` | currency, **different symbol** | **ERROR** | mismatched units |
| currency | `*` | currency | **ERROR** | no real-world unit for money² |
| currency | `*` `/` | int / float | currency | scaling, always allowed |
| currency | `+` `-` | int / float | currency | **WARNING** — adding a bare number to money is unusual but not blocked |
| int/float | `*` | currency | currency | symmetric with above |
| int/float | `+` `-` `/` | currency | currency | **WARNING**, same reasoning |
| int | any | int | int | standard C rules |
| float / int | any | float / int | float if either operand is float | standard C rules |

**Design decision (D1):** `currency / currency` is valid only when both operands share the same symbol, and produces a plain `float` ratio (e.g. `price1 / price2` → "how many times bigger is price1"). Division across different currencies is an ERROR rather than a silent conversion, because this preprocessor does not perform currency conversion using exchange rates (see `LIMITATIONS.md`).

**Design decision (D3):** currency literals may be negative (`-₹50.00` parses). A negative *result* from subtraction (e.g. an overdraft) is accepted without special handling, since it is a legitimate value, not a syntax or semantic problem.

## 4. ERROR vs. WARNING semantics

- **WARNING**: the statement still produces a value and is still emitted into the generated C program, but the situation is worth a human's attention (symbol reassignment, bare-number/currency mixing).
- **ERROR**: the statement's result is semantically meaningless. The preprocessor:
  1. Does **not** emit the real C expression — it writes a `/* ERROR: ... skipped */` comment in its place.
  2. Marks the target variable in `invalid_vars`.
  3. If that variable is later passed to `output()`, prints `"<var> = N/A (semantic error)"` instead of attempting to read an uninitialized value.

## 5. I/O rules

- `input(var)` emits `scanf` with `%d` for `int`-typed variables and `%f` for `float`/`currency`-typed variables, matching the variable's actual declared C type.
- `output(var)` emits `printf` with the variable's currency symbol (if any) and two decimal places for currency/float, or `%d` for plain `int`.
- `input()` expects a bare number with no currency symbol. See `LIMITATIONS.md` for what happens if the user types one anyway.