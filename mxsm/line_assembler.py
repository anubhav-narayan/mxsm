"""
A minimal line assembler: takes one line of assembly text and turns it
into machine code bytes, driven entirely by an ISA object
(mxsm.isa_schema.ISA) -- there is no hand-written per-mnemonic parsing
table here. Retargeting to a different ISA means pointing this at a
different JSON file, nothing in this module changes.

This is deliberately much simpler than mxsm's real multi-line
tokenizer/assembler (mxsm/tokenizer.py, mxsm/assembler.py): no labels,
no sections, no multi-line programs -- just "one line in, one
instruction's bytes out". It exists to drive the REPL in
scripts/mxsm_repl.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .bitfield import EncodingError
from .schema import ISA, InstructionDef


class LineAssemblyError(Exception):
    """Raised when a line of assembly can't be matched against the ISA."""


@dataclass
class AssembledLine:
    mnemonic: str
    ins_def: InstructionDef
    operand_tokens: List[str]
    encoded: bytes

    @property
    def hex(self) -> str:
        return self.encoded.hex()


def _split_operands(rest: str) -> List[str]:
    rest = rest.strip()
    if not rest:
        return []
    return [tok.strip() for tok in rest.split(",")]


def _parse_line(line: str) -> Tuple[str, List[str]]:
    line = line.split(";", 1)[0].strip()  # strip trailing comment
    if not line:
        raise LineAssemblyError("empty line")
    parts = line.split(None, 1)
    mnemonic = parts[0].upper()
    rest = parts[1] if len(parts) > 1 else ""
    return mnemonic, _split_operands(rest)


def _try_match(isa: ISA, ins_def: InstructionDef,
                operand_tokens: List[str]) -> Optional[Dict[str, int]]:
    """Return {field_name: value} if operand_tokens fit this
    InstructionDef, else None. Handles both field-based instructions and
    fully-literal ones (recognised via meta['dst']/['src'], e.g. MOV)."""
    dst = ins_def.meta.get("dst")
    src = ins_def.meta.get("src")

    if not ins_def.operands and dst is not None and src is not None:
        # fully-literal two-register instruction, e.g. "MOV D,A"
        if len(operand_tokens) != 2:
            return None
        if operand_tokens[0].upper() == dst and operand_tokens[1].upper() == src:
            return {}
        return None

    if not ins_def.operands:
        # plain zero-operand instruction: NOP, HALT, JNZ, JNC, ...
        return {} if not operand_tokens else None

    if len(operand_tokens) != len(ins_def.operands):
        return None

    values: Dict[str, int] = {}
    for op, token in zip(ins_def.operands, operand_tokens):
        if op.type == "register":
            table = op.values or isa.registers
            name = token.upper()
            if name not in table:
                return None
            values[op.name] = table[name]
        elif op.type == "immediate":
            try:
                values[op.name] = int(token, 0)
            except ValueError:
                return None
        else:
            return None  # "label" operands aren't supported by this minimal assembler
    return values


def describe_usage(isa: ISA, ins_def: InstructionDef) -> str:
    dst = ins_def.meta.get("dst")
    src = ins_def.meta.get("src")
    if not ins_def.operands and dst is not None and src is not None:
        return f"{ins_def.mnemonic} {dst},{src}"
    if not ins_def.operands:
        return ins_def.mnemonic
    parts = []
    for op in ins_def.operands:
        if op.type == "register":
            names = sorted((op.values or isa.registers).keys())
            parts.append("{" + "|".join(names) + "}")
        elif op.type == "immediate":
            parts.append("<n>")
        else:
            parts.append(f"<{op.name}>")
    return f"{ins_def.mnemonic} " + ", ".join(parts)


def assemble_line(isa: ISA, line: str) -> AssembledLine:
    """Assemble a single line of text against `isa`. Raises
    LineAssemblyError with a human-readable explanation on failure."""
    mnemonic, operand_tokens = _parse_line(line)

    candidates = isa.instructions.get(mnemonic)
    if not candidates:
        known = ", ".join(sorted(isa.mnemonics))
        raise LineAssemblyError(f"unknown mnemonic {mnemonic!r}. Known mnemonics: {known}")

    matches = []
    for ins_def in candidates:
        values = _try_match(isa, ins_def, operand_tokens)
        if values is not None:
            matches.append((ins_def, values))

    if not matches:
        usage = "; ".join(describe_usage(isa, c) for c in candidates)
        given = ", ".join(operand_tokens) if operand_tokens else "(no operands)"
        raise LineAssemblyError(
            f"'{mnemonic} {given}' doesn't match any known form of {mnemonic}. "
            f"Valid form(s): {usage}"
        )
    if len(matches) > 1:
        raise LineAssemblyError(
            f"'{line.strip()}' is ambiguous between {len(matches)} instruction "
            f"definitions -- this is an ISA definition bug, not a user error"
        )

    ins_def, values = matches[0]
    try:
        encoded = ins_def.encode(values, endianness=isa.endianness)
    except EncodingError as e:
        raise LineAssemblyError(str(e)) from e

    return AssembledLine(mnemonic, ins_def, operand_tokens, encoded)