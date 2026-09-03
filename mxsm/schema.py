"""Validated, architecture-neutral ISA specification model."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from itertools import product
from typing import Dict, List, Optional, Tuple

from .bitfield import BitPattern, EncodingError


class ISAError(Exception):
    """Raised when an ISA specification is invalid or cannot be resolved."""


_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OPERAND_TYPES = {"register", "immediate", "label", "selector", "memory"}


@dataclass
class OperandDef:
    name: str
    type: str = "immediate"
    values: Optional[Dict[str, int]] = None
    signed: bool = False
    size: Optional[int] = None


@dataclass
class InstructionDef:
    mnemonic: str
    operands: List[OperandDef]
    encoding: str
    meta: Dict = field(default_factory=dict)
    aliases: List[Dict[str, object]] = field(default_factory=list)
    pattern: BitPattern = field(init=False, repr=False)

    def __post_init__(self):
        try:
            self.pattern = BitPattern(self.encoding)
        except EncodingError as error:
            raise ISAError(f"{self.mnemonic}: {error}") from error
        names = [operand.name for operand in self.operands]
        if len(names) != len(set(names)):
            raise ISAError(f"{self.mnemonic}: duplicate operand name")
        declared = set(names)
        unknown = self.pattern.field_names - declared
        if unknown:
            raise ISAError(f"{self.mnemonic}: encoding references undeclared operand(s) {sorted(unknown)}")
        unused = declared - self.pattern.field_names
        if unused:
            raise ISAError(f"{self.mnemonic}: operand(s) {sorted(unused)} are not encoded")
        for operand in self.operands:
            width = self.pattern.field_widths[operand.name]
            if operand.size is not None and operand.size < width:
                raise ISAError(f"{self.mnemonic}.{operand.name}: declared size {operand.size} is smaller than encoded width {width}")

    @property
    def size_bytes(self) -> int:
        return self.pattern.width_bytes

    def encode(self, values: Dict[str, int], *, endianness: str = "big") -> bytes:
        definitions = {operand.name: operand for operand in self.operands}
        for name, value in values.items():
            if name not in definitions:
                continue
            if not isinstance(value, int) or isinstance(value, bool):
                raise EncodingError(f"value for field '{name}' must be an integer")
            width = self.pattern.field_widths[name]
            minimum, maximum = (-(1 << (width - 1)), (1 << (width - 1)) - 1) if definitions[name].signed else (0, (1 << width) - 1)
            if not minimum <= value <= maximum:
                raise EncodingError(f"value {value} for field '{name}' is outside the {width}-bit range [{minimum}, {maximum}]")
        encoded = dict(values)
        for name, value in encoded.items():
            if name in definitions and definitions[name].signed and value < 0:
                encoded[name] = value + (1 << self.pattern.field_widths[name])
        try:
            return self.pattern.encode(encoded, endianness=endianness)
        except EncodingError as error:
            raise EncodingError(f"{self.mnemonic}: {error}") from error


class ISA:
    """An ISA spec with list-based public names and form lookup methods."""

    def __init__(self, spec: dict, forms: Dict[str, List[InstructionDef]], register_codes: Dict[str, int]):
        self.spec = spec
        self.name = spec["isa"]
        self.schema_version = spec.get("schema_version", 1)
        self.word_size = spec.get("word_size", 8)
        self.address_width = spec.get("address_width", self.word_size)
        self.data_width = spec.get("data_width", self.word_size)
        self.endianness = spec.get("endianness", "big")
        self._forms = forms
        self._register_codes = register_codes

    @property
    def instructions(self) -> List[str]:
        """Instruction mnemonic names in declaration order."""
        return list(self._forms)

    @property
    def registers(self) -> List[str]:
        """Register names in declaration order."""
        return list(self._register_codes)

    @property
    def mnemonics(self) -> set[str]:
        return set(self.instructions)

    @classmethod
    def from_dict(cls, spec: dict) -> "ISA":
        if not isinstance(spec, dict):
            raise ISAError(f"ISA definition must be an object, got {type(spec).__name__}")
        try:
            name, raw_instructions = spec["isa"], spec["instructions"]
        except KeyError as error:
            raise ISAError(f"ISA definition missing required key: {error}") from error
        version = spec.get("schema_version", 1)
        if not isinstance(name, str) or not name.strip():
            raise ISAError("isa must be a non-empty string")
        if not isinstance(version, int) or isinstance(version, bool) or version != 1:
            raise ISAError(f"schema_version must be 1, got {version!r}")
        for key in ("word_size", "address_width", "data_width"):
            width = spec.get(key, spec.get("word_size", 8))
            if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
                raise ISAError(f"{key} must be a positive integer, got {width!r}")
        endianness = spec.get("endianness", "big")
        if endianness not in ("big", "little"):
            raise ISAError("endianness must be 'big' or 'little'")
        if not isinstance(raw_instructions, list):
            raise ISAError("instructions must be an array")
        raw_registers = spec.get("registers", {})
        if not isinstance(raw_registers, dict):
            raise ISAError("registers must be an object mapping names to integer codes")
        register_codes = {}
        for register, code in raw_registers.items():
            if not isinstance(register, str) or not _NAME_RE.fullmatch(register):
                raise ISAError(f"invalid register name: {register!r}")
            if not isinstance(code, int) or isinstance(code, bool) or code < 0:
                raise ISAError(f"register {register!r} code must be a non-negative integer")
            if code in register_codes.values():
                raise ISAError(f"duplicate register code: {code}")
            register_codes[register] = code
        forms: Dict[str, List[InstructionDef]] = {}
        seen = set()
        for index, raw in enumerate(raw_instructions):
            if not isinstance(raw, dict):
                raise ISAError(f"instruction {index} must be an object")
            mnemonic, encoding = raw.get("mnemonic"), raw.get("encoding")
            if not isinstance(mnemonic, str) or not _NAME_RE.fullmatch(mnemonic):
                raise ISAError(f"instruction {index} has invalid mnemonic: {mnemonic!r}")
            if not isinstance(encoding, str) or not encoding.strip():
                raise ISAError(f"{mnemonic}: encoding must be a non-empty string")
            raw_operands = raw.get("operands", [])
            if not isinstance(raw_operands, list):
                raise ISAError(f"{mnemonic}: operands must be an array")
            operands = []
            names = set()
            for operand_index, raw_operand in enumerate(raw_operands):
                if not isinstance(raw_operand, dict) or "name" not in raw_operand:
                    raise ISAError(f"{mnemonic}: operand {operand_index} must contain a name")
                operand_name = raw_operand["name"]
                operand_type = raw_operand.get("type", "immediate")
                values = raw_operand.get("values")
                if not isinstance(operand_name, str) or not _NAME_RE.fullmatch(operand_name) or operand_name in names:
                    raise ISAError(f"{mnemonic}: invalid or duplicate operand name: {operand_name!r}")
                if operand_type not in _OPERAND_TYPES:
                    raise ISAError(f"{mnemonic}: unsupported operand type: {operand_type!r}")
                signed = raw_operand.get("signed", False)
                if not isinstance(signed, bool):
                    raise ISAError(f"{mnemonic}.{operand_name}: signed must be boolean")
                size = raw_operand.get("size")
                if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size <= 0):
                    raise ISAError(f"{mnemonic}.{operand_name}: size must be a positive integer")
                if values is not None and not isinstance(values, dict):
                    raise ISAError(f"{mnemonic}.{operand_name}: values must be an object")
                operands.append(OperandDef(operand_name, operand_type, values, signed, size))
                names.add(operand_name)
            aliases = raw.get("aliases", [])
            if not isinstance(aliases, list):
                raise ISAError(f"{mnemonic}: aliases must be an array")
            for alias_index, alias in enumerate(aliases):
                if not isinstance(alias, dict):
                    raise ISAError(f"{mnemonic}: alias {alias_index} must be an object")
                alias_operands = alias.get("operands")
                alias_values = alias.get("values")
                if not isinstance(alias_operands, list) or not all(isinstance(value, str) for value in alias_operands):
                    raise ISAError(f"{mnemonic}: alias {alias_index} operands must be an array of strings")
                if not isinstance(alias_values, dict) or set(alias_values) != {operand.name for operand in operands}:
                    raise ISAError(f"{mnemonic}: alias {alias_index} values must map every operand")
            form = InstructionDef(mnemonic, operands, encoding, raw.get("meta", {}), aliases)
            signature = (mnemonic, encoding)
            if signature in seen:
                raise ISAError(f"duplicate instruction definition: {mnemonic} {encoding!r}")
            seen.add(signature)
            forms.setdefault(mnemonic.upper(), []).append(form)
        return cls(spec, forms, register_codes)

    @classmethod
    def from_json(cls, source) -> "ISA":
        if hasattr(source, "read"):
            return cls.from_dict(json.load(source))
        with open(source) as handle:
            return cls.from_dict(json.load(handle))

    def search_mnemonic(self, mnemonic: str) -> List[InstructionDef]:
        return list(self._forms.get(mnemonic.upper(), []))

    def find(self, mnemonic: str, operand_count: int) -> Optional[InstructionDef]:
        return next((form for form in self.search_mnemonic(mnemonic) if len(form.operands) == operand_count), None)

    def all_instructions(self) -> List[InstructionDef]:
        return [form for forms in self._forms.values() for form in forms]

    def build(self, instruction: InstructionDef) -> List[Tuple[Dict[str, int], bytes]]:
        """Build every concrete operand expansion of an instruction form.

        This is intentionally eager. Callers handling large ISAs should use
        ``ISAEncodingIndex`` or ``ISAProductionTree`` instead.
        """
        if not isinstance(instruction, InstructionDef):
            raise TypeError("instruction must be an InstructionDef")
        if instruction not in self.all_instructions():
            raise ISAError("instruction does not belong to this ISA")

        domains = []
        for operand in instruction.operands:
            if operand.values is not None:
                values = list(operand.values.values())
            elif operand.type == "register":
                values = list(self._register_codes.values())
            else:
                width = instruction.pattern.field_widths[operand.name]
                if operand.signed:
                    values = range(-(1 << (width - 1)), 1 << (width - 1))
                else:
                    values = range(1 << width)
            domains.append(values)

        expansions = []
        for combination in product(*domains) if domains else [()]:
            values = {
                operand.name: value
                for operand, value in zip(instruction.operands, combination)
            }
            encoded = instruction.encode(values, endianness=self.endianness)
            expansions.append((values, encoded))
        return expansions

    def resolve_register(self, operand: OperandDef, name: str) -> int:
        table = operand.values or self._register_codes
        if name not in table:
            raise ISAError(f"'{name}' is not a valid register for this operand")
        return table[name]

    def resolve_register_name(self, operand: OperandDef, code: int) -> str:
        table = operand.values or self._register_codes
        for name, value in table.items():
            if value == code:
                return name
        raise ISAError(f"code {code} is not a valid value for this operand")


@dataclass(frozen=True)
class EncodingEntry:
    instruction: InstructionDef
    mask: int
    value: int
    bit_width: int


class ISAEncodingIndex:
    def __init__(self, isa: ISA | dict | str):
        self.isa = ISA.from_json(isa) if isinstance(isa, str) else ISA.from_dict(isa) if isinstance(isa, dict) else isa
        self.entries = [EncodingEntry(form, *form.pattern.mask_and_value(), form.pattern.width_bits) for form in self.isa.all_instructions()]

    def search(self, code: int, *, bit_width: Optional[int] = None) -> List[Tuple[InstructionDef, Dict[str, int]]]:
        return [(entry.instruction, entry.instruction.pattern.decode_fields(code)) for entry in self.entries if (bit_width is None or entry.bit_width == bit_width) and entry.instruction.pattern.matches(code)]

    def search_bytes(self, raw: bytes) -> List[Tuple[InstructionDef, Dict[str, int]]]:
        return self.search(int.from_bytes(raw, self.isa.endianness), bit_width=len(raw) * 8)


class ISAProductionTree:
    """Compatibility facade using the lazy encoding index."""

    def __init__(self, isa: ISA | dict | str):
        self.isa = ISA.from_json(isa) if isinstance(isa, str) else ISA.from_dict(isa) if isinstance(isa, dict) else isa
        self._index = ISAEncodingIndex(self.isa)

    @classmethod
    def from_json(cls, source):
        return cls(ISA.from_json(source))

    @classmethod
    def from_dict(cls, spec: dict):
        return cls(ISA.from_dict(spec))

    def search_mnemonic(self, mnemonic: str) -> List[InstructionDef]:
        return self.isa.search_mnemonic(mnemonic)

    def reverse_search(self, code: int | str, *, bit_width: Optional[int] = None):
        if isinstance(code, str):
            code = int(code, 0)
        return self._index.search(code, bit_width=bit_width)

    search_code = reverse_search
