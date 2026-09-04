"""Compact binary object format for MXSM.

The binary layout is little-endian for its metadata tables. Section payload
bytes retain the ISA endianness recorded in the header.

MXO file layout
===============

| Offset              | Size              | Table/field                  |
|---------------------|-------------------|------------------------------|
| 0                   | 32                | Fixed header                 |
| ``section_table_offset`` | ``32 * section_count`` | Section table       |
| ``symbol_table_offset``  | ``16 * symbol_count``  | Symbol table        |
| ``relocation_table_offset`` | ``28 * relocation_count`` | Relocation table |
| ``string_table_offset`` | variable          | NUL-terminated UTF-8 strings |
| ``data_offset``      | variable          | Concatenated section payloads |

Fixed header (``<8sHHBBBBIIII``)
--------------------------------

| Field                    | Type/size | Meaning                                  |
|--------------------------|-----------|------------------------------------------|
| magic                    | 8 bytes   | ``MX`` + address/data byte widths + NULs |
| version                  | uint16    | Object format version                    |
| flags                    | uint16    | Reserved; currently zero                 |
| address_width            | uint8     | ISA address width in bits                |
| data_width               | uint8     | ISA data width in bits                   |
| endianness               | uint8     | 0 = little, 1 = big                      |
| section_count            | uint8     | Number of section records                |
| section_table_offset     | uint32    | File offset of section table             |
| symbol_table_offset      | uint32    | File offset of symbol table              |
| relocation_table_offset  | uint32    | File offset of relocation table          |
| string_table_offset      | uint32    | File offset of string table              |

Section record (``<IBBHQQQ``, 32 bytes)
----------------------------------------

| Field       | Type/size | Meaning                                      |
|-------------|-----------|----------------------------------------------|
| name_offset | uint32    | Offset of section name in string table       |
| kind        | uint8     | Section kind; currently 1                    |
| flags       | uint8     | Section flags; currently zero                |
| alignment   | uint16    | Section alignment; currently 1               |
| address     | uint64    | Virtual/load address                         |
| file_offset | uint64    | File offset of section payload              |
| size        | uint64    | Payload size in bytes                        |

Symbol record (``<IHHQ``, 16 bytes)
------------------------------------

| Field       | Type/size | Meaning                                      |
|-------------|-----------|----------------------------------------------|
| name_offset | uint32    | Offset of symbol name in string table        |
| section     | uint16    | Zero-based section-table index               |
| flags       | uint16    | Reserved; currently zero                     |
| offset      | uint64    | Section-relative symbol offset               |

Relocation record (``<HHQI qHH``, 28 bytes)
--------------------------------------------

| Field       | Type/size | Meaning                                      |
|-------------|-----------|----------------------------------------------|
| section     | uint16    | Section containing the relocation             |
| type        | uint16    | Relocation type; currently 1 (absolute)      |
| offset      | uint64    | Byte offset within the target section        |
| symbol      | uint32    | Zero-based symbol-table index                |
| addend      | int64     | Signed adjustment applied by the linker      |
| width       | uint16    | Relocated field width in bits                |
| reserved    | uint16    | Reserved; currently zero                     |

The string table starts with a NUL byte. Names are stored once as
NUL-terminated UTF-8 strings, and table records refer to them by byte offset.
Section payloads are concatenated after the string table and located using
each section record's ``file_offset`` and ``size``.

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
    exported = set(obj.get("exports", []))
    imported = set(obj.get("imports", []))
    for name, symbol in symbols.items():
        symbol_index[name] = len(symbol_entries)
        symbol_entries.append((
            string_offset(name),
            section_index[symbol["section"]],
            symbol["offset"],
            1 if name in exported else 0,
        ))
    for name in sorted(imported - symbols.keys()):
        symbol_index[name] = len(symbol_entries)
        symbol_entries.append((string_offset(name), 0, 0, 2))

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
        _SYMBOL.pack(name_offset, section, flags, value)
        for name_offset, section, value, flags in symbol_entries
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


def unpack_object(data: bytes) -> dict:
    """Decode a packed MXO binary object into the JSON object representation."""
    header = unpack_header(data)
    section_count = header["section_count"]
    section_table_offset = header["section_table_offset"]
    symbol_table_offset = header["symbol_table_offset"]
    relocation_table_offset = header["relocation_table_offset"]
    string_table_offset = header["string_table_offset"]
    if not (
        _HEADER.size <= section_table_offset <= symbol_table_offset
        <= relocation_table_offset <= string_table_offset <= len(data)
    ):
        raise ValueError("invalid MXO table offsets")

    section_end = section_table_offset + section_count * _SECTION.size
    if section_end > symbol_table_offset:
        raise ValueError("truncated MXO section table")

    strings = data[string_table_offset:]

    def read_string(offset: int) -> str:
        if offset >= len(strings):
            raise ValueError("invalid MXO string offset")
        end = strings.find(b"\0", offset)
        if end < 0:
            raise ValueError("unterminated MXO string")
        return strings[offset:end].decode("utf-8")

    sections = []
    for index in range(section_count):
        values = _SECTION.unpack_from(data, section_table_offset + index * _SECTION.size)
        name_offset, _kind, _flags, _alignment, address, file_offset, size = values
        if file_offset + size > len(data):
            raise ValueError("truncated MXO section payload")
        sections.append({
            "name": read_string(name_offset),
            "address": address,
            "data": data[file_offset:file_offset + size].hex(),
        })

    symbol_size = relocation_table_offset - symbol_table_offset
    if symbol_size % _SYMBOL.size:
        raise ValueError("invalid MXO symbol table size")
    symbols = {}
    exports = []
    imports = []
    symbol_names = []
    section_names = [section["name"] for section in sections]
    for index in range(symbol_size // _SYMBOL.size):
        name_offset, section, flags, offset = _SYMBOL.unpack_from(
            data, section_end + index * _SYMBOL.size
        )
        name = read_string(name_offset)
        symbol_names.append(name)
        if flags & 2:
            imports.append(name)
            continue
        if section >= len(section_names):
            raise ValueError("invalid MXO symbol section")
        symbols[name] = {
            "section": section_names[section],
            "offset": offset,
        }
        if flags & 1:
            exports.append(name)

    relocation_size = string_table_offset - relocation_table_offset
    if relocation_size % _RELOCATION.size:
        raise ValueError("invalid MXO relocation table size")
    relocations = []
    for index in range(relocation_size // _RELOCATION.size):
        section, relocation_type, offset, symbol, addend, width, _reserved = (
            _RELOCATION.unpack_from(data, relocation_table_offset + index * _RELOCATION.size)
        )
        if section >= len(section_names) or symbol >= len(symbol_names):
            raise ValueError("invalid MXO relocation reference")
        relocations.append({
            "section": section_names[section],
            "offset": offset,
            "symbol": symbol_names[symbol],
            "type": "absolute" if relocation_type == 1 else relocation_type,
            "addend": addend,
            "width": width,
        })

    return {
        "format": "mxsm-packed",
        "version": header["version"],
        "isa": "",
        "address_width": header["address_width"],
        "data_width": header["data_width"],
        "endianness": header["endianness"],
        "sections": sections,
        "symbols": symbols,
        "relocations": relocations,
        "imports": imports,
        "exports": exports,
    }