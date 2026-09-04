# MXSM Assembler Source Format

This guide describes the source syntax accepted by the ISA-driven, two-pass
MXSM assembler.

## Minimal source file

An assembly file is a sequence of comments, labels, directives, and
instructions. Code defaults to the `.ins` section:

```asm
; A comment
.ins
.export start

start:
    NOP
    HALT
```

Use the ISA JSON file for the target architecture:

```shell
mxsm assemble program.mx11 --isa mx11su.json --format mxo -o build/program.mxo
```

The assembler performs two passes. The first pass collects labels and sizes
sections; the second resolves symbols and encodes instructions and data.
Forward references are therefore allowed.

## Lexical rules

- Mnemonics, registers, labels, and symbols are case-insensitive where the
  selected ISA defines them.
- Labels have the form `name:` and may contain letters, digits, and `_`, but
  cannot begin with a digit.
- Comments begin with `;`. A semicolon inside a quoted string is data.
- Numbers accept decimal, hexadecimal (`0x2a`), binary (`0b101010`), and octal
  notation.
- Prefix an address or symbolic address with `&`, for example `&start` or
  `&0x80`.
- Instruction operands are separated by whitespace and commas according to
  the selected ISA definition.

## Sections

The current section is changed by:

```asm
.data                    ; data bytes and words
.ins                     ; normal instructions (the default)
.nmi                     ; non-maskable interrupt handler
.irq                     ; interrupt handler
```

`.nmi` and `.irq` use the vector addresses from the ISA definition. For the
MX/11-70 definition these are `0x80` and `0xc0`.

## Symbols and modules

Define a symbol with a label:

```asm
.ins
start:
    NOP

.data
message:
    .byte "Hello", 0
```

Use `.import` for a symbol supplied by another object file and `.export` to
make a local symbol available to other objects:

```asm
.import console_write
.export kernel_main

.ins
kernel_main:
    ; reference syntax depends on the instruction's operand definition
    NOP
```

Imported references are emitted as relocations and are resolved by the static
linker. An exported name must be defined in the same source file. Duplicate
global definitions are rejected by the linker.

## Data and layout directives

These directives are valid in `.data`:

```asm
.byte 0x01, 2, "text"    ; emit bytes; strings expand to their characters
.word 0x1234              ; emit one ISA-sized data word
.res 64                   ; reserve 64 zero-filled bytes
.space 64                 ; alias for .res
```

`.align` advances the current section location to the next multiple of its
positive numeric argument. `.org` sets the current section location to an
explicit non-negative address:

```asm
.data
.align 16
table:
    .res 16

.ins
.org 0x40
entry:
    NOP
```

These directives produce sparse object sections. Gaps are preserved in packed
objects and zero-filled in raw images.

## Includes and macros

Include another source file inline. Paths are resolved relative to the file
containing the directive:

```asm
.include "constants.mx11"
```

Macros are expanded before tokenization. See
[macros.md](macros.md) for parameters, named arguments, and local labels.
Section changes and layout directives should remain outside macro bodies.

## Output formats

The assembler supports:

- `raw`: writes `ins.bin` and `data.bin` to the output directory.
- `mxo`: writes a binary relocatable object containing sections, symbols, and
  relocations.
- `mxp`: writes a human-readable JSON packed object.

For multiple source files, assemble each module as `mxo` or `mxp`, then link
them with `mxsm link` or `mxsm-link`.

## Complete example

```asm
; kernel.mx11
.include "io.inc"
.import console_write
.export start

.data
banner:
    .byte "Batch OS", 0

.ins
start:
    NOP
    ; call/argument syntax is defined by the selected ISA
    HALT

.nmi
nmi_handler:
    RTI

.irq
irq_handler:
    RTI
```
