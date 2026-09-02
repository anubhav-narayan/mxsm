"""
mxsm REL -- a minimal "Read-Elaborate-Loop" assembler REPL.

    1. Reads the ISA's JSON definition.
    2. Builds the ISA schema (mxsm.isa_schema.ISA) from it.
    3. Is now ready to produce machine code for any line typed at it,
       using nothing but that schema -- no separate opcode table.
    4. Prompts for one line of assembly at a time.
    5. Checks the line against the ISA: on success, prints the encoded
       machine code as hex next to the recognised mnemonic/operands; on
       failure, prints an explanation and loops back to re-prompt.

Run: python3 scripts/mxsm_repl.py [path/to/isa.json]
(defaults to mxsm/isa/mx11su.json if no path is given)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mxsm.isa_schema import ISA, ISAError                          # noqa: E402
from mxsm.line_assembler import assemble_line, LineAssemblyError   # noqa: E402

DEFAULT_ISA = Path(__file__).resolve().parent.parent / "mxsm" / "isa" / "mx11su.json"


def main():
    isa_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ISA

    # --- 1 & 2: read the ISA's JSON definition and build the schema ---
    try:
        isa = ISA.from_json(isa_path)
    except (ISAError, OSError) as e:
        print(f"failed to load ISA from {isa_path}: {e}", file=sys.stderr)
        sys.exit(1)

    # --- 3: ready to produce machine code -----------------------------
    n_forms = sum(len(v) for v in isa.instructions.values())
    print(f"mxsm REL -- loaded ISA {isa.name!r} from {isa_path.name} "
          f"({len(isa.mnemonics)} mnemonics, {n_forms} instruction form(s), "
          f"{isa.word_size}-bit word, {isa.endianness}-endian)")
    print("Type a line of assembly, e.g.:  LDI 5   /   ADD X   /   MOV D,A")
    print("Ctrl-D or 'quit' to exit.\n")

    while True:
        # --- 4: read one line -----------------------------------------
        try:
            line = input("mxsm> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if line.strip().lower() in ("quit", "exit"):
            break
        if not line.strip():
            continue

        # --- 5: elaborate (check + encode), report success or error ---
        try:
            result = assemble_line(isa, line)
        except LineAssemblyError as e:
            print(f"  error: {e}\n")
            continue

        operands = ", ".join(result.operand_tokens)
        shown = f"{result.mnemonic}{(' ' + operands) if operands else ''}"
        print(f"  {shown:<20} -> {result.hex}  ({result.ins_def.pattern.width_bytes} byte(s))\n")


if __name__ == "__main__":
    main()