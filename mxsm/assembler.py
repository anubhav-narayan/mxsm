"""Two-pass assembler driven by the validated ISA schema."""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .bitfield import EncodingError
from .line_assembler import _try_alias
from .preprocessor import ExpandedLine, MacroProcessor
from .schema import ISA, InstructionDef, OperandDef
from .tokenizer import Token, TokenType, Tokenizer


class AssemblyError(SyntaxError):
    """Raised when source cannot be parsed, resolved, or encoded."""


@dataclass
class _InstructionItem:
    address: int
    definition: InstructionDef
    values: Dict[str, int | str]
    token: Token


@dataclass
class _DataItem:
    address: int
    value: int | str
    token: Token


class Assembler:
    """Assemble a complete source file using an ISA JSON definition.

    The assembler performs a real pass 1 (section sizing and symbol collection)
    followed by pass 2 (symbol resolution and encoding). ``ins`` remains a
    dense instruction-memory image and ``data`` remains a contiguous data image.
    """

    def __init__(self, isa_source):
        definition = self._load_definition(isa_source)
        self.isa = ISA.from_dict(definition)
        self.tokenizer = Tokenizer(self.isa.instructions, self.isa.registers)
        self.nmi_addr = definition.get("nmi_vector", 0)
        self.irq_addr = definition.get("irq_vector", 0)
        self.ins_len = max(
            (instruction.size_bytes for instruction in self.isa.all_instructions()),
            default=(self.isa.word_size + 7) // 8,
        )
        self.data_len = (self.isa.data_width + 7) // 8
        self.section_regions = [
            ("data", 0),
            ("ins", 0),
            ("nmi", self.nmi_addr),
            ("irq", self.irq_addr),
        ]
        self.section_labels = [name for name, _ in self.section_regions]
        self.code = ""
        self.tokens: Dict[int, List[Token]] = {}
        self.sections: Dict[str, Dict[int, List[Token]]] = {
            name: {} for name in self.section_labels
        }
        self.symbol_table: Dict[str, int] = {}
        self.ins_dict: Dict[int, _InstructionItem] = {}
        self.mem_dict: Dict[int, _DataItem] = {}
        self.ins = b""
        self.data = b""
        self._expanded_lines: List[ExpandedLine] = []

    @staticmethod
    def _load_definition(source) -> dict:
        if isinstance(source, dict):
            return source
        if hasattr(source, "read"):
            return json.load(source)
        if isinstance(source, Path):
            with source.open() as handle:
                return json.load(handle)
        if isinstance(source, str):
            if source.lstrip().startswith("{"):
                return json.loads(source)
            with open(source) as handle:
                return json.load(handle)
        raise TypeError(
            "ISA definition must be a mapping, JSON string, path, or readable file"
        )

    def preprocess(self, code: str) -> str:
        """Expand macros and retain the expanded source for diagnostics."""
        self._expanded_lines = MacroProcessor().process(code)
        return "\n".join(line.text for line in self._expanded_lines)

    def tokenize(self, code: str) -> dict:
        self.code = code
        self.tokens = self.tokenizer.tokenize(code)
        return self.tokens

    def split_sections(self) -> dict:
        self.sections = {name: {} for name in self.section_labels}
        current = "ins"
        for line_number in sorted(self.tokens):
            tokens = self.tokens[line_number]
            if not tokens:
                continue
            directive = next(
                (token for token in tokens if token.type is TokenType.DIRECTIVE),
                None,
            )
            if directive and directive.value[1:].lower() in self.section_labels:
                current = directive.value[1:].lower()
                continue
            self.sections[current][line_number] = tokens
        return self.sections

    def _error(self, token: Token, message: str) -> AssemblyError:
        source_line = self.code.splitlines()[token.line] if self.code else ""
        return AssemblyError(f"{token.line + 1}:{token.column}: {message}\n{source_line}")

    @staticmethod
    def _number(token: Token) -> Optional[int]:
        if token.type in {TokenType.NUMBER, TokenType.ADDRESS_NUMBER}:
            return int(token.value.lstrip("&"), 0)
        return None

    def _resolve_operand(
        self, operand: OperandDef, token: Token
    ) -> int | str | None:
        if operand.type in {"label", "memory"} and token.type in {
            TokenType.SYMBOL,
            TokenType.ADDRESS_LABEL,
        }:
            return token.value.lstrip("&")
        number = self._number(token)
        if number is not None and operand.type in {"immediate", "label", "memory"}:
            return number
        if operand.type == "register":
            table = operand.values or self.isa._register_codes
            return table.get(token.value.upper())
        if operand.type == "selector":
            table = operand.values or {"": 0}
            return table.get(token.value.upper())
        return None

    def _match_instruction(
        self, mnemonic: str, operands: List[Token], source_token: Token
    ) -> tuple[InstructionDef, Dict[str, int | str]]:
        candidates = self.isa.search_mnemonic(mnemonic)
        if not candidates:
            raise self._error(source_token, f"unknown mnemonic {mnemonic!r}")

        matches: list[tuple[InstructionDef, Dict[str, int | str]]] = []
        for definition in candidates:
            alias_values = _try_alias(self.isa, definition, operands)
            if alias_values is not None:
                matches.append((definition, alias_values))
                continue
            values: Dict[str, int | str] = {}
            index = 0
            matched = True
            for operand_index, operand in enumerate(definition.operands):
                remaining = len(definition.operands) - operand_index - 1
                if (
                    operand.type == "selector"
                    and len(operands) - index == remaining
                    and operand.values
                    and "" in operand.values
                ):
                    values[operand.name] = operand.values[""]
                    continue
                if index >= len(operands):
                    matched = False
                    break
                value = self._resolve_operand(operand, operands[index])
                if value is None:
                    matched = False
                    break
                values[operand.name] = value
                index += 1
            if matched and index == len(operands):
                matches.append((definition, values))

        if len(matches) != 1:
            if not matches:
                raise self._error(
                    source_token,
                    f"operands do not match any form of {mnemonic}",
                )
            raise self._error(source_token, f"ambiguous instruction form {mnemonic}")
        return matches[0]

    def _define_label(self, token: Token, address: int) -> None:
        if token.value in self.symbol_table:
            raise self._error(token, f"duplicate label {token.value!r}")
        self.symbol_table[token.value] = address

    def _pass1_data(self, tokens: List[Token], address: int) -> int:
        directive = tokens[0].value.lower()
        if directive == ".byte":
            if len(tokens) == 1:
                raise self._error(tokens[0], ".byte requires at least one value")
            for token in tokens[1:]:
                if token.type is TokenType.STRING:
                    try:
                        value = ast.literal_eval(token.value)
                    except (SyntaxError, ValueError) as error:
                        raise self._error(token, "invalid string literal") from error
                    for character in value:
                        self.mem_dict[address] = _DataItem(address, ord(character), token)
                        address += 1
                elif token.type in {
                    TokenType.NUMBER,
                    TokenType.ADDRESS_NUMBER,
                    TokenType.ADDRESS_LABEL,
                }:
                    value = (
                        token.value.lstrip("&")
                        if token.type is TokenType.ADDRESS_LABEL
                        else self._number(token)
                    )
                    self.mem_dict[address] = _DataItem(address, value, token)
                    address += 1
                else:
                    raise self._error(token, "invalid .byte value")
            return address
        if directive == ".res":
            if len(tokens) != 2 or self._number(tokens[1]) is None:
                raise self._error(tokens[0], ".res requires one numeric count")
            count = self._number(tokens[1])
            if count < 0:
                raise self._error(tokens[1], ".res count cannot be negative")
            for _ in range(count):
                self.mem_dict[address] = _DataItem(address, 0, tokens[1])
                address += 1
            return address
        raise self._error(tokens[0], f"unknown data directive {directive!r}")

    def _pass1(self) -> None:
        counters = dict(self.section_regions)
        for section, _ in self.section_regions:
            for line_number in sorted(self.sections[section]):
                tokens = self.sections[section][line_number]
                index = 0
                if tokens and tokens[0].type is TokenType.LABEL:
                    self._define_label(tokens[0], counters[section])
                    index = 1
                if index == len(tokens):
                    continue
                current = tokens[index]
                if current.type is TokenType.DIRECTIVE:
                    if section != "data":
                        raise self._error(current, "data directives are only valid in .data")
                    counters[section] = self._pass1_data(tokens[index:], counters[section])
                    continue
                if current.type is not TokenType.INSTRUCTION:
                    raise self._error(current, "expected instruction or directive")
                definition, values = self._match_instruction(
                    current.value.upper(), tokens[index + 1:], current
                )
                self.ins_dict[counters[section]] = _InstructionItem(
                    counters[section], definition, values, current
                )
                counters[section] += definition.size_bytes

    def ir_pass(self, code: str) -> dict:
        self.preprocess(code)
        self.tokenize("\n".join(line.text for line in self._expanded_lines))
        self.split_sections()
        self.symbol_table.clear()
        self.ins_dict.clear()
        self.mem_dict.clear()
        self._pass1()
        return {
            "ins": self.ins_dict,
            "data": self.mem_dict,
            "symbol": self.symbol_table,
        }

    def _resolve(self, value: int | str, token: Token) -> int:
        if isinstance(value, int):
            return value
        if value not in self.symbol_table:
            raise self._error(token, f"label {value!r} is not defined")
        return self.symbol_table[value]

    def assemble_data(self) -> bytes:
        mask = (1 << self.isa.data_width) - 1
        output = bytearray()
        for address in sorted(self.mem_dict):
            item = self.mem_dict[address]
            value = self._resolve(item.value, item.token)
            if not 0 <= value <= mask:
                raise self._error(item.token, f"data value {value} does not fit")
            output.extend(value.to_bytes(self.data_len, self.isa.endianness))
        self.data = bytes(output)
        return self.data

    def assemble_ins(self) -> bytes:
        image_size = 1 << self.isa.address_width
        image = bytearray(image_size)
        for address in sorted(self.ins_dict):
            item = self.ins_dict[address]
            values = {
                name: self._resolve(value, item.token)
                for name, value in item.values.items()
            }
            try:
                encoded = item.definition.encode(values, endianness=self.isa.endianness)
            except EncodingError as error:
                raise self._error(item.token, str(error)) from error
            offset = address
            image[offset:offset + len(encoded)] = encoded
        self.ins = bytes(image)
        return self.ins

    def mr_pass(self) -> dict:
        return {"ins": self.assemble_ins(), "data": self.assemble_data()}

    def assemble(self, code: str) -> dict:
        self.ir_pass(code)
        return self.mr_pass()

    @property
    def debug_info(self) -> dict:
        return self.sections
