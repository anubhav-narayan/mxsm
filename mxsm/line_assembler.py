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
from .tokenizer import Token, TokenType, Tokenizer


class LineAssemblyError(Exception):
    """Raised when a line of assembly can't be matched against the ISA."""


@dataclass
class AssembledLine:
    mnemonic: str
    ins_def: InstructionDef
    operand_tokens: List[Token]
    encoded: bytes

    @property
    def hex(self) -> str:
        return self.encoded.hex()


def _split_operands(rest: str) -> List[str]:
    rest = rest.strip()
    if not rest:
        return []
    return [tok.strip() for tok in rest.split(",")]


def _parse_line(isa: ISA, line: str) -> Tuple[str, List[Token]]:
    tokenizer = Tokenizer(isa.instructions, isa.registers)
    tokens = tokenizer.tokenize_line(line, 0)
    if not tokens:
        raise LineAssemblyError("empty line")
    if tokens[0].type is not TokenType.INSTRUCTION:
        raise LineAssemblyError(f"expected instruction mnemonic, got {tokens[0].value!r}")
    return tokens[0].value.upper(), tokens[1:]


def _try_match(isa: ISA, ins_def: InstructionDef,
                operand_tokens: List[Token]) -> Optional[Dict[str, int]]:
    """Return {field_name: value} if operand_tokens fit this
    InstructionDef, else None. Handles both field-based instructions and
    fully-literal ones (recognised via meta['dst']/['src'], e.g. MOV)."""
    dst = ins_def.meta.get("dst")
    src = ins_def.meta.get("src")

    if not ins_def.operands and dst is not None and src is not None:
        # fully-literal two-register instruction, e.g. "MOV D,A"
        if len(operand_tokens) != 2:
            return None
        if operand_tokens[0].value.upper() == dst and operand_tokens[1].value.upper() == src:
            return {}
        return None

    if not ins_def.operands:
        # plain zero-operand instruction: NOP, HALT, JNZ, JNC, ...
        return {} if not operand_tokens else None

    values: Dict[str, int] = {}
    token_index = 0
    for operand_index, op in enumerate(ins_def.operands):
        tokens_needed_after = len(ins_def.operands) - operand_index - 1
        if op.type == "selector" and len(operand_tokens) - token_index == tokens_needed_after:
            table = op.values or {"": 0}
            if "" in table:
                values[op.name] = table[""]
                continue
        if token_index >= len(operand_tokens):
            return None
        token = operand_tokens[token_index]
        token_value = token.value
        token_index += 1
        if op.type == "register":
            table = op.values or isa._register_codes
            name = token_value.upper()
            if name not in table:
                return None
            values[op.name] = table[name]
        elif op.type == "selector":
            table = op.values or {"": 0, token: 1}
            name = token_value.upper()
            if name not in table:
                return None
            values[op.name] = table[name]
        elif op.type == "immediate":
            try:
                values[op.name] = int(token_value, 0)
            except ValueError:
                return None
        else:
            return None  # "label" operands aren't supported by this minimal assembler
    return values if token_index == len(operand_tokens) else None


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
            names = sorted((op.values or isa._register_codes).keys())
            parts.append("{" + "|".join(names) + "}")
        elif op.type == "selector":
            names = sorted(name for name in (op.values or {}) if name)
            parts.append("[" + "|".join(names) + "]")
        elif op.type == "immediate":
            parts.append("<n>")
        else:
            parts.append(f"<{op.name}>")
    return f"{ins_def.mnemonic} " + ", ".join(parts)


def assemble_line(isa: ISA, line: str) -> AssembledLine:
    """Assemble a single line of text against `isa`. Raises
    LineAssemblyError with a human-readable explanation on failure."""
    mnemonic, operand_tokens = _parse_line(isa, line)

    candidates = isa.search_mnemonic(mnemonic)
    if not candidates:
        known = ", ".join(sorted(isa.mnemonics))
        raise LineAssemblyError(f"unknown mnemonic {mnemonic!r}. Known mnemonics: {known}")

    matches = []
    for ins_def in candidates:
        alias_values = _try_alias(isa, ins_def, operand_tokens)
        if alias_values is not None:
            matches.append((ins_def, alias_values))
            continue
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


def _try_alias(isa: ISA, ins_def: InstructionDef,
               operand_tokens: List[Token]) -> Optional[Dict[str, int]]:
    for alias in ins_def.aliases:
        spellings = alias["operands"]
        if len(spellings) != len(operand_tokens):
            continue
        if any(expected.upper() != actual.value.upper() for expected, actual in zip(spellings, operand_tokens)):
            continue
        values = {}
        for operand in ins_def.operands:
            value = alias["values"][operand.name]
            if isinstance(value, str) and operand.type in {"register", "selector"}:
                table = operand.values or isa._register_codes
                if value.upper() in table:
                    value = table[value.upper()]
                elif value in table:
                    value = table[value]
                else:
                    return None
            elif isinstance(value, str):
                try:
                    value = int(value, 0)
                except ValueError:
                    return None
            if not isinstance(value, int) or isinstance(value, bool):
                return None
            values[operand.name] = value
        return values
    return None