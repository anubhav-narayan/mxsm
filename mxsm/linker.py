"""Static-linker input model for JSON and binary MXSM object files.

This module currently implements the linker's first phase: loading and
validating relocatable JSON objects and MXO binaries. Layout, symbol
resolution, and relocation application build on the normalized
``InputObject`` records.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .object_format import unpack_object


class LinkError(Exception):
    """Raised when an object cannot be accepted by the linker."""


def unpack_executable(data: bytes) -> dict:
    """Decode an MXE executable and return its sparse section representation."""
    header = struct.Struct("<4sHBBBBQH")
    record = struct.Struct("<16sQQQ")
    if len(data) < header.size:
        raise LinkError("truncated MXE header")
    magic, version, address_bytes, data_bytes, endian, section_count, entry, record_count = (
        header.unpack_from(data)
    )
    if magic != b"MXE\0" or version != 1 or record_count != section_count:
        raise LinkError("unsupported MXE executable format")
    table_end = header.size + section_count * record.size
    if table_end > len(data):
        raise LinkError("truncated MXE section table")
    if endian not in {0, 1} or not address_bytes or not data_bytes:
        raise LinkError("invalid MXE header")
    sections = []
    for index in range(section_count):
        raw_name, address, offset, size = record.unpack_from(
            data, header.size + index * record.size
        )
        if offset < table_end or offset + size > len(data):
            raise LinkError(f"invalid MXE payload for section {index}")
        try:
            name = raw_name.split(b"\0", 1)[0].decode("ascii")
        except UnicodeDecodeError as error:
            raise LinkError("MXE section name is not ASCII") from error
        if not name:
            raise LinkError("MXE section has an empty name")
        sections.append({
            "name": name,
            "address": address,
            "data": data[offset:offset + size],
        })
    return {
        "format": "mxsm-executable",
        "version": version,
        "address_width": address_bytes * 8,
        "data_width": data_bytes * 8,
        "endianness": "little" if endian == 0 else "big",
        "entry": entry,
        "sections": sections,
    }


def executable_images(data: bytes) -> dict[str, bytes]:
    """Convert an MXE executable into dense ``ins`` and ``data`` images."""
    executable = unpack_executable(data)
    address_space = 1 << executable["address_width"]
    images = {"ins": bytearray(address_space), "data": bytearray(address_space)}
    for section in executable["sections"]:
        name = section["name"]
        image_name = "ins" if name in {"ins", "nmi", "irq"} else name
        if image_name not in images:
            continue
        end = section["address"] + len(section["data"])
        if section["address"] < 0 or end > address_space:
            raise LinkError(f"section {name!r} exceeds executable address space")
        images[image_name][section["address"]:end] = section["data"]
    return {name: bytes(image) for name, image in images.items()}


@dataclass(frozen=True)
class InputObject:
    """Validated JSON object together with its source name."""

    name: str
    definition: dict

    @property
    def isa_key(self) -> tuple[Any, ...]:
        definition = self.definition
        return (
            definition.get("isa"),
            definition.get("address_width"),
            definition.get("data_width"),
            definition.get("endianness"),
        )


@dataclass
class LinkedSection:
    name: str
    address: int
    data: bytearray


@dataclass
class GlobalSymbol:
    name: str
    section: str
    address: int
    binding: str


class StaticLinker:
    """Collect compatible JSON or MXO objects for a later link operation.

    ``source`` may be a mapping, JSON string, filesystem path, readable text
    stream, or MXO binary bytes. MXO files are decoded into the same normalized
    packed-object representation used by JSON input.
    """

    def __init__(self, isa: dict | None = None):
        self.isa = isa
        self.objects: list[InputObject] = []
        self.section_bases: dict[str, int] = {
            "data": 0,
            "ins": 0,
            "nmi": (isa or {}).get("nmi_vector", 128),
            "irq": (isa or {}).get("irq_vector", 192),
        }
        self.sections: dict[str, LinkedSection] = {}
        self._placements: dict[tuple[str, str], tuple[str, int]] = {}
        self.symbols: dict[str, GlobalSymbol] = {}

    @staticmethod
    def _load_json(source) -> tuple[str, dict]:
        if isinstance(source, bytes):
            try:
                return "<binary>", unpack_object(source)
            except ValueError as error:
                raise LinkError(f"invalid MXO object: {error}") from error
        if isinstance(source, dict):
            return "<mapping>", source
        if hasattr(source, "read"):
            name = getattr(source, "name", "<stream>")
            try:
                return str(name), json.load(source)
            except (json.JSONDecodeError, TypeError) as error:
                raise LinkError(f"{name}: invalid JSON object") from error
        if isinstance(source, Path):
            name = str(source)
            try:
                raw = source.read_bytes()
                if raw.startswith(b"MX"):
                    return name, StaticLinker._load_json(raw)[1]
                return name, json.loads(raw)
            except OSError as error:
                raise LinkError(f"{name}: cannot read object") from error
            except json.JSONDecodeError as error:
                raise LinkError(f"{name}: invalid JSON object") from error
        if isinstance(source, str):
            candidate = Path(source)
            if candidate.exists():
                return StaticLinker._load_json(candidate)
            try:
                return "<json>", json.loads(source)
            except json.JSONDecodeError as error:
                raise LinkError("object source is neither a file nor valid JSON") from error
        raise LinkError("object source must be a mapping, JSON string, path, or readable stream")

    @staticmethod
    def _validate_object(name: str, definition: dict) -> None:
        if not isinstance(definition, dict):
            raise LinkError(f"{name}: object must be a JSON object")
        if definition.get("format") not in {"mxsm-object", "mxsm-packed"}:
            raise LinkError(f"{name}: unsupported object format")
        if definition.get("version") != 1:
            raise LinkError(f"{name}: unsupported object version")
        for field in ("isa", "address_width", "data_width", "endianness"):
            if field not in definition:
                raise LinkError(f"{name}: missing object field {field!r}")
        if definition["endianness"] not in {"big", "little"}:
            raise LinkError(f"{name}: invalid endianness")
        if not isinstance(definition["sections"], list):
            raise LinkError(f"{name}: sections must be an array")
        if not isinstance(definition.get("symbols", {}), dict):
            raise LinkError(f"{name}: symbols must be an object")
        if not isinstance(definition.get("relocations", []), list):
            raise LinkError(f"{name}: relocations must be an array")
        section_names = set()
        for section in definition["sections"]:
            if not isinstance(section, dict) or not isinstance(section.get("name"), str):
                raise LinkError(f"{name}: malformed section record")
            section_name = section["name"]
            if section_name in section_names:
                raise LinkError(f"{name}: duplicate section {section_name!r}")
            section_names.add(section_name)
            if definition["format"] == "mxsm-packed":
                if not isinstance(section.get("address"), int):
                    raise LinkError(f"{name}: section {section_name!r} has no address")
                payload = section.get("data")
                if not isinstance(payload, str):
                    raise LinkError(f"{name}: packed section {section_name!r} has no data")
                try:
                    bytes.fromhex(payload)
                except ValueError as error:
                    raise LinkError(f"{name}: invalid data in section {section_name!r}") from error
            else:
                records = section.get("records")
                if not isinstance(records, list):
                    raise LinkError(f"{name}: section {section_name!r} has no records")
                for record in records:
                    if (
                        not isinstance(record, dict)
                        or not isinstance(record.get("address"), int)
                        or not isinstance(record.get("data"), str)
                    ):
                        raise LinkError(f"{name}: malformed record in section {section_name!r}")
                    try:
                        bytes.fromhex(record["data"])
                    except ValueError as error:
                        raise LinkError(f"{name}: invalid record data in {section_name!r}") from error

    def add_object(self, source) -> InputObject:
        """Load, validate, and retain one JSON or MXO object file."""
        name, definition = self._load_json(source)
        self._validate_object(name, definition)
        candidate = InputObject(name, definition)
        expected = self.isa
        if expected is None:
            self.isa = {
                "isa": definition["isa"],
                "address_width": definition["address_width"],
                "data_width": definition["data_width"],
                "endianness": definition["endianness"],
            }
        elif (
            candidate.definition.get("address_width") != expected.get("address_width")
            or candidate.definition.get("data_width") != expected.get("data_width")
            or candidate.definition.get("endianness") != expected.get("endianness")
            or (
                candidate.definition.get("isa")
                and expected.get("isa")
                and candidate.definition["isa"] != expected["isa"]
            )
        ):
            raise LinkError(f"{name}: object ISA metadata is incompatible with linker")
        self.objects.append(candidate)
        return candidate

    def layout_sections(self) -> dict:
        """Concatenate input sections and preserve fixed interrupt vectors.

        The returned mapping contains ``LinkedSection`` instances. Ordinary
        sections are appended in input order; ``nmi`` and ``irq`` retain their
        configured vector addresses and reject overlaps.
        """
        if not self.objects:
            raise LinkError("cannot lay out an empty link")

        contributions: dict[str, list[tuple[int, bytes]]] = {}
        for obj in self.objects:
            for section in obj.definition["sections"]:
                if obj.definition["format"] == "mxsm-packed":
                    contributions.setdefault(section["name"], []).append(
                        (section["address"], bytes.fromhex(section["data"]))
                    )
                    continue
                records = section["records"]
                if not records:
                    continue
                base = min(record["address"] for record in records)
                end = max(
                    record["address"] + len(bytes.fromhex(record["data"]))
                    for record in records
                )
                payload = bytearray(end - base)
                for record in records:
                    offset = record["address"] - base
                    data = bytes.fromhex(record["data"])
                    payload[offset:offset + len(data)] = data
                contributions.setdefault(section["name"], []).append((base, bytes(payload)))

        result: dict[str, LinkedSection] = {}
        cursors: dict[str, int] = {}
        for name, parts in contributions.items():
            fixed = name in {"nmi", "irq"}
            address = self.section_bases.get(name, 0)
            if not fixed:
                address = cursors.get(name, address)
            payload = bytearray()
            for part_index, (source_address, data) in enumerate(parts):
                if fixed and source_address != self.section_bases.get(name, source_address):
                    raise LinkError(
                        f"section {name!r} has conflicting input address "
                        f"{source_address:#x}"
                    )
                if not fixed and source_address != parts[0][0] and source_address != 0:
                    # Relocatable sections are expected to be section-relative.
                    raise LinkError(
                        f"section {name!r} has non-relative input address "
                        f"{source_address:#x}"
                    )
                payload.extend(data)
            if fixed and address + len(payload) > 1 << self.isa["address_width"]:
                raise LinkError(f"section {name!r} exceeds address space")
            result[name] = LinkedSection(name, address, payload)
            cursors[name] = address + len(payload)
        self.sections = result
        self._placements.clear()
        for object_file in self.objects:
            for section in object_file.definition["sections"]:
                section_name = section["name"]
                if section_name not in result:
                    continue
                if object_file.definition["format"] == "mxsm-packed":
                    source_address = section["address"]
                    data = bytes.fromhex(section["data"])
                else:
                    records = section["records"]
                    if not records:
                        continue
                    source_address = min(record["address"] for record in records)
                    end = max(
                        record["address"] + len(bytes.fromhex(record["data"]))
                        for record in records
                    )
                    payload = bytearray(end - source_address)
                    for record in records:
                        offset = record["address"] - source_address
                        record_data = bytes.fromhex(record["data"])
                        payload[offset:offset + len(record_data)] = record_data
                    data = bytes(payload)
                placement_start = result[section_name].data.find(data)
                if placement_start < 0:
                    raise LinkError(f"cannot place section {section_name!r} from {object_file.name}")
                self._placements[(object_file.name, section_name)] = (
                    section_name,
                    placement_start,
                )
        return result

    def resolve_symbols(self) -> dict:
        if not self.sections:
            self.layout_sections()
        symbols: dict[str, GlobalSymbol] = {}
        for object_file in self.objects:
            for name, symbol in object_file.definition.get("symbols", {}).items():
                section_name = symbol.get("section")
                placement = self._placements.get((object_file.name, section_name))
                if placement is None:
                    raise LinkError(
                        f"{object_file.name}: symbol {name!r} references unknown section"
                    )
                linked_section, placement_offset = placement
                address = (
                    self.sections[linked_section].address
                    + placement_offset
                    + symbol.get("offset", 0)
                )
                if name in symbols:
                    raise LinkError(f"duplicate global symbol {name!r}")
                symbols[name] = GlobalSymbol(name, linked_section, address, "global")
        self.symbols = symbols
        return symbols

    def apply_relocations(self) -> None:
        if not self.symbols:
            self.resolve_symbols()
        for object_file in self.objects:
            for relocation in object_file.definition.get("relocations", []):
                symbol_name = relocation.get("symbol")
                if symbol_name not in self.symbols:
                    raise LinkError(f"undefined symbol {symbol_name!r}")
                section_name = relocation.get("section")
                placement = self._placements.get((object_file.name, section_name))
                if placement is None:
                    raise LinkError(
                        f"{object_file.name}: relocation references unknown section {section_name!r}"
                    )
                linked_section, placement_offset = placement
                width = relocation.get("width")
                if not isinstance(width, int) or width <= 0 or width % 8:
                    raise LinkError("only positive byte-aligned relocations are supported")
                size = width // 8
                offset = placement_offset + relocation.get("offset", 0)
                target = self.symbols[symbol_name].address + relocation.get("addend", 0)
                limit = 1 << width
                if not 0 <= target < limit:
                    raise LinkError(
                        f"relocation for {symbol_name!r} does not fit in {width} bits"
                    )
                data = self.sections[linked_section].data
                if offset < 0 or offset + size > len(data):
                    raise LinkError("relocation points outside section data")
                data[offset:offset + size] = target.to_bytes(
                    size, self.isa["endianness"]
                )

    def link(self, *, entry: str | None = None) -> dict:
        self.layout_sections()
        self.resolve_symbols()
        self.apply_relocations()
        if entry is not None and entry not in self.symbols:
            raise LinkError(f"entry symbol {entry!r} is undefined")
        return {
            "format": "mxsm-executable",
            "version": 1,
            "isa": self.isa.get("isa", ""),
            "address_width": self.isa["address_width"],
            "data_width": self.isa["data_width"],
            "endianness": self.isa["endianness"],
            "entry": self.symbols[entry].address if entry else None,
            "sections": [
                {
                    "name": section.name,
                    "address": section.address,
                    "data": bytes(section.data).hex(),
                }
                for section in self.sections.values()
            ],
            "symbols": {
                name: {"section": symbol.section, "address": symbol.address}
                for name, symbol in self.symbols.items()
            },
            "relocations": [],
        }

    def emit_images(self) -> dict[str, bytes]:
        if not self.sections:
            self.link()
        address_space = 1 << self.isa["address_width"]
        images = {"ins": bytearray(address_space), "data": bytearray(address_space)}
        for name, section in self.sections.items():
            image_name = "ins" if name in {"ins", "nmi", "irq"} else name
            if image_name not in images:
                continue
            end = section.address + len(section.data)
            if end > address_space:
                raise LinkError(f"section {name!r} exceeds address space")
            images[image_name][section.address:end] = section.data
        return {name: bytes(data) for name, data in images.items()}

    def emit_executable(self, *, entry: str | None = None) -> bytes:
        """Emit a compact MXE executable containing linked sparse sections."""
        linked = self.link(entry=entry)
        sections = linked["sections"]
        entry_address = linked["entry"] or 0
        header = struct.Struct("<4sHBBBBQH")
        record = struct.Struct("<16sQQQ")
        table_offset = header.size
        data_offset = table_offset + len(sections) * record.size
        payload = bytearray()
        records = bytearray()
        for section in sections:
            name = section["name"].encode("ascii")
            if len(name) > 15:
                raise LinkError(f"section name {section['name']!r} is too long")
            data = bytes.fromhex(section["data"])
            records.extend(record.pack(
                name + b"\0" * (16 - len(name)),
                section["address"],
                data_offset + len(payload),
                len(data),
            ))
            payload.extend(data)
        return bytes(header.pack(
            b"MXE\0", 1,
            (self.isa["address_width"] + 7) // 8,
            (self.isa["data_width"] + 7) // 8,
            0 if self.isa["endianness"] == "little" else 1,
            len(sections), entry_address, len(sections),
        ) + records + payload)
