"""
mxsm REL -- an interactive assembler REPL.

    1. Reads the ISA's JSON definition.
    2. Builds the ISA schema from it.
    3. Is now ready to produce machine code for any line typed at it,
       using nothing but that schema -- no separate opcode table.
    4. Provides history, editing, and completion through prompt_toolkit.
    5. Checks the line against the ISA: on success, prints the encoded
       machine code as hex next to the recognised mnemonic/operands; on
       failure, prints an explanation and loops back to re-prompt.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mxsm.schema import ISA, ISAError                               # noqa: E402
from mxsm.line_assembler import assemble_line, LineAssemblyError   # noqa: E402
from mxsm.tokenizer import Token, Tokenizer, TokenType                       # noqa: E402
from mxsm.source_analysis import analyze_file                                 # noqa: E402
from prompt_toolkit import PromptSession                                     # noqa: E402
from prompt_toolkit.completion import Completer, Completion                   # noqa: E402
from prompt_toolkit.history import FileHistory                                # noqa: E402
from prompt_toolkit.styles import Style                                        # noqa: E402

DEFAULT_ISA = Path(__file__).resolve().parent.parent / "mx11su.json"
HISTORY_FILE = Path.home() / ".cache" / "mxsm" / "repl.history"


class ISACompleter(Completer):
    """Complete mnemonics and register names from the loaded ISA."""

    def __init__(self, isa: ISA):
        self.words = sorted(set(isa.instructions + isa.registers + ["quit", "exit", ":help", ":forms", ":registers", ":analyze"]))

    def get_completions(self, document, complete_event):
        word = document.get_word_before_cursor()
        for candidate in self.words:
            if candidate.lower().startswith(word.lower()):
                yield Completion(candidate, start_position=-len(word))


def _format_tokens(tokens: list[Token]) -> str:
    if not tokens:
        return "  (no tokens)"
    return "  " + "  ".join(
        f"{token.type.name}={token.value!r}@{token.column}"
        for token in tokens
    )


def _analyze_line(tokenizer: Tokenizer, line: str) -> list[Token]:
    tokens = tokenizer.tokenize_line(line, 0)
    print("Tokens:")
    print(_format_tokens(tokens))
    return tokens


def _print_help(isa: ISA) -> None:
    print("Enter an assembly instruction, or one of these commands:")
    print("  :help       Show this help")
    print("  :forms      List instruction forms")
    print("  :registers  List register names")
    print("  :analyze FILE Analyze functions, labels, directives, and calls")
    print("  :tokens ... Analyze tokens without assembling")
    print("  :quit       Exit the REPL")
    print(f"Loaded {isa.name} with {len(isa.instructions)} mnemonics.\n")


def _print_forms(isa: ISA) -> None:
    for mnemonic in isa.instructions:
        for instruction in isa.search_mnemonic(mnemonic):
            operands = ", ".join(operand.name for operand in instruction.operands)
            suffix = f" {operands}" if operands else ""
            print(f"  {instruction.mnemonic}{suffix} -> {instruction.encoding}")
    print()


def run_repl(isa: ISA, *, history_file: Path = HISTORY_FILE) -> None:
    history_file.parent.mkdir(parents=True, exist_ok=True)
    session = PromptSession(
        history=FileHistory(str(history_file)),
        completer=ISACompleter(isa),
        complete_while_typing=True,
        style=Style.from_dict({
            "prompt": "ansicyan bold",
            "completion-menu.completion": "bg:#202020 #ffffff",
            "completion-menu.completion.current": "bg:#00aaaa #000000",
        }),
    )
    tokenizer = Tokenizer(isa.instructions, isa.registers)

    n_forms = len(isa.all_instructions())
    print(f"mxsm REL -- loaded ISA {isa.name!r} "
          f"({len(isa.instructions)} mnemonics, {n_forms} instruction form(s), "
          f"{isa.word_size}-bit word, {isa.endianness}-endian)")
    print("Type an instruction, :help, or :quit. Press Ctrl-D to exit.\n")

    while True:
        try:
            line = session.prompt("mxsm> ", refresh_interval=0.05)
        except (EOFError, KeyboardInterrupt):
            print()
            return

        command = line.strip().lower()
        if command in {"quit", "exit", ":quit", ":exit"}:
            return
        if command == ":help":
            _print_help(isa)
            continue
        if command == ":forms":
            _print_forms(isa)
            continue
        if command == ":registers":
            print("  " + ", ".join(isa.registers) + "\n")
            continue
        if command.startswith(":analyze "):
            try:
                analysis = analyze_file(isa, line.split(None, 1)[1])
            except (OSError, ValueError) as error:
                print(f"  error: {error}\n")
                continue
            print(f"  functions: {len(analysis.functions)}")
            for function in analysis.functions:
                end = function.end_line + 1 if function.end_line is not None else "unclosed"
                print(f"    {function.name}: lines {function.start_line + 1}-{end}")
                if function.labels:
                    print(f"      labels: {', '.join(function.labels)}")
                if function.calls:
                    print(f"      calls: {', '.join(function.calls)}")
            print(f"  labels: {', '.join(analysis.labels) or '(none)'}")
            print(f"  directives: {', '.join(analysis.directives) or '(none)'}")
            if analysis.errors:
                print("  errors:")
                for error in analysis.errors:
                    print(f"    {error}")
            print()
            continue
        if command == ":tokens" or command.startswith(":tokens "):
            _analyze_line(tokenizer, line[len(":tokens"):].lstrip())
            print()
            continue
        if not line.strip():
            continue

        tokens = _analyze_line(tokenizer, line)
        if any(token.type in {
            TokenType.DIRECTIVE,
            TokenType.LABEL,
            TokenType.STRING,
            TokenType.ADDRESS_LABEL,
            TokenType.ADDRESS_NUMBER,
        } for token in tokens):
            print("Directive/label input analyzed; full multi-line assembly is not run in the REPL.\n")
            continue

        try:
            result = assemble_line(isa, line)
        except LineAssemblyError as error:
            print(f"  error: {error}\n")
            continue

        operands = ", ".join(token.value for token in result.operand_tokens)
        shown = f"{result.mnemonic}{(' ' + operands) if operands else ''}"
        print(f"  {shown:<20} -> 0x{result.hex}  "
              f"({result.ins_def.pattern.width_bytes} byte(s))\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Interactive assembler REPL for MXSM ISA JSON file")
    parser.add_argument(
        "isa_json",
        nargs="?",
        type=Path,
        default=DEFAULT_ISA,
        help=f"ISA JSON definition (default: {DEFAULT_ISA})",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=HISTORY_FILE,
        help=f"history file (default: {HISTORY_FILE})",
    )
    args = parser.parse_args(argv)
    isa_path = args.isa_json

    # --- 1 & 2: read the ISA's JSON definition and build the schema ---
    try:
        isa = ISA.from_json(isa_path)
    except (ISAError, OSError) as e:
        print(f"failed to load ISA from {isa_path}: {e}", file=sys.stderr)
        sys.exit(1)

    run_repl(isa, history_file=args.history)


if __name__ == "__main__":
    main()