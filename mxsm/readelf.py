"""Human-readable inspection of MXO objects and MXE executables."""
from __future__ import annotations

from .linker import unpack_executable
from .object_format import unpack_header, unpack_object


def format_mx_file(
    filename: str,
    data: bytes,
    *,
    show_header: bool,
    show_sections: bool,
    show_symbols: bool,
    show_relocations: bool,
) -> str:
    """Return a readelf-style summary of a binary MXO or MXE file."""
    if data.startswith(b"MXE\0"):
        file_type = "MXE executable"
        executable = unpack_executable(data)
        obj = None
        header = {
            "version": executable["version"],
            "address_width": executable["address_width"],
            "data_width": executable["data_width"],
            "endianness": executable["endianness"],
            "section_count": len(executable["sections"]),
            "entry": executable["entry"],
        }
        sections = executable["sections"]
    elif data[:2] == b"MX":
        file_type = "MXO relocatable object"
        header = unpack_header(data)
        obj = unpack_object(data)
        sections = obj["sections"]
    else:
        raise ValueError("unrecognized file: expected an MXO object or MXE executable")

    lines = [f"File: {filename}", f"Format: {file_type}"]
    if show_header:
        lines.extend(("", "File Header:"))
        lines.extend((
            f"  Version:         {header['version']}",
            f"  Address width:   {header['address_width']} bits",
            f"  Data width:      {header['data_width']} bits",
            f"  Endianness:      {header['endianness']}",
            f"  Section count:   {header['section_count']}",
        ))
        if obj is None:
            lines.append(f"  Entry address:   0x{header['entry']:X}")
        else:
            lines.extend((
                f"  Section table:   0x{header['section_table_offset']:X}",
                f"  Symbol table:    0x{header['symbol_table_offset']:X}",
                f"  Relocation table: 0x{header['relocation_table_offset']:X}",
                f"  String table:    0x{header['string_table_offset']:X}",
            ))

    if show_sections:
        lines.extend(("", "Section Headers:"))
        lines.append("  [Nr] Name             Address          Size")
        for index, section in enumerate(sections):
            payload = section["data"]
            size = len(payload) // 2 if isinstance(payload, str) else len(payload)
            lines.append(
                f"  [{index:2}] {section['name']:<16} "
                f"0x{section['address']:016X} {size:8d}"
            )

    if show_symbols:
        lines.extend(("", "Symbol Table:"))
        if obj is None:
            lines.append("  No symbol table in MXE executable.")
        elif not obj["symbols"] and not obj["imports"]:
            lines.append("  No symbols.")
        else:
            lines.append("  [Nr] Name                 Section      Value      Binding")
            for index, name in enumerate((*obj["symbols"], *obj["imports"])):
                if name in obj["symbols"]:
                    symbol = obj["symbols"][name]
                    section = symbol["section"]
                    value = symbol["offset"]
                    binding = "GLOBAL" if name in obj["exports"] else "LOCAL"
                else:
                    section = "UND"
                    value = 0
                    binding = "IMPORT"
                lines.append(
                    f"  [{index:2}] {name:<20} {section:<12} "
                    f"0x{value:08X} {binding}"
                )

    if show_relocations:
        lines.extend(("", "Relocations:"))
        if obj is None:
            lines.append("  No relocation table in MXE executable.")
        elif not obj["relocations"]:
            lines.append("  No relocations.")
        else:
            lines.append("  [Nr] Section      Offset     Type       Symbol             Addend   Width")
            for index, relocation in enumerate(obj["relocations"]):
                lines.append(
                    f"  [{index:2}] {relocation['section']:<12} "
                    f"0x{relocation['offset']:08X} "
                    f"{str(relocation['type']):<10} "
                    f"{relocation['symbol']:<20} "
                    f"{relocation['addend']:7d} {relocation['width']:5d}"
                )

    return "\n".join(lines)


__all__ = ["format_mx_file"]
