# ISA Specification JSON

An ISA definition is a JSON object loaded by the assembler and disassembler.
It describes architecture-wide settings, registers, and one or more instruction
forms. A mnemonic may have multiple forms, each with its own ordered operands
and encoding. Assembly matches the source operands against those forms.

## Top-Level Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `isa` | Yes | Non-empty name for the composed ISA. |
| `instructions` | Conditional | Legacy flat array of instruction forms. Use this or the structured `control_set`/`domains` form. |
| `control_set` | Conditional | Named object containing shared Control/System instruction forms. |
| `domains` | Conditional | Array of non-control instruction sets, each tagged with a DAR value. |
| `schema_version` | No | Schema version; currently only `1` is supported. Defaults to `1`. |
| `word_size` | No | Default word width in bits. Defaults to `8`. |
| `address_width` | No | Address width in bits. Defaults to `word_size`. |
| `data_width` | No | Data width in bits. Defaults to `word_size`. |
| `endianness` | No | `"big"` or `"little"`; defaults to `"big"`. |
| `registers` | No | Object mapping register names to non-negative integer codes. |
| `base` | No | Relative path to another ISA JSON file to extend. See [Shared Base Specifications](#shared-base-specifications). |

Widths must be positive integers. `word_size` supplies defaults; it does not
limit instruction-pattern widths. The instruction pattern determines an
instruction's encoded size.

```json
{
  "schema_version": 1,
  "isa": "Example8",
  "word_size": 8,
  "address_width": 16,
  "data_width": 8,
  "endianness": "big",
  "registers": {"A": 0, "X": 1},
  "instructions": [
    {
      "mnemonic": "LDI",
      "operands": [{"name": "value", "type": "immediate", "size": 4}],
      "encoding": "1111 {value:4}"
    }
  ]
}
```

Register names and instruction mnemonics use letters or `_` first, followed by
letters, digits, or `_`. Register codes must be unique within the composed
specification. Mnemonic lookup is case-insensitive.

### Control/System Set and DAR Domains

An ISA may separate shared control instructions from instructions selected by
the DAR value. In this form, `control_set` is an object with a descriptive
`name` and an `instructions` array. Each entry in `domains` has a unique
non-negative `dar`, a descriptive `name`, and its own `instructions` array.
Domains may also declare a `registers` object mapping register names to codes.
It overlays the top-level `registers` map: domain entries may add names or
override codes, while unmentioned shared registers remain available. Effective
register codes must be unique within each domain, but may be reused in other
domains. Control/System instructions use only the top-level register map.
An instruction operand's `values` map, when present, still takes precedence
over these maps for that operand. Do not also provide the legacy top-level
`instructions` array.

Control/System instructions are available in every domain and are protected:
the loader rejects a domain encoding that can match a Control/System encoding
of the same bit width. Different DAR domains may reuse encodings because DAR
selects which domain is active. Instruction `operation` strings may document
effects such as DAR transitions; they remain informational and are not
executed by the assembler or disassembler.

```json
{
  "isa": "MX/11-70",
  "control_set": {
    "name": "Control/System",
    "instructions": [
      {"mnemonic": "DSEL", "encoding": "11110000", "operation": "DAR <- A"},
      {"mnemonic": "DRET", "encoding": "11110011", "operation": "DAR <- 0"}
    ]
  },
  "domains": [
    {
      "dar": 0,
      "name": "Base",
      "instructions": [{"mnemonic": "NOP", "encoding": "00000000"}]
    },
    {
      "dar": 1,
      "name": "MXTTY/11",
      "registers": {"RX": 0, "TX": 1},
      "instructions": [{"mnemonic": "TTYOUT", "encoding": "00000001"}]
    }
  ]
}
```

The loaded `ISA` exposes `control_set_name`, `control_instructions`,
`domain_names`, and `domain_instructions`. `all_instructions()` remains a
flattened view for compatibility with existing callers. The older flat
`instructions` form remains supported for ISAs without DAR domains.

## Instruction Forms

Each instruction form has these fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `mnemonic` | Yes | Instruction name. |
| `encoding` | Yes | Bit pattern describing the instruction's fixed bits and operand fields. |
| `operands` | No | Ordered array of operand definitions; defaults to `[]`. |
| `aliases` | No | Alternate source operand spellings and the encoded values they supply. |
| `description` | No | Optional human-readable explanation. |
| `operation` | No | Optional pseudocode describing the state transition. |
| `meta` | No | Optional implementation-specific metadata object. |

`description` and `operation` are strings available on the loaded instruction
form. They are informational and do not affect encoding. `meta` is passed
through to the loaded form; its contents are not validated by the ISA schema.

### Operands

An operand is an object with a required unique `name` and these optional
properties:

| Property | Default | Meaning |
| --- | --- | --- |
| `type` | `"immediate"` | One of `register`, `immediate`, `label`, `selector`, or `memory`. |
| `values` | None | Object mapping accepted names to numeric codes/values. Commonly used for register and selector operands. |
| `signed` | `false` | Treat the encoded field as a signed two's-complement integer. |
| `size` | None | Declared operand size in bits; if supplied, it must be positive and at least as wide as the operand's encoded field. |

Register operands use their `values` map when present, otherwise the top-level
`registers` map. Selector operands normally define a `values` map; an empty-name
entry (`"": 0`) represents the selector's default value and allows it to be
omitted from assembly source. `immediate`, `label`, and `memory` operands can
take numeric values; the assembler also resolves symbols for label and memory
operands.

`size` does not enlarge an encoding field. The field width in `encoding`
controls the value range that can be encoded. For example, `size: 8` paired
with `{value:4}` still encodes only four bits.

### Encoding Patterns

An encoding is a non-empty, whitespace-separated sequence of tokens:

- A token containing only `0` and `1` is a literal bit sequence.
- `{name:WIDTH}` inserts an unsigned field of `WIDTH` bits.
- `{name[HIGH:LOW]}` inserts bits `HIGH` through `LOW` (inclusive) from the
  named operand. `HIGH` must be greater than or equal to `LOW`.

All declared operands must appear in the pattern, and every field in the
pattern must have a corresponding operand. A field may appear in multiple
slices to encode a scattered value, as in this RISC-V branch form:

```json
{
  "mnemonic": "BEQ",
  "operands": [
    {"name": "offset", "signed": true},
    {"name": "rs1", "type": "register"},
    {"name": "rs2", "type": "register"}
  ],
  "encoding": "{offset[12:12]} {offset[10:5]} {rs2:5} {rs1:5} 000 {offset[4:1]} {offset[11:11]} 1100011"
}
```

For an operand used in slices, its effective encoded width is one greater than
its highest referenced bit. Unsigned values range from $0$ to $2^w - 1$; signed
values range from $-2^{w-1}$ to $2^{w-1} - 1$, where $w$ is that effective
width. Negative signed values are encoded in two's complement.

Patterns may have any positive bit width, not only a whole number of bytes.
The encoded byte count is the pattern width rounded up to the next byte; unused
high bits in the first byte are zero. With `"endianness": "little"`, the
resulting byte sequence is reversed. This applies to the complete instruction
encoding, not separately to each operand field.

## Aliases

An alias maps a positional spelling in assembly source to encoded operand
values. Its `operands` array contains the source tokens to match, and `values`
maps every declared operand name to the value used for encoding. The number of
source operands may differ from the instruction form's encoded operand count.
Names are matched case-insensitively.

```json
{
  "mnemonic": "ADD",
  "operands": [{
    "name": "pair",
    "type": "selector",
    "values": {"": 0, "X": 1, "Y": 2}
  }],
  "encoding": "110000 {pair:2}",
  "aliases": [
    {"operands": ["A", "X"], "values": {"pair": 1}},
    {"operands": ["A", "Y"], "values": {"pair": 2}}
  ]
}
```

## Validation and Encoding Overlaps

The loader checks required fields, supported schema version and operand
types, positive widths and sizes, register and operand names, unique register
codes, alias structure, and consistency between operands and encoding fields.
It rejects an exact duplicate instruction definition with the same mnemonic
and encoding.

The loader does **not** detect overlapping encoding patterns with different
mnemonics or different field layouts. Such overlaps can make disassembly
ambiguous; the encoding index returns all matches, while the disassembler uses
the first match in declaration order. Ensure instruction patterns are disjoint
where unique decoding is required.

## Shared Base Specifications

An ISA file may name one relative JSON file in its `base` field. The base's
instruction forms are inherited and the child's forms are appended. Registers
are merged; a repeated register name must keep the same code, and codes must
remain unique across the composed specification. Other settings are inherited
unless the child supplies its own value. The child's `isa` name is used for the
composed spec.

For example, a common MX/11 spec can define shared instructions and registers,
then extension-domain specs can add forms:

```json
{
  "isa": "MX/11-extension-A",
  "base": "mx11-base.json",
  "instructions": [
    {"mnemonic": "EXTA", "operands": [], "encoding": "11110000"}
  ]
}
```

The `base` path is relative to the file containing the reference. Base
references can be chained, and circular references are rejected. A base must
be loaded from a file because the reference is resolved relative to that file.
The loader merges definitions; it does not allocate opcode ranges or reject
overlapping patterns. Authors are responsible for keeping inherited and
extension encodings disjoint when the architecture requires unique decoding.
