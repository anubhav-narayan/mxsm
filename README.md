# MX Assembler

MX Cross Assembler is a command-line tool for assembling machine code for the MX architecture (or theoratically any architecture). This tool takes an assembly source file and a production mapping file in JSON format and generates binary output files for data and instruction segments.

## Features

- **Source Code Parsing**: Reads and tokenizes the MX11 assembly source code(or any other, if you have the correct `prod.json.tab`).
- **Assembly Macros**: Reuse parameterized instruction sequences with local labels. See [docs/macros.md](docs/macros.md).
- **Assembler Reference**: Source layout, directives, symbols, includes, and output formats are documented in [docs/assembler.md](docs/assembler.md).
- **Instruction and Data Segmentation**: Separates `.data` and `.ins` directives into respective memory segments.
- **Code Segmenetation**: Separates the code into `.ins` and `.nmi`, `.irq` sections for interrupt service routines.
- **Symbol Resolution**: Handles labels and symbolic addresses.
- **Binary Generation**: Outputs binary files for both data and instruction segments.
- **Object Generation**: Outputs compact binary MXO files with sections, symbols, and relocations, without allocating the full address space.
- **Static Linking**: Combines JSON or MXO objects and emits a linked JSON map or MXE executable image.
- **Binary Formats**: MXO and MXE layouts are documented in [docs/object-formats.md](docs/object-formats.md).

## Requirements

- Python 3.8+
- `click` library for the command-line interface.
- `json` library for parsing the production mapping.

## Installation

### Using Poetry
1. Clone the repository:

    ```bash
    git clone https://github.com/anubhav-narayan/mxsm.git
    cd mxsm
    ```

2. Install the dependencies using [Poetry](https://python-poetry.org/):

    ```bash
    poetry install
    ```

3. If you want to use the CLI command globally, you can use:

    ```bash
    poetry build
    ```

## Usage

### Static linker

Link assembled object files into a sparse linked map:

```shell
mxsm link main.mxp library.mxp -o linked.mxp
```

Emit an executable MXE image instead:

```shell
mxsm link main.mxo library.mxo --format executable --entry main -o program.mxe
```

The dedicated `mxsm-link` command is also available as an alias.

The executable contains the linked section payloads, load addresses, ISA
width metadata, and entry-point address. Absolute relocations are resolved
during linking; unresolved symbols or incompatible object metadata are errors.

### Assembler directives

The assembler supports these source directives:

```asm
.include "common.mx11"   ; inline another source file (relative to this file)
.import console_write    ; declare a symbol supplied by another object
.export kernel_main      ; publish a symbol for other objects
.byte 0x20, "OK"         ; emit data bytes
.word 0x42               ; emit one ISA data word
.res 16                  ; reserve zero-filled data
.space 16                ; alias for .res
.align 16                ; advance to the next alignment boundary
.org 0x80                ; set the current section address
```

`.import` declarations are retained in JSON objects and unresolved imported
symbols are resolved by the linker through relocations. `.export` declarations
are retained in both JSON and MXO objects.

### Command-Line Interface

```shell
$ mxsm --help
Usage: mxsm [OPTIONS] COMMAND [ARGS]...

  Assemble, disassemble, and statically link MX/11 programs.

Options:
  --help             Show this message and exit.
$
```

Examples:

```shell
mxsm assemble source.mx11 --isa mx11su.json --format mxo -o build/source.mxo
mxsm assemble source.mx11 --isa mx11su.json --format mxp -o build/source.mxp
mxsm assemble source.mx11 --isa mx11su.json --format raw -o build/
mxsm disassemble build/ins.bin --isa mx11su.json -o build/ins.mx11
mxsm extract program.mxe -o build/raw
```

Use `--format mxo` to write the binary `program.mxo` object file. The
file starts with an 8-byte MXSM signature:

```text
MX  address-width-bytes  data-width-bytes  reserved[4]
```

For the MX/11 ISA, the signature is `b"MX\x01\x01\x00\x00\x00\x00"`.
The binary contains fixed-width tables for:

- sections and their virtual load addresses and file payloads;
- symbols as section-relative offsets; and
- absolute relocation entries containing the target section, byte offset,
  symbol index, addend, and field width.

Section payloads are stored once, without full-memory gaps. The `packed` format
name is an alias for the same binary representation. Symbolic fields are
zero-filled in the object and are intended to be resolved by a future static or
dynamic linker.

Examples:

```bash
mxsm --format object source.mx11 mx11su.json
mxsm --format packed source.mx11 mx11su.json
```

## MX/11 ISA spec

```json
{
  "isa": "MX/11-70",
  "address_width": 8,
  "data_width": 8,
  "endianness": "big",
  "nmi_vector": 128,
  "irq_vector": 192,
  "registers": {
    "A": 0, "X": 1, "Y": 2, "D": 3,
    "DAR": 4, "MBR": 5, "INSP": 6, "FLAGS": 7,
    "SA": 8, "SX": 9, "SY": 10, "SD": 11,
    "R0": 12, "R1": 13, "R2": 14, "R3": 15
  },
  "instructions": [
    {"mnemonic": "NOP",  "operands": [], "encoding": "00000000"},
    {"mnemonic": "HALT", "operands": [], "encoding": "11111111"},
    {
      "mnemonic": "MOV",
      "operands": [
        {
          "name": "dst",
          "type": "register",
          "values": {"A": 0, "X": 1, "Y": 2, "D": 3, "SA": 4, "SX": 5, "SY": 6, "SD": 7}
        },
        {
          "name": "src",
          "type": "register",
          "values": {"A": 0, "X": 1, "Y": 2, "D": 3, "DAR": 4, "MBR": 5, "INSP": 6, "FLAGS": 7, "SA": 8, "SX": 9, "SY": 10, "SD": 11, "R0": 12, "R1": 13, "R2": 14, "R3": 15}
        }
      ],
      "encoding": "0 {dst:3} {src:4}",
      "aliases": [
        {
          "operands": ["MBR", "X"],
          "values": {"dst": 1, "src": "X"}
        },
        {
          "operands": ["MBR", "Y"],
          "values": {"dst": 2, "src": "Y"}
        },
        {
          "operands": ["MBR", "D"],
          "values": {"dst": 3, "src": "D"}
        },
        {
          "operands": ["MBR", "SA"],
          "values": {"dst": 4, "src": "SA"}
        },
        {
          "operands": ["MBR", "SX"],
          "values": {"dst": 5, "src": "SX"}
        },
        {
          "operands": ["MBR", "SY"],
          "values": {"dst": 6, "src": "SY"}
        },
        {
          "operands": ["MBR", "SD"],
          "values": {"dst": 7, "src": "SD"}
        }
      ]
    },
    {
      "mnemonic": "CLR",
      "operands": [
        {
          "name": "reg",
          "type": "register",
          "values": {"A": 0, "X": 1, "Y": 2, "D": 3, "SA": 4, "SX": 5, "SY": 6, "SD": 7}
        }
      ],
      "encoding": "10000 {reg:3}"
    },
    {
      "mnemonic": "INCR",
      "operands": [
        {
          "name": "reg",
          "type": "register",
          "values": {"A": 0, "X": 1, "Y": 2, "D": 3, "SA": 4, "SX": 5, "SY": 6, "SD": 7}
        }
      ],
      "encoding": "10001 {reg:3}"
    },
    {
      "mnemonic": "DECR",
      "operands": [
        {
          "name": "reg",
          "type": "register",
          "values": {"A": 0, "X": 1, "Y": 2, "D": 3, "SA": 4, "SX": 5, "SY": 6, "SD": 7}
        }
      ],
      "encoding": "10010 {reg:3}"
    },
    {
      "mnemonic": "NOT",
      "operands": [
        {
          "name": "reg",
          "type": "register",
          "values": {"A": 0, "X": 1, "Y": 2, "D": 3, "SA": 4, "SX": 5, "SY": 6, "SD": 7}
        }
      ],
      "encoding": "10011 {reg:3}"
    },
    {
      "mnemonic": "BNZ",
      "operands": [
        {
          "name": "base",
          "type": "selector",
          "values": {"": 0, "INSP": 1}
        },
        {
          "name": "reg",
          "type": "register",
          "values": {"A": 0, "X": 1, "Y": 2, "D": 3, "SA": 4, "SX": 5, "SY": 6, "SD": 7}
        }
      ],
      "encoding": "1010 {base:1} {reg:3}"
    },
    {
      "mnemonic": "BC",
      "operands": [
        {
          "name": "base",
          "type": "selector",
          "values": {"": 0, "INSP": 1}
        },
        {
          "name": "reg",
          "type": "register",
          "values": {"A": 0, "X": 1, "Y": 2, "D": 3, "SA": 4, "SX": 5, "SY": 6, "SD": 7}
        }
      ],
      "encoding": "1011 {base:1} {reg:3}"
    },
    {
      "mnemonic": "ADD",
      "operands": [
        {
          "name": "pair",
          "type": "selector",
          "values": {"": 0, "X": 1, "Y": 2, "D": 3}
        }
      ],
      "encoding": "110000 {pair:2}",
      "aliases":[
        {
          "operands":["X", "Y"],
          "values":{"pair":0}
        },
        {
          "operands":["A", "X"],
          "values":{"pair":1}
        },
        {
          "operands":["A", "Y"],
          "values":{"pair":2}
        },
        {
          "operands":["A", "D"],
          "values":{"pair":3}
        }
      ]
    },
    {
      "mnemonic": "ADC",
      "operands": [
        {
          "name": "pair",
          "type": "selector",
          "values": {"": 0, "X": 1, "Y": 2, "D": 3}
        }
      ],
      "encoding": "110001 {pair:2}",
      "aliases":[
        {
          "operands":["X", "Y"],
          "values":{"pair":0}
        },
        {
          "operands":["A", "X"],
          "values":{"pair":1}
        },
        {
          "operands":["A", "Y"],
          "values":{"pair":2}
        },
        {
          "operands":["A", "D"],
          "values":{"pair":3}
        }
      ]
    },
    {
      "mnemonic": "SUB",
      "operands": [
        {
          "name": "pair",
          "type": "selector",
          "values": {"": 0, "X": 1, "Y": 2, "D": 3}
        }
      ],
      "encoding": "110010 {pair:2}",
      "aliases":[
        {
          "operands":["X", "Y"],
          "values":{"pair":0}
        },
        {
          "operands":["A", "X"],
          "values":{"pair":1}
        },
        {
          "operands":["A", "Y"],
          "values":{"pair":2}
        },
        {
          "operands":["A", "D"],
          "values":{"pair":3}
        }
      ]
    },
    {
      "mnemonic": "SBC",
      "operands": [
        {
          "name": "pair",
          "type": "selector",
          "values": {"": 0, "X": 1, "Y": 2, "D": 3}
        }
      ],
      "encoding": "110011 {pair:2}",
      "aliases":[
        {
          "operands":["X", "Y"],
          "values":{"pair":0}
        },
        {
          "operands":["A", "X"],
          "values":{"pair":1}
        },
        {
          "operands":["A", "Y"],
          "values":{"pair":2}
        },
        {
          "operands":["A", "D"],
          "values":{"pair":3}
        }
      ]
    },
    {
      "mnemonic": "AND",
      "operands": [
        {
          "name": "pair",
          "type": "selector",
          "values": {"": 0, "X": 1, "Y": 2, "D": 3}
        }
      ],
      "encoding": "110100 {pair:2}",
      "aliases":[
        {
          "operands":["X", "Y"],
          "values":{"pair":0}
        },
        {
          "operands":["A", "X"],
          "values":{"pair":1}
        },
        {
          "operands":["A", "Y"],
          "values":{"pair":2}
        },
        {
          "operands":["A", "D"],
          "values":{"pair":3}
        }
      ]
    },
    {
      "mnemonic": "OR",
      "operands": [
        {
          "name": "pair",
          "type": "selector",
          "values": {"": 0, "X": 1, "Y": 2, "D": 3}
        }
      ],
      "encoding": "110101 {pair:2}",
      "aliases":[
        {
          "operands":["X", "Y"],
          "values":{"pair":0}
        },
        {
          "operands":["A", "X"],
          "values":{"pair":1}
        },
        {
          "operands":["A", "Y"],
          "values":{"pair":2}
        },
        {
          "operands":["A", "D"],
          "values":{"pair":3}
        }
      ]
    },
    {
      "mnemonic": "XOR",
      "operands": [
        {
          "name": "pair",
          "type": "selector",
          "values": {"": 0, "X": 1, "Y": 2, "D": 3}
        }
      ],
      "encoding": "110110 {pair:2}",
      "aliases":[
        {
          "operands":["X", "Y"],
          "values":{"pair":0}
        },
        {
          "operands":["A", "X"],
          "values":{"pair":1}
        },
        {
          "operands":["A", "Y"],
          "values":{"pair":2}
        },
        {
          "operands":["A", "D"],
          "values":{"pair":3}
        }
      ]
    },
    {
      "mnemonic": "CMP",
      "operands": [
        {
          "name": "pair",
          "type": "selector",
          "values": {"": 0, "X": 1, "Y": 2, "D": 3}
        }
      ],
      "encoding": "110111 {pair:2}",
      "aliases":[
        {
          "operands":["X", "Y"],
          "values":{"pair":0}
        },
        {
          "operands":["A", "X"],
          "values":{"pair":1}
        },
        {
          "operands":["A", "Y"],
          "values":{"pair":2}
        },
        {
          "operands":["A", "D"],
          "values":{"pair":3}
        }
      ]
    },
    {
      "mnemonic": "LDI",
      "operands": [
        {
          "name": "imm4",
          "type": "immediate",
          "size": 4
        }
      ],
      "encoding": "1110 {imm4:4}"
    },
    {"mnemonic": "DSEL", "encoding": "11110000"},
    {"mnemonic": "DNXT", "encoding": "11110001"},
    {"mnemonic": "DPRV", "encoding": "11110010"},
    {"mnemonic": "DRET", "encoding": "11110011"},
    {"mnemonic": "CTXS", "encoding": "11110100"},
    {"mnemonic": "CRET", "encoding": "11110101"},
    {"mnemonic": "IRQ", "encoding": "11110110"},
    {"mnemonic": "RTI", "encoding": "11110111"},
    {"mnemonic": "BRZ", "encoding": "11111000"},
    {"mnemonic": "RET", "encoding": "11111001"},
    {"mnemonic": "SFA", "encoding": "11111010"},
    {"mnemonic": "LFA", "encoding": "11111011"},
    {"mnemonic": "LD", "encoding": "11111100"},
    {"mnemonic": "ST", "encoding": "11111101"},
    {"mnemonic": "NMI", "encoding": "11111110"}
  ]
}
```