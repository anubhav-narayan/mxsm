# MX Assembler

MX Cross Assembler is a command-line tool for assembling machine code for the MX architecture (or theoratically any architecture). This tool takes an assembly source file and a production mapping file in JSON format and generates binary output files for data and instruction segments.

## Features

- **Source Code Parsing**: Reads and tokenizes the MX11 assembly source code(or any other, if you have the correct `prod.json.tab`).
- **Instruction and Data Segmentation**: Separates `.data` and `.ins` directives into respective memory segments.
- **Code Segmenetation**: Separates the code into `.ins` and `.nmi`, `.irq` sections for interrupt service routines.
- **Symbol Resolution**: Handles labels and symbolic addresses.
- **Binary Generation**: Outputs binary files for both data and instruction segments.

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

### Command-Line Interface

```shell
$ mxsm --help
Usage: mxsm [OPTIONS] [PROD_FILE] INPUT_FILE

  MXSM - MX Cross Assembler

  2-Pass Cross Architecture Assembler for MX Architecture

  INPUT_FILE: Path to the MX assembly file.

  PROD_FILE: Production table file in JSON. [default: ./prod.tab.json]

Options:
  -o, --output PATH  Directory to save the assembled binary files.  [default:
                     ./build]
  --debug            Print debug information after assembly.
  --help             Show this message and exit.
$
```

## MX11SU `prod.json.tab`

```json
{
  "NMI_ADDR": 128,
  "IRQ_ADDR": 192,
  "INSTRUCTION_LENGTH": 1,
  "DATA_LENGTH": 1,
  "INS": [
    "NOP",
    "NOT",
    "NAND",
    "XOR",
    "XNOR",
    "AND",
    "OR",
    "NOR",
    "ADD",
    "ADC",
    "SUB",
    "SBB",
    "INCR",
    "DECR",
    "X2",
    "CLR",
    "RST",
    "MOV",
    "LDI",
    "LD",
    "ST",
    "SHM",
    "SHL",
    "SHR",
    "ROL",
    "ROR",
    "JNZ",
    "JZ",
    "JNC",
    "JC",
    "JNE",
    "JE",
    "JGT",
    "JLT",
    "RJNZ",
    "RJZ",
    "RJNC",
    "RJC",
    "RJNE",
    "RJE",
    "RJGT",
    "RJLT",
    "HALT"
  ],
  "REGS": [
    "A",
    "X",
    "Y",
    "D",
    "DAR",
    "MBR",
    "INSP",
    "FLAGS",
    "SA",
    "SX",
    "SY",
    "SD",
    "R0",
    "R1",
    "R2",
    "R3"
  ],
  "PROD" : {
    "INSTRUCTION": {
      "idepth": 1,
      "NOP": "00",
      "NOT": "01",
      "NAND": "02",
      "XOR": "03",
      "XNOR": "04",
      "AND": "05",
      "OR": "06",
      "NOR": "07",
      "ADD": "08",
      "ADC": "09",
      "SUB": "0a",
      "SBB": "0b",
      "INCR": "0c",
      "DECR": "0d",
      "X2": "0e",
      "CLR": "0f",
      "RST": "6f",
      "SHM": "94",
      "JNZ": "a0",
      "JZ": "a1",
      "JNC": "a2",
      "JC": "a3",
      "JNE": "a4",
      "JE": "a5",
      "JLT": "a6",
      "JGT": "a7",
      "RJNZ": "a8",
      "RJZ": "a9",
      "RJNC": "aa",
      "RJC": "ab",
      "RJNE": "ac",
      "RJE": "ad",
      "RJLT": "ae",
      "RJGT": "af",
      "INTR": "f2",
      "HALT": "ff"
    },
    "INSTRUCTION,REGISTER": {
      "idepth": 2,
      "MOV": {
        "X": "10",
        "Y": "20",
        "D": "30"
      },
      "NOT": {
        "A": "01",
        "X": "11",
        "Y": "21",
        "D": "31"
      },
      "NAND": {
        "A": "02",
        "X": "12",
        "Y": "22",
        "D": "32"
      },
      "XOR": {
        "A": "03",
        "X": "13",
        "Y": "23",
        "D": "33"
      },
      "XNOR": {
        "A": "04",
        "X": "14",
        "Y": "24",
        "D": "34"
      },
      "AND": {
        "A": "05",
        "X": "15",
        "Y": "25",
        "D": "35"
      },
      "OR": {
        "A": "06",
        "X": "16",
        "Y": "26",
        "D": "36"
      },
      "NOR": {
        "A": "07",
        "X": "17",
        "Y": "27",
        "D": "37"
      },
      "ADD": {
        "A": "08",
        "X": "18",
        "Y": "28",
        "D": "38"
      },
      "ADC": {
        "A": "09",
        "X": "19",
        "Y": "29",
        "D": "39"
      },
      "SUB": {
        "A": "0a",
        "X": "1a",
        "Y": "2a",
        "D": "3a"
      },
      "SBB": {
        "A": "0b",
        "X": "1b",
        "Y": "2b",
        "D": "3b"
      },
      "INCR": {
        "A": "0c",
        "X": "1c",
        "Y": "2c",
        "D": "3c",
        "DAR": "4c",
        "MBR": "5c",
        "INSP": "6c",
        "FLAGS": "7c"
      },
      "DECR": {
        "A": "0d",
        "X": "1d",
        "Y": "2d",
        "D": "3d",
        "DAR": "4d",
        "MBR": "5d",
        "INSP": "6d",
        "FLAGS": "7d"
      },
      "X2": {
        "A": "0e",
        "X": "1e",
        "Y": "2e",
        "D": "3e"
      },
      "CLR": {
        "A": "0f",
        "X": "1f",
        "Y": "2f",
        "D": "3f",
        "DAR": "4f",
        "MBR": "5f",
        "INSP": "6f",
        "FLAGS": "7f"
      },
      "LD": {
        "A": "b0",
        "X": "b1",
        "Y": "b2",
        "FLAGS": "b3",
        "R0": "b4",
        "R1": "b5",
        "R2": "b6",
        "R3": "b7"
      },
      "ST": {
        "A": "b8",
        "X": "b9",
        "Y": "ba",
        "FLAGS": "bb",
        "R0": "bc",
        "R1": "bd",
        "R2": "be",
        "R3": "bf"
      },
      "SHM": {
        "SA": "90",
        "SX": "91",
        "SY": "92",
        "SD": "93",
        "A": "94",
        "X": "95",
        "Y": "96",
        "D": "97"
      }
    },
    "INSTRUCTION,NUMBER": {
      "idepth": 2,
      "LDI": {
        "0": "e0",
        "1": "e1",
        "2": "e2",
        "3": "e3",
        "4": "e4",
        "5": "e5",
        "6": "e6",
        "7": "e7",
        "8": "e8",
        "9": "e9",
        "10": "ea",
        "11": "eb",
        "12": "ec",
        "13": "ed",
        "14": "ee",
        "15": "ef"
      },
      "SHL": {
        "0": "c0",
        "1": "c1",
        "2": "c2",
        "3": "c3",
        "4": "c4",
        "5": "c5",
        "6": "c6",
        "7": "c7"
      },
      "ROL": {
        "0": "c8",
        "1": "c9",
        "2": "ca",
        "3": "cb",
        "4": "cc",
        "5": "cd",
        "6": "ce",
        "7": "cf"
      },
      "SHR": {
        "0": "d0",
        "1": "d1",
        "2": "d2",
        "3": "d3",
        "4": "d4",
        "5": "d5",
        "6": "d6",
        "7": "d7"
      },
      "ROR": {
        "0": "d8",
        "1": "d9",
        "2": "da",
        "3": "db",
        "4": "dc",
        "5": "dd",
        "6": "de",
        "7": "df"
      }
    },
    "INSTRUCTION,REGISTER,REGISTER": {
      "idepth": 3,
      "MOV": {
        "A": {
          "A": "00",
          "X": "10",
          "Y": "20",
          "D": "30",
          "R0": "88"
        },
        "D": {
          "A": "40",
          "X": "50",
          "Y": "60",
          "MBR": "70",
          "R3": "8b"
        },
        "X": {
          "A": "80",
          "Y": "84",
          "D": "86",
          "R1": "89"
        },
        "Y": {
          "A": "81",
          "Y": "85",
          "D": "87",
          "R2": "8a"
        }
      },
      "NOT": {
        "A": {
          "A": "01",
          "X": "11",
          "Y": "21",
          "D": "31"
        },
        "D": {
          "A": "41",
          "X": "51",
          "Y": "61",
          "D": "71"
        }
      },
      "NAND": {
        "D": {
          "A": "42",
          "X": "52",
          "Y": "62",
          "D": "72"
        }
      },
      "XOR": {
        "D": {
          "A": "43",
          "X": "53",
          "Y": "63",
          "D": "73"
        }
      },
      "XNOR": {
        "D": {
          "A": "44",
          "X": "54",
          "Y": "64",
          "D": "74"
        }
      },
      "AND": {
        "D": {
          "A": "45",
          "X": "55",
          "Y": "65",
          "D": "75"
        }
      },
      "OR": {
        "D": {
          "A": "46",
          "X": "56",
          "Y": "66",
          "D": "76"
        }
      },
      "NOR": {
        "D": {
          "A": "47",
          "X": "57",
          "Y": "67",
          "D": "77"
        }
      },
      "ADD": {
        "D": {
          "A": "48",
          "X": "58",
          "Y": "68",
          "D": "78"
        }
      }
    }
  }
}
```