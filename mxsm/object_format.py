"""Compact binary object format for MXSM.

The format is intentionally table-oriented so a future static or dynamic
linker can map sections and apply relocations without understanding JSON.
"""
from __future__ import annotations

import struct


def make_magic(address_width_bytes: int, data_width_bytes: int) -> bytes:
    """Build the 8-byte MXO signature for an ISA's storage widths."""
    if not 0 < address_width_bytes < 256 or not 0 < data_width_bytes < 256:
        raise ValueError("object widths must fit in one byte")
    return b"MX" + bytes((address_width_bytes, data_width_bytes, 0, 0, 0, 0))


# Default signature for an ISA with 1-byte addresses and data values.
MAGIC = make_magic(1, 1)
VERSION = 1
_HEADER = struct.Struct("<8sHHBBBBIIII")
_SECTION = struct.Struct("<IBBHQQQ")
_SYMBOL = struct.Struct("<IHHQ")
_RELOCATION = struct.Struct("<HHQI qHH")


def pack_object(obj: dict) -> bytes:
    """Encode a packed assembler object as a compact MXO binary file."""
    if obj.get("format") != "mxsm-packed":
        raise ValueError("binary objects require a packed MXSM object")
    sections = obj.get("sections", [])
    symbols = obj.get("symbols", {})
    relocations = obj.get("relocations", [])
    section_index = {section["name"]: index for index, section in enumerate(sections)}
    strings = bytearray(b"\0")
    string_offsets = {}

    def string_offset(value: str) -> int:
        if value in string_offsets:
            return string_offsets[value]
        offset = len(strings)
        strings.extend(value.encode("utf-8") + b"\0")
        string_offsets[value] = offset
        return offset

    for section in sections:
        string_offset(section["name"])
    symbol_entries = []
    symbol_index = {}
    for name, symbol in symbols.items():
        symbol_index[name] = len(symbol_entries)
        symbol_entries.append((string_offset(name), section_index[symbol["section"]], symbol["offset"]))

    section_data = [bytes.fromhex(section["data"]) for section in sections]
    section_table_offset = _HEADER.size
    symbol_table_offset = section_table_offset + len(sections) * _SECTION.size
    relocation_table_offset = symbol_table_offset + len(symbol_entries) * _SYMBOL.size
    string_table_offset = relocation_table_offset + len(relocations) * _RELOCATION.size
    data_offset = string_table_offset + len(strings)
    section_table = bytearray()
    payload = bytearray()
    for index, section in enumerate(sections):
        data = section_data[index]
        section_table.extend(_SECTION.pack(
            string_offsets[section["name"]], 1, 0, 1,
            section["address"], data_offset + len(payload), len(data),
        ))
        payload.extend(data)

    relocation_table = bytearray()
    for relocation in relocations:
        relocation_table.extend(_RELOCATION.pack(
            section_index[relocation["section"]], 1, relocation["offset"],
            symbol_index[relocation["symbol"]], relocation.get("addend", 0),
            relocation["width"], 0,
        ))
    header = _HEADER.pack(
        make_magic((obj["address_width"] + 7) // 8, (obj["data_width"] + 7) // 8),
        VERSION, 0, obj["address_width"], obj["data_width"],
        0 if obj["endianness"] == "little" else 1, len(sections),
        section_table_offset, symbol_table_offset, relocation_table_offset,
        string_table_offset,
    )
    symbol_table = b"".join(
        _SYMBOL.pack(name_offset, section, 0, value)
        for name_offset, section, value in symbol_entries
    )
    return bytes(header + section_table + symbol_table + relocation_table + strings + payload)


def unpack_header(data: bytes) -> dict:
    """Read the fixed header, useful for linkers that need not decode payloads."""
    if len(data) < _HEADER.size:
        raise ValueError("truncated MXO header")
    values = _HEADER.unpack_from(data)
    magic = values[0]
    if magic[:2] != b"MX" or magic[4:] != b"\0" * 4 or values[1] != VERSION:
        raise ValueError("unsupported MXSM object format")
    return {
        "version": values[1],
        "magic": magic,
        "address_width_bytes": magic[2],
        "data_width_bytes": magic[3],
        "address_width": values[3],
        "data_width": values[4],
        "endianness": "little" if values[5] == 0 else "big",
        "section_count": values[6],
        "section_table_offset": values[7],
        "symbol_table_offset": values[8],
        "relocation_table_offset": values[9],
        "string_table_offset": values[10],
    }