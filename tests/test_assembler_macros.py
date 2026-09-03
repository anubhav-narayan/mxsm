import json
import unittest

from mxsm.assembler import Assembler


class AssemblerMacroTests(unittest.TestCase):
    def test_macro_expands_before_legacy_ir_pass(self):
        with open("examples/prod.tab.json") as handle:
            assembler = Assembler(json.dumps(json.load(handle)))

        result = assembler.ir_pass(
            ".macro CLEAR\nCLR\n.endmacro\n.ins\nCLEAR\n"
        )

        self.assertEqual(len(result["ins"]), 1)


if __name__ == "__main__":
    unittest.main()