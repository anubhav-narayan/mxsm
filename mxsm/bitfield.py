"""
Bitfield-pattern based instruction encoding.

An encoding pattern is a whitespace-separated string of tokens describing
how a fixed-format instruction's bits are laid out:

  - A run of '0'/'1' characters is a *literal* bit-field: emitted (and,
    for disassembly, matched) exactly as written.
  - ``{name:WIDTH}`` is a WIDTH-bit field sourced from operand ``name``.
  - ``{name[HI:LO]}`` slices bits HI..LO (inclusive, HI >= LO) out of
    operand ``name``'s value. This lets a single operand's bits be
    scattered across non-adjacent positions in the instruction word,
    which real ISAs need constantly (e.g. RISC-V's split immediates).

Example::

    "0000 {reg:4}"          -> 8-bit instruction: fixed top nibble + register
    "011 {imm[11:5]} {rs2:5} {rs1:5} 000 {imm[4:0]} 1100011"  -> RISC-V SB-type

Patterns may have any positive bit width. Encoded values use the minimum
number of bytes needed to contain the pattern; unused high bits in the first
byte are zero. For little-endian output, those bytes are reversed after
padding, preserving the pattern's bit ordering within the encoded word.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple, Union


class EncodingError(Exception):
    """Raised for malformed encoding patterns or bad operand values."""


_FIELD_RE = re.compile(
    r"^\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\[(?P<hi>\d+):(?P<lo>\d+)\])?"
    r"(?::(?P<width>\d+))?\}$"
)


@dataclass(frozen=True)
class LiteralSegment:
    bits: str  # e.g. "0000"

    @property
    def width(self) -> int:
        return len(self.bits)


@dataclass(frozen=True)
class FieldSegment:
    name: str
    width: int
    hi: int
    lo: int
    sliced: bool  # True if declared via {name[hi:lo]} (partial value)

    def extract_bits(self, value: int) -> str:
        chunk = (value >> self.lo) & ((1 << self.width) - 1)
        return format(chunk, f"0{self.width}b")


Segment = Union[LiteralSegment, FieldSegment]


def parse_encoding(pattern: str) -> Tuple[List[Segment], int]:
    """Parse an encoding pattern string into segments plus total bit width."""
    segments: List[Segment] = []
    tokens = pattern.split()
    if not tokens:
        raise EncodingError("empty encoding pattern")
    for tok in tokens:
        if tok and set(tok) <= {"0", "1"}:
            segments.append(LiteralSegment(tok))
            continue
        m = _FIELD_RE.match(tok)
        if not m:
            raise EncodingError(f"unrecognised encoding token: {tok!r}")
        name = m.group("name")
        if m.group("hi") is not None:
            hi, lo = int(m.group("hi")), int(m.group("lo"))
            if hi < lo:
                raise EncodingError(f"field '{name}' has hi < lo ({hi} < {lo})")
            if m.group("width") is not None and int(m.group("width")) != hi - lo + 1:
                raise EncodingError(
                    f"field '{name}': explicit width conflicts with [{hi}:{lo}] slice"
                )
            segments.append(FieldSegment(name, hi - lo + 1, hi, lo, sliced=True))
        else:
            if m.group("width") is None:
                raise EncodingError(
                    f"field '{name}' needs an explicit width, e.g. "
                    f"'{{{name}:4}}' or a slice like '{{{name}[7:4]}}'"
                )
            width = int(m.group("width"))
            segments.append(FieldSegment(name, width, width - 1, 0, sliced=False))
    total = sum(s.width for s in segments)
    return segments, total


class BitPattern:
    """A compiled instruction encoding: fixed bits + named operand fields."""

    def __init__(self, pattern: str):
        self.pattern = pattern
        self.segments, self.width_bits = parse_encoding(pattern)
        if self.width_bits <= 0:
            raise EncodingError(f"encoding '{pattern}' must have positive width")
        self.width_bytes = (self.width_bits + 7) // 8
        self.field_names = {s.name for s in self.segments if isinstance(s, FieldSegment)}
        self.field_widths = {
            name: max(
                segment.hi + 1
                for segment in self.segments
                if isinstance(segment, FieldSegment) and segment.name == name
            )
            for name in self.field_names
        }

    def encode(self, operands: Dict[str, int], *, endianness: str = "big") -> bytes:
        missing = self.field_names - operands.keys()
        if missing:
            raise EncodingError(f"missing operand value(s) for: {sorted(missing)}")
        bits: List[str] = []
        for seg in self.segments:
            if isinstance(seg, LiteralSegment):
                bits.append(seg.bits)
                continue
            value = operands[seg.name]
            if not seg.sliced and not (0 <= value < (1 << seg.width)):
                raise EncodingError(
                    f"value {value} for field '{seg.name}' doesn't fit in "
                    f"{seg.width} bit(s)"
                )
            bits.append(seg.extract_bits(value))
        raw = int("".join(bits), 2).to_bytes(self.width_bytes, "big")
        if endianness == "little":
            raw = raw[::-1]
        return raw

    def mask_and_value(self) -> Tuple[int, int]:
        """(mask, value): literal bits are 1 in mask with their required
        value; field bits are 0 in mask (wildcard). Used for disassembly."""
        mask_bits: List[str] = []
        value_bits: List[str] = []
        for seg in self.segments:
            if isinstance(seg, LiteralSegment):
                mask_bits.append("1" * seg.width)
                value_bits.append(seg.bits)
            else:
                mask_bits.append("0" * seg.width)
                value_bits.append("0" * seg.width)
        return int("".join(mask_bits), 2), int("".join(value_bits), 2)

    def matches(self, raw: int) -> bool:
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            return False
        if raw >= (1 << self.width_bits):
            return False
        mask, value = self.mask_and_value()
        return (raw & mask) == value

    def decode_fields(self, raw: int) -> Dict[str, int]:
        """Given a raw integer of width_bits that already matches this
        pattern, extract field values (merging split/sliced fields)."""
        result: Dict[str, int] = {}
        bitstring = format(raw, f"0{self.width_bits}b")
        pos = 0
        for seg in self.segments:
            chunk = bitstring[pos:pos + seg.width]
            pos += seg.width
            if isinstance(seg, FieldSegment):
                val = int(chunk, 2)
                result[seg.name] = result.get(seg.name, 0) | (val << seg.lo)
        return result

    def __repr__(self) -> str:
        return f"BitPattern({self.pattern!r}, width_bits={self.width_bits})"