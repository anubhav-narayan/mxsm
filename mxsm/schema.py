"""Validated, architecture-neutral ISA specification model."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
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
    description: Optional[str] = None
    operation: Optional[str] = None
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


def _load_spec(source, stack: Tuple[Path, ...] = ()) -> dict:
    path = None
    if isinstance(source, dict):
        spec = source
    elif hasattr(source, "read"):
        spec = json.load(source)
        source_name = getattr(source, "name", None)
        if source_name:
            path = Path(source_name).resolve()
    elif isinstance(source, Path):
        path = source.resolve()
        spec = json.loads(path.read_text())
    elif isinstance(source, str):
        if source.lstrip().startswith("{"):
            spec = json.loads(source)
        else:
            path = Path(source).resolve()
            spec = json.loads(path.read_text())
    else:
        raise TypeError("ISA definition must be a mapping, JSON string, path, or readable file")

    if path is not None:
        if path in stack:
            cycle = " -> ".join(str(item) for item in (*stack, path))
            raise ISAError(f"circular ISA base reference: {cycle}")
        stack = (*stack, path)
    return _resolve_spec(spec, path, stack)


def _resolve_spec(spec: dict, path: Optional[Path] = None, stack: Tuple[Path, ...] = ()) -> dict:
    if not isinstance(spec, dict):
        raise ISAError(f"ISA definition must be an object, got {type(spec).__name__}")
    if "base" not in spec:
        return spec
    base_reference = spec["base"]
    if not isinstance(base_reference, str) or not base_reference.strip():
        raise ISAError("base must be a non-empty relative path")
    if path is None:
        raise ISAError("base references require loading the ISA spec from a file")
    base_path = Path(base_reference)
    if base_path.is_absolute():
        raise ISAError("base must be a relative path")
    base = _load_spec(path.parent / base_path, stack)

    base_registers = base.get("registers", {})
    extension_registers = spec.get("registers", {})
    base_instructions = base.get("instructions", [])
    extension_instructions = spec.get("instructions", [])
    if not isinstance(base_registers, dict) or not isinstance(extension_registers, dict):
        raise ISAError("registers must be an object mapping names to integer codes")
    if not isinstance(base_instructions, list) or not isinstance(extension_instructions, list):
        raise ISAError("instructions must be an array")

    registers = dict(base_registers)
    for name, code in extension_registers.items():
        if name in registers and registers[name] != code:
            raise ISAError(f"register {name!r} conflicts with the base ISA definition")
        registers[name] = code

    merged = dict(base)
    merged.update({key: value for key, value in spec.items() if key not in ("base", "registers", "instructions")})
    merged["registers"] = registers
    merged["instructions"] = base_instructions + extension_instructions
    return merged


class ISA:
    """An ISA spec with list-based public names and form lookup methods."""

    def __init__(
        self,
        spec: dict,
        forms: Dict[str, List[InstructionDef]],
        register_codes: Dict[str, int],
        control_instructions: Optional[List[InstructionDef]] = None,
        domain_instructions: Optional[Dict[int, List[InstructionDef]]] = None,
        domain_names: Optional[Dict[int, str]] = None,
        control_set_name: Optional[str] = None,
    ):
        self.spec = spec
        self.name = spec["isa"]
        self.schema_version = spec.get("schema_version", 1)
        self.word_size = spec.get("word_size", 8)
        self.address_width = spec.get("address_width", self.word_size)
        self.data_width = spec.get("data_width", self.word_size)
        self.endianness = spec.get("endianness", "big")
        self._forms = forms
        self._register_codes = register_codes
        self.control_instructions = control_instructions or []
        self.domain_instructions = domain_instructions or {}
        self.domain_names = domain_names or {}
        self.control_set_name = control_set_name

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
        spec = _resolve_spec(spec)
        if not isinstance(spec, dict):
            raise ISAError(f"ISA definition must be an object, got {type(spec).__name__}")
        try:
            name = spec["isa"]
        except KeyError as error:
            raise ISAError(f"ISA definition missing required key: {error}") from error
        has_structured_instructions = "control_set" in spec or "domains" in spec
        raw_instructions = spec.get("instructions", [])
        if not isinstance(raw_instructions, list):
            raise ISAError("instructions must be an array")
        if not has_structured_instructions and "instructions" not in spec:
            raise ISAError("ISA definition missing required key: 'instructions'")
        if has_structured_instructions and raw_instructions:
            raise ISAError("instructions cannot be combined with control_set or domains")

        instruction_groups = []
        control_name = None
        if has_structured_instructions:
            control_set = spec.get("control_set", {"name": "Control/System", "instructions": []})
            if not isinstance(control_set, dict):
                raise ISAError("control_set must be an object")
            control_name = control_set.get("name")
            if not isinstance(control_name, str) or not control_name.strip():
                raise ISAError("control_set.name must be a non-empty string")
            control_raw = control_set.get("instructions", [])
            if not isinstance(control_raw, list):
                raise ISAError("control_set.instructions must be an array")
            instruction_groups.append(("control", None, control_raw))

            raw_domains = spec.get("domains", [])
            if not isinstance(raw_domains, list):
                raise ISAError("domains must be an array")
            seen_dar_values = set()
            for domain_index, domain in enumerate(raw_domains):
                if not isinstance(domain, dict):
                    raise ISAError(f"domain {domain_index} must be an object")
                dar_value = domain.get("dar")
                domain_name = domain.get("name")
                domain_raw = domain.get("instructions", [])
                if not isinstance(dar_value, int) or isinstance(dar_value, bool) or dar_value < 0:
                    raise ISAError(f"domain {domain_index}.dar must be a non-negative integer")
                if dar_value in seen_dar_values:
                    raise ISAError(f"duplicate DAR domain value: {dar_value}")
                if not isinstance(domain_name, str) or not domain_name.strip():
                    raise ISAError(f"domain {domain_index}.name must be a non-empty string")
                if not isinstance(domain_raw, list):
                    raise ISAError(f"domain {domain_index}.instructions must be an array")
                seen_dar_values.add(dar_value)
                instruction_groups.append(("domain", dar_value, domain_raw))
        else:
            instruction_groups.append(("legacy", None, raw_instructions))

        scoped_instructions = [
            (raw, scope, dar_value)
            for scope, dar_value, group in instruction_groups
            for raw in group
        ]
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
        control_instructions: List[InstructionDef] = []
        domain_instructions: Dict[int, List[InstructionDef]] = {
            dar_value: []
            for scope, dar_value, _ in instruction_groups
            if scope == "domain"
        }
        domain_names = {
            domain["dar"]: domain["name"]
            for domain in spec.get("domains", [])
        } if has_structured_instructions else {}
        seen = set()
        for index, (raw, scope, dar_value) in enumerate(scoped_instructions):
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
            description = raw.get("description")
            operation = raw.get("operation")
            if description is not None and not isinstance(description, str):
                raise ISAError(f"{mnemonic}: description must be a string")
            if operation is not None and not isinstance(operation, str):
                raise ISAError(f"{mnemonic}: operation must be a string")
            form = InstructionDef(
                mnemonic, operands, encoding, raw.get("meta", {}), aliases,
                description, operation,
            )
            signature = (scope, dar_value, mnemonic, encoding)
            if signature in seen:
                raise ISAError(f"duplicate instruction definition: {mnemonic} {encoding!r}")
            seen.add(signature)
            forms.setdefault(mnemonic.upper(), []).append(form)
            if scope == "control":
                control_instructions.append(form)
            elif scope == "domain":
                domain_instructions[dar_value].append(form)

        for control_instruction in control_instructions:
            control_mask, control_value = control_instruction.pattern.mask_and_value()
            for dar_value, domain_forms in domain_instructions.items():
                for domain_instruction in domain_forms:
                    if control_instruction.pattern.width_bits != domain_instruction.pattern.width_bits:
                        continue
                    domain_mask, domain_value = domain_instruction.pattern.mask_and_value()
                    if not ((control_value ^ domain_value) & control_mask & domain_mask):
                        raise ISAError(
                            f"domain DAR {dar_value} instruction {domain_instruction.mnemonic} "
                            f"overlaps Control/System instruction {control_instruction.mnemonic}"
                        )

        return cls(
            spec,
            forms,
            register_codes,
            control_instructions,
            domain_instructions,
            domain_names,
            control_name,
        )

    @classmethod
    def from_json(cls, source) -> "ISA":
        return cls.from_dict(_load_spec(source))

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
