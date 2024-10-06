# MX Assembler

MX Cross Assembler is a command-line tool for assembling machine code for the MX architecture (or theoratically any architecture). This tool takes an assembly source file and a production mapping file in TOML format and generates binary output files for data and instruction segments.

## Features

- **Source Code Parsing**: Reads and tokenizes the MX11 assembly source code.
- **Instruction and Data Segmentation**: Separates `.data` and `.ins` directives into respective memory segments. More to be added soon.
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