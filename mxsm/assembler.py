"""Two-pass assembler driven by the validated ISA schema."""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .bitfield import EncodingError
from .line_assembler import _try_alias
from .preprocessor import ExpandedLine, MacroProcessor
from .schema import ISA, InstructionDef, OperandDef
from .tokenizer import Token, TokenType, Tokenizer
from .object_format import pack_object


class AssemblyError(SyntaxError):
    """Raised when source cannot be parsed, resolved, or encoded."""


@dataclass
class _InstructionItem:
    section: str
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
        self.symbol_sections: Dict[str, str] = {}
        self.ins_dict: Dict[int, _InstructionItem] = {}
        self.mem_dict: Dict[int, _DataItem] = {}
        self.ins = b""
        self.data = b""
        self._expanded_lines: List[ExpandedLine] = []
        self.imported_symbols: set[str] = set()
        self.exported_symbols: set[str] = set()

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

    @staticmethod
    def _include_source(code: str, source_name: str, include_stack: tuple[Path, ...] = ()) -> str:
        """Expand .include directives relative to the including source file."""
        output: list[str] = []
        base = Path(source_name).parent if source_name not in {"", "<source>"} else Path.cwd()
        pattern = re.compile(r'^\s*\.include\s+(?:"([^"]+)"|<([^>]+)>)\s*(?:;.*)?$', re.IGNORECASE)
        for line_number, line in enumerate(code.splitlines(), 1):
            match = pattern.match(line)
            if not match:
                output.append(line)
                continue
            include_path = (base / (match.group(1) or match.group(2))).resolve()
            if include_path in include_stack:
                chain = " -> ".join(str(path) for path in (*include_stack, include_path))
                raise AssemblyError(f"recursive .include: {chain}")
            try:
                included = include_path.read_text()
            except OSError as error:
                raise AssemblyError(
                    f"{source_name}:{line_number}: cannot read included file {include_path}"
                ) from error
            output.append(Assembler._include_source(included, str(include_path), (*include_stack, include_path)))
        return "\n".join(output)

    def preprocess(self, code: str, source_name: str = "<source>") -> str:
        """Expand macros and retain the expanded source for diagnostics."""
        code = self._include_source(code, source_name)
        self._expanded_lines = MacroProcessor().process(code, source_name)
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

    def _define_label(self, token: Token, section: str, address: int) -> None:
        if token.value in self.symbol_table:
            raise self._error(token, f"duplicate label {token.value!r}")
        self.symbol_table[token.value] = address
        self.symbol_sections[token.value] = section

    def _pass1_data(self, tokens: List[Token], address: int) -> int:
        directive = tokens[0].value.lower()
        if directive in {".byte", ".word"}:
            if len(tokens) == 1:
                raise self._error(tokens[0], f"{directive} requires at least one value")
            for token in tokens[1:]:
                if token.type is TokenType.STRING:
                    if directive != ".byte":
                        raise self._error(token, ".word does not accept strings")
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
                    address += self.data_len if directive == ".word" else 1
                else:
                    raise self._error(token, f"invalid {directive} value")
            return address
        if directive in {".res", ".space"}:
            if len(tokens) != 2 or self._number(tokens[1]) is None:
                raise self._error(tokens[0], f"{directive} requires one numeric count")
            count = self._number(tokens[1])
            if count < 0:
                raise self._error(tokens[1], f"{directive} count cannot be negative")
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
                    self._define_label(tokens[0], section, counters[section])
                    index = 1
                if index == len(tokens):
                    continue
                current = tokens[index]
                if current.type is TokenType.DIRECTIVE:
                    directive = current.value.lower()
                    if directive in {".import", ".export"}:
                        if len(tokens) < 2 or any(
                            token.type is not TokenType.SYMBOL for token in tokens[index + 1:]
                        ):
                            raise self._error(current, f"{directive} requires one or more symbols")
                        target = (
                            self.imported_symbols
                            if directive == ".import"
                            else self.exported_symbols
                        )
                        target.update(token.value for token in tokens[index + 1:])
                        continue
                    if directive == ".align":
                        if len(tokens) != index + 2 or self._number(tokens[index + 1]) is None:
                            raise self._error(current, ".align requires one numeric boundary")
                        alignment = self._number(tokens[index + 1])
                        if alignment <= 0:
                            raise self._error(tokens[index + 1], ".align boundary must be positive")
                        counters[section] = (
                            (counters[section] + alignment - 1) // alignment
                        ) * alignment
                        continue
                    if directive == ".org":
                        if len(tokens) != index + 2 or self._number(tokens[index + 1]) is None:
                            raise self._error(current, ".org requires one numeric address")
                        address = self._number(tokens[index + 1])
                        if address < 0:
                            raise self._error(tokens[index + 1], ".org address cannot be negative")
                        counters[section] = address
                        continue
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
                    section, counters[section], definition, values, current
                )
                counters[section] += definition.size_bytes

    def ir_pass(self, code: str, *, source_name: str = "<source>") -> dict:
        self.imported_symbols.clear()
        self.exported_symbols.clear()
        self.preprocess(code, source_name)
        self.tokenize("\n".join(line.text for line in self._expanded_lines))
        self.split_sections()
        self.symbol_table.clear()
        self.symbol_sections.clear()
        self.ins_dict.clear()
        self.mem_dict.clear()
        self._pass1()
        invalid_exports = self.exported_symbols - self.symbol_table.keys()
        if invalid_exports:
            raise AssemblyError(
                f"exported symbol(s) are not defined: {', '.join(sorted(invalid_exports))}"
            )
        for name in self.imported_symbols & self.symbol_table.keys():
            raise AssemblyError(f"imported symbol {name!r} is also defined locally")
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
        if not self.mem_dict:
            self.data = b""
            return self.data
        output = bytearray((max(self.mem_dict) + self.data_len))
        for address in sorted(self.mem_dict):
            item = self.mem_dict[address]
            value = self._resolve(item.value, item.token)
            if not 0 <= value <= mask:
                raise self._error(item.token, f"data value {value} does not fit")
            encoded = value.to_bytes(self.data_len, self.isa.endianness)
            output[address:address + self.data_len] = encoded
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

    @staticmethod
    def _append_record(records: list[dict], address: int, encoded: bytes) -> None:
        if records and records[-1]["address"] + len(bytes.fromhex(records[-1]["data"])) == address:
            records[-1]["data"] += encoded.hex()
        else:
            records.append({"address": address, "data": encoded.hex()})

    def _encode_object_instruction(self, item: _InstructionItem) -> tuple[bytes, list[dict]]:
        values = {}
        relocations = []
        for name, value in item.values.items():
            if isinstance(value, str):
                values[name] = 0
                relocations.append({
                    "section": item.section,
                    "offset": item.address,
                    "symbol": value,
                    "field": name,
                    "type": "absolute",
                    "width": item.definition.pattern.field_widths[name],
                })
            else:
                values[name] = value
        try:
            encoded = item.definition.encode(values, endianness=self.isa.endianness)
        except EncodingError as error:
            raise self._error(item.token, str(error)) from error
        return encoded, relocations

    def assemble_object(
        self, code: str, *, packed: bool = False, source_name: str = "<source>"
    ) -> dict:
        """Return a sparse, JSON-serializable object file representation.

        Section records contain load addresses and only populated byte ranges,
        allowing consumers to load or link programs without allocating the
        entire address space.
        """
        self.ir_pass(code, source_name=source_name)
        sections = {name: [] for name in self.section_labels}
        relocations = []
        for address in sorted(self.ins_dict):
            item = self.ins_dict[address]
            encoded, item_relocations = self._encode_object_instruction(item)
            relocations.extend(item_relocations)
            self._append_record(sections[item.section], address, encoded)

        mask = (1 << self.isa.data_width) - 1
        for address in sorted(self.mem_dict):
            item = self.mem_dict[address]
            if isinstance(item.value, str):
                value = 0
                relocations.append({
                    "section": "data",
                    "offset": address,
                    "symbol": item.value,
                    "type": "absolute",
                    "width": self.isa.data_width,
                })
            else:
                value = item.value
            if not 0 <= value <= mask:
                raise self._error(item.token, f"data value {value} does not fit")
            encoded = value.to_bytes(self.data_len, self.isa.endianness)
            self._append_record(sections["data"], address, encoded)

        section_bases = dict(self.section_regions)
        symbols = {
            name: {
                "section": self.symbol_sections[name],
                "offset": address - section_bases[self.symbol_sections[name]],
            }
            for name, address in sorted(self.symbol_table.items())
        }
        result = {
            "format": "mxsm-packed" if packed else "mxsm-object",
            "version": 1,
            "isa": self.isa.name,
            "address_width": self.isa.address_width,
            "data_width": self.isa.data_width,
            "endianness": self.isa.endianness,
            "sections": [],
            "symbols": symbols,
            "relocations": relocations,
            "imports": sorted(self.imported_symbols),
            "exports": sorted(self.exported_symbols),
        }
        for name, records in sections.items():
            if not records:
                continue
            if not packed:
                result["sections"].append({"name": name, "records": records})
                continue
            first = records[0]["address"]
            payload = bytearray()
            for record in records:
                gap = record["address"] - (first + len(payload))
                payload.extend(b"\0" * gap)
                payload.extend(bytes.fromhex(record["data"]))
            result["sections"].append({
                "name": name,
                "address": first,
                "data": bytes(payload).hex(),
            })
        return result

    def assemble_binary_object(self, code: str, *, source_name: str = "<source>") -> bytes:
        """Return a compact MXO binary object suitable for a linker."""
        return pack_object(self.assemble_object(code, packed=True, source_name=source_name))

    def mr_pass(self) -> dict:
        return {"ins": self.assemble_ins(), "data": self.assemble_data()}

    def assemble(self, code: str, *, source_name: str = "<source>") -> dict:
        self.ir_pass(code, source_name=source_name)
        return self.mr_pass()

    @property
    def debug_info(self) -> dict:
        return self.sections
