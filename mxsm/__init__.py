from .schema import ISA, ISAEncodingIndex, ISAError


def __getattr__(name):
	if name == "Assembler":
		from .assembler import Assembler
		return Assembler
	if name == "Disassembler":
		from .disassembler import Disassembler
		return Disassembler
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["Assembler", "Disassembler", "ISA", "ISAEncodingIndex", "ISAError"]