"""
Data-driven, multi-ISA instruction set description.

Replaces mxsm's old fixed-byte, fixed-width `prod.tab.json` opcode table
with a bitfield-pattern based schema (see bitfield.py). An ISA is loaded
from a JSON file (or dict) shaped like::

    {
      "isa": "MX11SU",
      "word_size": 8,
      "endianness": "big",
      "registers": {"A": 0, "X": 1, "Y": 2, "D": 3, ...},
      "instructions": [
        {"mnemonic": "NOP", "operands": [], "encoding": "00000000"},
        {
          "mnemonic": "MOV",
          "operands": [
            {"name": "dst", "type": "register", "values": {"X": 1, "Y": 2, "D": 3}}
          ],
          "encoding": "{dst:4} 0000"
        }
      ]
    }

This is deliberately ISA-agnostic: instruction width, operand count, and
field layout are all data, not code, so a single assembler core can be
retargeted to any ISA by swapping this file in.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .bitfield import BitPattern, EncodingError
from .tokenizer import Token, TokenType


class ISAError(Exception):
    """Raised for malformed or inconsistent ISA definitions."""


@dataclass
class OperandDef:
    name: str
    type: str = "immediate"          # "register" | "immediate" | "label"
    values: Optional[Dict[str, int]] = None  # per-operand register override
    signed: bool = False


@dataclass
class InstructionDef:
    mnemonic: str
    operands: List[OperandDef]
    encoding: str
    meta: Dict = field(default_factory=dict)  # opaque passthrough for consumers
                                               # (e.g. a simulator's semantics
                                               # hints); isa_schema itself
                                               # never reads this.
    pattern: BitPattern = field(init=False, repr=False)

    def __post_init__(self):
        try:
            self.pattern = BitPattern(self.encoding)
        except EncodingError as e:
            raise ISAError(f"{self.mnemonic}: {e}") from e

        declared = {op.name for op in self.operands}
        used = self.pattern.field_names
        unknown = used - declared
        if unknown:
            raise ISAError(
                f"{self.mnemonic}: encoding references undeclared operand(s) "
                f"{sorted(unknown)}"
            )
        unused = declared - used
        if unused:
            raise ISAError(
                f"{self.mnemonic}: operand(s) {sorted(unused)} declared but "
                f"never referenced in encoding"
            )

    @property
    def size_bytes(self) -> int:
        return self.pattern.width_bytes

    def encode(self, operand_values: Dict[str, int], *, endianness: str = "big") -> bytes:
        try:
            return self.pattern.encode(operand_values, endianness=endianness)
        except EncodingError as e:
            raise EncodingError(f"{self.mnemonic}: {e}") from e


@dataclass
class ISA:
    name: str
    word_size: int
    endianness: str
    registers: Dict[str, int]
    instructions: Dict[str, List[InstructionDef]]  # mnemonic -> operand-count overloads

    @classmethod
    def from_dict(cls, spec: dict) -> "ISA":
        try:
            name = spec["isa"]
            raw_instructions = spec["instructions"]
        except KeyError as e:
            raise ISAError(f"ISA definition missing required key: {e}") from e

        word_size = spec.get("word_size", 8)
        endianness = spec.get("endianness", "big")
        registers = spec.get("registers", {})

        if endianness not in ("big", "little"):
            raise ISAError(f"endianness must be 'big' or 'little', got {endianness!r}")

        instructions: Dict[str, List[InstructionDef]] = {}
        seen_signatures = set()
        for entry in raw_instructions:
            try:
                mnemonic = entry["mnemonic"]
                encoding = entry["encoding"]
            except KeyError as e:
                raise ISAError(f"instruction entry missing required key: {e}") from e

            operands = [
                OperandDef(
                    name=o["name"],
                    type=o.get("type", "immediate"),
                    values=o.get("values"),
                    signed=o.get("signed", False),
                )
                for o in entry.get("operands", [])
            ]
            ins_def = InstructionDef(mnemonic, operands, encoding, entry.get("meta", {}))
            sig = (mnemonic, encoding)
            if sig in seen_signatures:
                raise ISAError(
                    f"duplicate instruction definition: {mnemonic} {encoding!r}"
                )
            seen_signatures.add(sig)
            instructions.setdefault(mnemonic, []).append(ins_def)

        return cls(name, word_size, endianness, registers, instructions)

    @classmethod
    def from_json(cls, path_or_fh) -> "ISA":
        if hasattr(path_or_fh, "read"):
            spec = json.load(path_or_fh)
        else:
            with open(path_or_fh) as fh:
                spec = json.load(fh)
        return cls.from_dict(spec)

    def resolve_register(self, operand: OperandDef, name: str) -> int:
        table = operand.values or self.registers
        if name not in table:
            raise ISAError(f"'{name}' is not a valid register for this operand")
        return table[name]

    def resolve_register_name(self, operand: OperandDef, code: int) -> str:
        """Reverse of resolve_register: decoded field value -> register name.
        Used by a disassembler/interpreter to turn bits back into a name."""
        table = operand.values or self.registers
        for name, value in table.items():
            if value == code:
                return name
        raise ISAError(f"code {code} is not a valid value for this operand")

    def find(self, mnemonic: str, arg_count: int) -> Optional[InstructionDef]:
        for candidate in self.instructions.get(mnemonic, []):
            if len(candidate.operands) == arg_count:
                return candidate
        return None

    def all_instructions(self) -> List[InstructionDef]:
        """Every InstructionDef across every mnemonic, flattened -- what a
        decoder needs to scan when going from raw bytes to (mnemonic, fields)
        rather than from a parsed mnemonic to bytes."""
        return [ins for group in self.instructions.values() for ins in group]

    @property
    def mnemonics(self):
        return set(self.instructions.keys())


class ProductionNode:
    """Node in a trie that stores one instruction production path."""

    __slots__ = (
        "name",
        "children",
        "mnemonic",
        "instruction",
        "operand_values",
        "code",
        "bit_width",
    )

    def __init__(self, name: str):
        self.name = name
        self.children: Dict[str, "ProductionNode"] = {}
        self.mnemonic: Optional[str] = None
        self.instruction: Optional[InstructionDef] = None
        self.operand_values: Optional[Dict[str, int]] = None
        self.code: Optional[int] = None
        self.bit_width: Optional[int] = None

    @property
    def is_terminal(self) -> bool:
        return self.instruction is not None and self.mnemonic is not None

    def __repr__(self) -> str:
        suffix = f" -> {self.mnemonic}" if self.is_terminal else ""
        return f"ProductionNode(name={self.name!r}{suffix})"


class ISAProductionTree:
    """Bit-path tree built from an ISA schema.

    Each instruction production becomes a path of bits, with reverse lookup by
    machine code and lookup by mnemonic across all matching productions.
    """

    def __init__(self, isa: ISA | dict | str):
        if isinstance(isa, str):
            self.isa = ISA.from_json(isa)
        elif isinstance(isa, dict):
            self.isa = ISA.from_dict(isa)
        elif isinstance(isa, ISA):
            self.isa = isa
        else:
            raise TypeError("isa must be an ISA instance, a dict, or a JSON path")

        self.root = ProductionNode("ISA")
        self._by_mnemonic: Dict[str, List[ProductionNode]] = {}
        self._width_roots: Dict[int, ProductionNode] = {}
        self._build()

        for width, node in sorted(self._width_roots.items()):
            self.root.children.setdefault(f"{width}b", node)

    @classmethod
    def from_json(cls, path_or_fh):
        return cls(ISA.from_json(path_or_fh))

    @classmethod
    def from_dict(cls, spec: dict):
        return cls(ISA.from_dict(spec))

    def _operand_values(self, operand: OperandDef, width: int) -> List[int]:
        if operand.values:
            return sorted({int(v) for v in operand.values.values()})
        if operand.type == "register":
            return sorted({int(v) for v in self.isa.registers.values()})
        if width <= 0:
            return [0]
        return list(range(1 << width))

    def _production_values(self, ins: InstructionDef):
        widths = {
            match.group(1): int(match.group(2))
            for match in re.finditer(r"\{([A-Za-z_][A-Za-z0-9_]*)\:(\d+)\}", ins.encoding)
        }
        if not ins.operands:
            yield {}
            return

        choices = [self._operand_values(op, widths.get(op.name, 0)) for op in ins.operands]
        from itertools import product
        for combo in product(*choices):
            yield {op.name: value for op, value in zip(ins.operands, combo)}

    def _build(self):
        for mnemonic, group in self.isa.instructions.items():
            for ins in group:
                for operand_values in self._production_values(ins):
                    try:
                        encoded = ins.encode(operand_values, endianness=self.isa.endianness)
                    except Exception:
                        continue
                    code = int.from_bytes(encoded, byteorder=self.isa.endianness, signed=False)
                    bit_width = len(encoded) * 8
                    width_root = self._width_roots.setdefault(bit_width, ProductionNode(f"{bit_width}b"))
                    node = width_root
                    bits = format(code, f"0{bit_width}b")
                    for bit in bits:
                        node = node.children.setdefault(bit, ProductionNode(f"{node.name}.{bit}"))
                    node.mnemonic = mnemonic
                    node.instruction = ins
                    node.operand_values = dict(operand_values)
                    node.code = code
                    node.bit_width = bit_width
                    self._by_mnemonic.setdefault(mnemonic, []).append(node)

    def search_mnemonic(self, mnemonic: str) -> List[ProductionNode]:
        return list(self._by_mnemonic.get(mnemonic, []))

    def reverse_search(self, code: int | str, *, bit_width: Optional[int] = None) -> List[ProductionNode]:
        if isinstance(code, str):
            value = code.strip()
            if value.lower().startswith("0x"):
                code = int(value, 16)
            elif value.lower().startswith("0b"):
                code = int(value, 2)
            elif value.lower().startswith("0o"):
                code = int(value, 8)
            else:
                code = int(value, 10)

        widths = [bit_width] if bit_width is not None else sorted(self._width_roots)
        matches: List[ProductionNode] = []
        for width in widths:
            root = self._width_roots.get(width)
            if root is None:
                continue
            node = root
            bits = format(int(code), f"0{width}b")
            for bit in bits:
                node = node.children.get(bit)
                if node is None:
                    break
            else:
                if node is not None and node.is_terminal:
                    matches.append(node)
        return matches

    def search_code(self, code: int | str, *, bit_width: Optional[int] = None) -> List[ProductionNode]:
        return self.reverse_search(code, bit_width=bit_width)

    def from_tokens(self, tokens: Iterable[Token]) -> List[ProductionNode]:
        """Resolve a tokenized instruction line to the matching machine-code nodes."""
        token_list = list(tokens)
        mnemonic_token = next((tok for tok in token_list if tok.type == TokenType.INSTRUCTION), None)
        if mnemonic_token is None:
            raise ISAError("token stream does not contain an instruction mnemonic")

        mnemonic = mnemonic_token.value
        operand_tokens = [
            tok for tok in token_list
            if tok.type in {TokenType.REGISTER, TokenType.NUMBER, TokenType.LABEL, TokenType.ADDRESS_NUMBER, TokenType.ADDRESS_LABEL}
        ]

        ins = self.isa.find(mnemonic, len(operand_tokens))
        if ins is None:
            raise ISAError(f"no ISA definition for {mnemonic!r} with {len(operand_tokens)} operands")

        operand_values: Dict[str, int] = {}
        for operand_def, token in zip(ins.operands, operand_tokens):
            if operand_def.type == "register":
                if token.type is not TokenType.REGISTER:
                    raise ISAError(f"operand {operand_def.name} for {mnemonic} must be a register token")
                operand_values[operand_def.name] = self.isa.resolve_register(operand_def, token.value)
                continue

            raw = token.value
            if raw.startswith("&"):
                raw = raw[1:]
            if raw.lower().startswith("0x"):
                operand_values[operand_def.name] = int(raw, 16)
            elif raw.lower().startswith("0b"):
                operand_values[operand_def.name] = int(raw, 2)
            elif raw.lower().startswith("0o"):
                operand_values[operand_def.name] = int(raw, 8)
            else:
                operand_values[operand_def.name] = int(raw, 10)

        encoded = ins.encode(operand_values, endianness=self.isa.endianness)
        code = int.from_bytes(encoded, byteorder=self.isa.endianness, signed=False)
        return self.reverse_search(code, bit_width=len(encoded) * 8)

    def __iter__(self):
        for productions in self._by_mnemonic.values():
            yield from productions

    def __repr__(self) -> str:
        total = sum(len(group) for group in self._by_mnemonic.values())
        return f"ISAProductionTree(isa={self.isa.name}, productions={total})"