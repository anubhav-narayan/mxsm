import unittest

from mxsm.schema import ISA
from mxsm.source_analysis import analyze_source
from mxsm.tokenizer import TokenType, Tokenizer


class SourceAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.isa = ISA.from_dict({
            "isa": "Demo",
            "registers": {"A": 0},
            "instructions": [
                {"mnemonic": "CALL", "operands": [{"name": "target", "type": "label"}], "encoding": "11110000 {target:8}"},
                {"mnemonic": "RET", "operands": [], "encoding": "11111111"},
            ],
        })

    def test_tokenizer_preserves_function_labels_and_symbols(self):
        tokens = Tokenizer(self.isa.instructions, self.isa.registers).tokenize_line("entry: CALL worker", 0)

        self.assertEqual([token.type for token in tokens], [TokenType.LABEL, TokenType.INSTRUCTION, TokenType.SYMBOL])
        self.assertEqual([token.value for token in tokens], ["entry", "CALL", "worker"])

    def test_analyzes_function_labels_and_calls(self):
        analysis = analyze_source(self.isa, ".function main\nentry: CALL worker\nRET\n.endfunction\n")

        self.assertEqual(analysis.functions[0].name, "main")
        self.assertEqual(analysis.functions[0].labels, ["entry"])
        self.assertEqual(analysis.functions[0].calls, ["worker"])
        self.assertFalse(analysis.errors)


if __name__ == "__main__":
    unittest.main()