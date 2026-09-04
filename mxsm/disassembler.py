from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

from .schema import ISA, ISAEncodingIndex, InstructionDef, OperandDef

class Disassembler:
    """
    Disassembler Class

    This class is responsible for the disassembly translation

    The disassembler consumes an ISA definition and uses its encoding index to
    find and decode instruction forms. `isa_source` accepts the same source
    types as :class:`Assembler`.
    """
    def __init__(self, isa_source):
        definition = self._load_definition(isa_source)
        self.isa = ISA.from_dict(definition)
        self.index = ISAEncodingIndex(self.isa)
        self.ins_len = max(
            (instruction.size_bytes for instruction in self.isa.all_instructions()),
            default=(self.isa.word_size + 7) // 8,
        )
        self.data_len = (self.isa.data_width + 7) // 8
        self.address_len = (self.isa.address_width + 7) // 8
        self.dec = ''
        self.sdec = []

    @staticmethod
    def _load_definition(source) -> dict:
        if isinstance(source, dict):
            return source
        if hasattr(source, 'read'):
            return json.load(source)
        if isinstance(source, Path):
            with source.open() as handle:
                return json.load(handle)
        if isinstance(source, str):
            if source.lstrip().startswith('{'):
                return json.loads(source)
            with open(source) as handle:
                return json.load(handle)
        raise TypeError('ISA definition must be a mapping, JSON string, path, or readable file')

    def _format_operand(self, operand: OperandDef, value: int, instruction: InstructionDef) -> str:
        values = operand.values
        if values is not None:
            for name, code in values.items():
                if code == value:
                    return name
        if operand.type == 'register':
            try:
                return self.isa.resolve_register_name(operand, value)
            except Exception:
                pass
        if operand.signed:
            width = instruction.pattern.field_widths[operand.name]
            if value >= 1 << (width - 1):
                value -= 1 << width
        return str(value)

    def _format_instruction(self, instruction: InstructionDef, fields: Dict[str, int]) -> str:
        operands = []
        for operand in instruction.operands:
            rendered = self._format_operand(operand, fields[operand.name], instruction)
            if rendered:
                operands.append(rendered)
        return instruction.mnemonic + (f" {', '.join(operands)}" if operands else '')

    def _search(self, code: int, bit_width: int | None = None) -> Tuple[InstructionDef, Dict[str, int]] | None:
        matches = self.index.search(code, bit_width=bit_width)
        return matches[0] if matches else None

    def search_code(self, code: int) -> str:
        match = self._search(code)
        if match is None:
            return f"0x{code:0{self.ins_len * 2}X}\t; Not Found"
        instruction, fields = match
        decoded = self._format_instruction(instruction, fields)
        self.sdec.append(decoded)
        return f"0x{code:0{instruction.size_bytes * 2}X}\t; {decoded}"

    def _decode_at(self, code: bytes, offset: int):
        sizes = sorted({instruction.size_bytes for instruction in self.isa.all_instructions()}, reverse=True)
        for size in sizes:
            raw = code[offset:offset + size]
            if len(raw) != size:
                continue
            match = self._search(int.from_bytes(raw, self.isa.endianness), size * 8)
            if match is not None:
                return size, match
        return None


    def disassemble(self, code: bytes) -> str:
        disasm = []
        self.sdec = []
        offset = 0
        while offset < len(code):
            decoded = self._decode_at(code, offset)
            if decoded is None:
                raw = code[offset:offset + self.ins_len]
                ins_code = int.from_bytes(raw, self.isa.endianness)
                disasm.append(f"0x{offset:0{self.address_len * 2}X}:\t{self.search_code(ins_code)}")
                offset += max(len(raw), 1)
                continue
            size, (instruction, fields) = decoded
            ins_code = int.from_bytes(code[offset:offset + size], self.isa.endianness)
            rendered = self._format_instruction(instruction, fields)
            self.sdec.append(rendered)
            disasm.append(
                f"0x{offset:0{self.address_len * 2}X}:\t"
                f"0x{ins_code:0{size * 2}X}\t; {rendered}"
            )
            offset += size
        self.dec = '\n'.join(disasm)
        return self.dec

    @property
    def string_decoding(self):
        return '\n'.join(self.sdec) 