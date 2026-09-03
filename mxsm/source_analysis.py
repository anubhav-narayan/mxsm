"""Structural analysis for assembly source before instruction assembly."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .tokenizer import Token, TokenType, Tokenizer
from .preprocessor import MacroProcessor


@dataclass
class FunctionAnalysis:
    name: str
    start_line: int
    end_line: Optional[int] = None
    labels: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)


@dataclass
class SourceAnalysis:
    functions: List[FunctionAnalysis] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    directives: List[str] = field(default_factory=list)
    instructions: List[Token] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def analyze_source(isa, source: str, *, preprocess: bool = True) -> SourceAnalysis:
    """Collect functions, labels, directives, and instructions from source.

    Function directives are deliberately generic. A target can use ``CALL``,
    ``JSR``, or another call instruction; all instruction lines remain in the
    token stream for the later architecture-specific assembler.
    """
    if preprocess:
        expanded = MacroProcessor().process(source)
        source = "\n".join(line.text for line in expanded)
    tokenizer = Tokenizer(isa.instructions, isa.registers)
    lines = tokenizer.tokenize(source)
    result = SourceAnalysis()
    current: Optional[FunctionAnalysis] = None
    for line_number, tokens in lines.items():
        if not tokens:
            continue
        directive = next((token for token in tokens if token.type is TokenType.DIRECTIVE), None)
        if directive is not None:
            result.directives.append(directive.value)
            if directive.value.lower() == ".function":
                name = next((token.value for token in tokens[tokens.index(directive) + 1:] if token.type is TokenType.SYMBOL), None)
                if name is None:
                    result.errors.append(f"line {line_number + 1}: .function requires a name")
                elif current is not None:
                    result.errors.append(f"line {line_number + 1}: nested function {name!r}")
                else:
                    current = FunctionAnalysis(name, line_number)
                    result.functions.append(current)
            elif directive.value.lower() == ".endfunction":
                if current is None:
                    result.errors.append(f"line {line_number + 1}: .endfunction without .function")
                else:
                    current.end_line = line_number
                    current = None

        for token in tokens:
            if token.type is TokenType.LABEL:
                result.labels.append(token.value)
                if current is not None:
                    current.labels.append(token.value)
            elif token.type is TokenType.INSTRUCTION:
                result.instructions.append(token)
                if current is not None and token.value.upper() in {"CALL", "JSR", "JAL", "BL", "BSR"}:
                    target = next((candidate.value for candidate in tokens[tokens.index(token) + 1:] if candidate.type is TokenType.SYMBOL), None)
                    if target is not None:
                        current.calls.append(target)
    if current is not None:
        result.errors.append(f"line {current.start_line + 1}: function {current.name!r} is not closed")
    return result


def analyze_file(isa, path: str | Path) -> SourceAnalysis:
    return analyze_source(isa, Path(path).read_text())