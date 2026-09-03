"""Source-level macro expansion for assembly programs."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class MacroError(Exception):
    """Raised for invalid macro definitions or expansion requests."""


@dataclass(frozen=True)
class SourceLocation:
    source: str
    line: int


@dataclass
class ExpandedLine:
    text: str
    location: SourceLocation
    expansion_stack: List[str] = field(default_factory=list)


@dataclass
class MacroDefinition:
    name: str
    parameters: List[str]
    body: List[ExpandedLine]
    location: SourceLocation


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MACRO_HEADER = re.compile(r"^\s*\.macro\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+(.*?))?\s*(?:;.*)?$", re.IGNORECASE)


def _remove_comment(line: str) -> str:
    quoted = False
    escaped = False
    for index, character in enumerate(line):
        if character == "\\" and quoted and not escaped:
            escaped = True
            continue
        if character == '"' and not escaped:
            quoted = not quoted
        if character == ";" and not quoted:
            return line[:index]
        escaped = False
    return line


def _split_arguments(text: str) -> List[str]:
    arguments: List[str] = []
    start = 0
    depth = 0
    quoted = False
    escaped = False
    for index, character in enumerate(text):
        if character == "\\" and quoted and not escaped:
            escaped = True
            continue
        if character == '"' and not escaped:
            quoted = not quoted
        elif not quoted and character in "([{":
            depth += 1
        elif not quoted and character in ")]}":
            depth -= 1
            if depth < 0:
                raise MacroError("unbalanced argument delimiters")
        elif character == "," and not quoted and depth == 0:
            value = text[start:index].strip()
            if not value:
                raise MacroError("empty macro argument")
            arguments.append(value)
            start = index + 1
        escaped = False
    if quoted or depth:
        raise MacroError("unterminated string or argument delimiter")
    value = text[start:].strip()
    if value:
        arguments.append(value)
    elif text.strip():
        raise MacroError("empty macro argument")
    return arguments


def _bind_parameters(definition: MacroDefinition, text: str) -> Dict[str, str]:
    arguments = _split_arguments(text)
    positional: List[str] = []
    named: Dict[str, str] = {}
    named_started = False
    for argument in arguments:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", argument)
        if match:
            named_started = True
            name, value = match.group(1), match.group(2).strip()
            if not value:
                raise MacroError(f"macro {definition.name}: empty value for {name!r}")
            if name in named:
                raise MacroError(f"macro {definition.name}: duplicate argument {name!r}")
            if name not in definition.parameters:
                raise MacroError(f"macro {definition.name}: unknown argument {name!r}")
            named[name] = value
        else:
            if named_started:
                raise MacroError(f"macro {definition.name}: positional argument follows named argument")
            positional.append(argument)
    if len(positional) > len(definition.parameters):
        raise MacroError(f"macro {definition.name}: too many arguments")
    values = dict(zip(definition.parameters, positional))
    values.update(named)
    missing = [name for name in definition.parameters if name not in values]
    if missing:
        raise MacroError(f"macro {definition.name}: missing argument(s): {', '.join(missing)}")
    return values


class MacroProcessor:
    def __init__(self, *, max_depth: int = 64, max_lines: int = 100000):
        self.max_depth = max_depth
        self.max_lines = max_lines
        self.macros: Dict[str, MacroDefinition] = {}
        self._expansion_id = 0

    def collect(self, source: str, source_name: str = "<source>") -> List[ExpandedLine]:
        lines = source.splitlines()
        emitted: List[ExpandedLine] = []
        index = 0
        while index < len(lines):
            raw = lines[index]
            header = _MACRO_HEADER.match(_remove_comment(raw))
            if not header:
                if _remove_comment(raw).strip().lower().startswith(".endmacro"):
                    raise MacroError(f"line {index + 1}: .endmacro without .macro")
                emitted.append(ExpandedLine(raw, SourceLocation(source_name, index + 1)))
                index += 1
                continue
            name = header.group(1)
            key = name.upper()
            raw_parameters = header.group(2) or ""
            parameters = [value.strip() for value in _split_arguments(raw_parameters)] if raw_parameters.strip() else []
            if any(not _IDENTIFIER.fullmatch(parameter) for parameter in parameters):
                raise MacroError(f"line {index + 1}: invalid macro parameter")
            if len(parameters) != len(set(parameters)):
                raise MacroError(f"line {index + 1}: duplicate macro parameter")
            if key in self.macros:
                raise MacroError(f"line {index + 1}: duplicate macro {name!r}")
            body: List[ExpandedLine] = []
            definition_line = index + 1
            index += 1
            while index < len(lines):
                body_line = lines[index]
                clean = _remove_comment(body_line).strip().lower()
                if clean.startswith(".macro"):
                    raise MacroError(f"line {index + 1}: nested macro definitions are not supported")
                if clean.startswith(".endmacro"):
                    break
                if clean in {".data", ".ins", ".nmi", ".irq", ".function", ".endfunction"}:
                    raise MacroError(f"line {index + 1}: {clean} is not allowed in a macro body")
                body.append(ExpandedLine(body_line, SourceLocation(source_name, index + 1)))
                index += 1
            if index == len(lines):
                raise MacroError(f"line {definition_line}: macro {name!r} is not closed")
            self.macros[key] = MacroDefinition(name, parameters, body, SourceLocation(source_name, definition_line))
            index += 1
        return emitted

    def expand(self, lines: List[ExpandedLine]) -> List[ExpandedLine]:
        output: List[ExpandedLine] = []
        for line in lines:
            self._expand_line(line, output, [])
        return output

    def process(self, source: str, source_name: str = "<source>") -> List[ExpandedLine]:
        return self.expand(self.collect(source, source_name))

    def _expand_line(self, line: ExpandedLine, output: List[ExpandedLine], stack: List[str]) -> None:
        if len(output) >= self.max_lines:
            raise MacroError(f"macro expansion exceeded maximum line count ({self.max_lines})")
        code = _remove_comment(line.text).strip()
        if not code:
            output.append(line)
            return
        match = re.match(r"^(?:(?P<label>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\s+(?P<args>.*?))?\s*$", code)
        if not match or match.group("name").upper() not in self.macros:
            output.append(line)
            return
        name = match.group("name").upper()
        if name in stack:
            chain = " -> ".join(stack + [name])
            raise MacroError(f"recursive macro expansion: {chain}")
        if len(stack) >= self.max_depth:
            raise MacroError(f"macro expansion exceeded maximum depth ({self.max_depth})")
        definition = self.macros[name]
        values = _bind_parameters(definition, match.group("args") or "")
        self._expansion_id += 1
        expansion_name = f"{definition.name}#{self._expansion_id}"
        local_labels = {}
        for body_line in definition.body:
            for local in re.findall(r"%%([A-Za-z_][A-Za-z0-9_]*)", body_line.text):
                local_labels.setdefault(local, f"__{definition.name}_{self._expansion_id}_{local}")
        first = True
        for body_line in definition.body:
            text = body_line.text
            for parameter, value in values.items():
                text = re.sub(rf"\\{re.escape(parameter)}\b", value, text)
            for local, generated in local_labels.items():
                text = re.sub(rf"%%{re.escape(local)}\b", generated, text)
            if first and match.group("label"):
                text = f"{match.group('label')}: {text}"
            first = False
            generated_line = ExpandedLine(text, line.location, stack + [expansion_name])
            self._expand_line(generated_line, output, stack + [name])
