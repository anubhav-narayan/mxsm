"""Command-line interface for assembling, disassembling, and linking MXSM files.

The preferred interface is subcommand-based::

    mxsm assemble kernel.mx11 --isa mx11su.json --format object -o build/kernel.mxo
    mxsm disassemble program.bin --isa mx11su.json -o program.mx11
    mxsm link build/*.mxo --format executable --entry start -o program.mxe

``mxsm-link`` remains available as a dedicated alias for the ``link`` command.
"""

from __future__ import annotations

import json
import pprint
from pathlib import Path
from typing import Literal

import click

from .assembler import Assembler
from .disassembler import Disassembler
from .linker import LinkError, StaticLinker, executable_images
from .readelf import format_mx_file


def _load_isa(path: Path) -> str:
    try:
        return path.read_text()
    except OSError as error:
        raise click.ClickException(f"cannot read ISA file {path}: {error}") from error


def _write(path: Path, content: str | bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)
    except OSError as error:
        raise click.ClickException(f"cannot write {path}: {error}") from error


def _validate_mif_width(ctx: click.Context, param: click.Parameter, value: int) -> int:
    if value % 8:
        raise click.BadParameter("must be a multiple of 8 bits", ctx=ctx, param=param)
    return value


def _mif_content(data: bytes, width: int, byte_order: Literal["big", "little"]) -> str:
    bytes_per_word = width // 8
    padded_data = data + b"\x00" * (-len(data) % bytes_per_word)
    words = (
        int.from_bytes(padded_data[offset:offset + bytes_per_word], byte_order)
        for offset in range(0, len(padded_data), bytes_per_word)
    )
    lines = [
        f"WIDTH={width};",
        f"DEPTH={len(padded_data) // bytes_per_word};",
        "",
        "ADDRESS_RADIX=HEX;",
        "DATA_RADIX=HEX;",
        "",
        "CONTENT BEGIN",
    ]
    lines.extend(
        f"    {address:02X} : {value:0{width // 4}X};"
        for address, value in enumerate(words)
    )
    lines.append("END;")
    return "\n".join(lines) + "\n"


@click.command("bin2mif")
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True,
              help="Output MIF file.")
@click.option("--width", type=click.IntRange(min=8), default=8, show_default=True,
              callback=_validate_mif_width, help="MIF word width in bits (a multiple of 8).")
@click.option("--byte-order", type=click.Choice(["big", "little"]), default="big",
              show_default=True, help="Byte order within multi-byte words.")
def bin2mif_main(input_file: Path, output: Path, width: int, byte_order: Literal["big", "little"]) -> None:
    """Convert RAW binary INPUT_FILE to a MIF file."""
    try:
        _write(output, _mif_content(input_file.read_bytes(), width, byte_order))
    except OSError as error:
        raise click.ClickException(str(error)) from error


@click.command("hex2mif")
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True,
              help="Output MIF file.")
@click.option("--width", type=click.IntRange(min=8), default=8, show_default=True,
              callback=_validate_mif_width, help="MIF word width in bits (a multiple of 8).")
@click.option("--byte-order", type=click.Choice(["big", "little"]), default="big",
              show_default=True, help="Byte order within multi-byte words.")
def hex2mif_main(input_file: Path, output: Path, width: int, byte_order: Literal["big", "little"]) -> None:
    """Convert whitespace-separated hexadecimal bytes in INPUT_FILE to MIF."""
    try:
        data = bytes.fromhex(input_file.read_text())
    except OSError as error:
        raise click.ClickException(str(error)) from error
    except ValueError as error:
        raise click.ClickException(f"invalid hexadecimal input in {input_file}: {error}") from error
    _write(output, _mif_content(data, width, byte_order))


@click.group()
def main() -> None:
    """Assemble, disassemble, and statically link MX/11 programs."""


@main.command("assemble")
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--isa", "isa_file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default="mx11su.json", show_default=True, help="ISA definition JSON.")
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True,
              help="Output file, or directory for raw images.")
@click.option("--format", "output_format", type=click.Choice(["raw", "mxo", "mxp"]),
              default="raw", show_default=True, help="Output format.")
@click.option("--debug", is_flag=True, help="Print assembler debug information.")
def assemble_main(input_file: Path, isa_file: Path, output: Path, output_format: str, debug: bool) -> None:
    """Assemble INPUT_FILE using ISA into raw, MXO, or JSON MXP output."""
    try:
        source = input_file.read_text()
        assembler = Assembler(_load_isa(isa_file))
        if output_format == "mxo":
            result: str | bytes = assembler.assemble_binary_object(source, source_name=str(input_file))
        elif output_format == "mxp":
            result = json.dumps(
                assembler.assemble_object(source, packed=True, source_name=str(input_file)),
                indent=2,
            )
        else:
            assembler.assemble(source, source_name=str(input_file))
            output.mkdir(parents=True, exist_ok=True)
            _write(output / "ins.bin", assembler.ins)
            _write(output / "data.bin", assembler.data)
            result = ""
        if output_format != "raw":
            _write(output, result)
        if debug:
            click.echo(pprint.pformat(assembler.debug_info))
    except (OSError, TypeError, ValueError) as error:
        raise click.ClickException(str(error)) from error


@main.command("disassemble")
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--isa", "isa_file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default="mx11su.json", show_default=True, help="ISA definition JSON.")
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True,
              help="Assembly output file.")
def disassemble_main(input_file: Path, isa_file: Path, output: Path) -> None:
    """Disassemble binary INPUT_FILE into assembly source."""
    try:
        disassembler = Disassembler(_load_isa(isa_file))
        disassembler.disassemble(input_file.read_bytes())
        _write(output, disassembler.string_decoding)
    except (OSError, TypeError, ValueError) as error:
        raise click.ClickException(str(error)) from error


@click.command("mxsm-link")
@click.argument("object_files", nargs=-1, required=True,
                type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True,
              help="Output linked map or executable.")
@click.option("--isa", "isa_file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="ISA JSON file supplying vector addresses.")
@click.option("--format", "output_format", type=click.Choice(["linked", "executable"]),
              default="linked", show_default=True)
@click.option("--entry", help="Entry-point symbol for executable output.")
@click.option("--debug", is_flag=True, help="Print the linked representation.")
def link_main(object_files: tuple[Path, ...], output: Path, isa_file: Path | None,
              output_format: str, entry: str | None, debug: bool) -> None:
    """Link MXO or MXP object files into a linked map or MXE executable."""
    try:
        isa = json.loads(_load_isa(isa_file)) if isa_file else None
        linker = StaticLinker(isa)
        for object_file in object_files:
            linker.add_object(object_file)
        result = linker.link(entry=entry)
        if output_format == "executable":
            _write(output, linker.emit_executable(entry=entry))
        else:
            result["format"] = "mxsm-linked"
            _write(output, json.dumps(result, indent=2))
        if debug:
            click.echo(json.dumps(result, indent=2))
    except (OSError, LinkError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise click.ClickException(str(error)) from error


main.add_command(link_main, "link")
main.add_command(bin2mif_main)
main.add_command(hex2mif_main)


@click.command("readmx", context_settings={"help_option_names": ["--help"]})
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-h", "--file-header", "show_header", is_flag=True, help="Display the file header.")
@click.option("-S", "--sections", "show_sections", is_flag=True, help="Display section headers.")
@click.option("-s", "--symbols", "show_symbols", is_flag=True, help="Display the symbol table.")
@click.option("-r", "--relocations", "show_relocations", is_flag=True,
              help="Display relocation entries.")
@click.option("-a", "--all", "show_all", is_flag=True, help="Display all available information.")
def readelf_main(
    input_file: Path,
    show_header: bool,
    show_sections: bool,
    show_symbols: bool,
    show_relocations: bool,
    show_all: bool,
) -> None:
    """Display information about an MXO object or MXE executable."""
    if show_all or not any((show_header, show_sections, show_symbols, show_relocations)):
        show_header = show_sections = show_symbols = show_relocations = True
    try:
        click.echo(format_mx_file(
            str(input_file),
            input_file.read_bytes(),
            show_header=show_header,
            show_sections=show_sections,
            show_symbols=show_symbols,
            show_relocations=show_relocations,
        ))
    except (OSError, LinkError, TypeError, ValueError) as error:
        raise click.ClickException(str(error)) from error


main.add_command(readelf_main, "readelf")


@main.command("extract")
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True,
              help="Directory for ins.bin and data.bin.")
def extract_main(input_file: Path, output: Path) -> None:
    """Extract dense raw instruction/data binaries from an MXE executable."""
    try:
        _name = input_file.name.split(".")[0]
        images = executable_images(input_file.read_bytes())
        output.mkdir(parents=True, exist_ok=True)
        _write(output / f"{_name}_ins.bin", images["ins"])
        _write(output / f"{_name}_data.bin", images["data"])
    except (OSError, LinkError) as error:
        raise click.ClickException(str(error)) from error


if __name__ == "__main__":
    main()
