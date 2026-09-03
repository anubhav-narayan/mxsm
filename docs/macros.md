# Assembly Macros

Macros let you name a reusable group of assembly lines. Define a macro with
`.macro` and finish it with `.endmacro`:

```asm
.macro CLEAR
    CLR
    CLR FLAGS
.endmacro

.ins
    CLEAR
```

The macro body is expanded before the source is assembled. A macro may be
invoked before its definition, and macro invocations may expand other macros.

## Arguments

Declare parameters after the macro name. Substitute them in the body with a
backslash:

```asm
.macro MOVE dst, src
    MOV \dst, \src
.endmacro

MOVE A, X
MOVE A, src=Y
```

Arguments can be positional or named. Positional arguments must come before
named arguments, and every declared parameter must be supplied. Arguments are
separated by commas; quoted strings may contain commas or semicolons.

## Local labels

Use `%%name` for a label that should be private to one expansion:

```asm
.macro LOOP
%%again:
    JNZ %%again
.endmacro

LOOP
LOOP
```

Each expansion receives a different generated label, so the two invocations do
not collide.

## Restrictions and errors

- Macro definitions cannot be nested.
- Section and function directives (`.data`, `.ins`, `.nmi`, `.irq`,
  `.function`, and `.endfunction`) are not allowed in macro bodies.
- Recursive expansion is rejected.
- Missing, duplicate, or unknown arguments are errors.
- A macro definition must have a matching `.endmacro`.

Comments begin with `;`, except inside quoted strings.
