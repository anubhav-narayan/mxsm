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

import click

from .assembler import Assembler
from .disassembler import Disassembler
from .linker import LinkError, StaticLinker, executable_images


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
