import unittest

from mxsm.assembler import Assembler
from mxsm.schema import ISA


class AssemblerMacroTests(unittest.TestCase):
    def test_constructor_loads_new_isa_definition(self):
        assembler = Assembler("mx11su.json")

        self.assertIsInstance(assembler.isa, ISA)
        self.assertEqual(assembler.nmi_addr, assembler.isa.spec.get("nmi_vector", 0))
        self.assertEqual(assembler.irq_addr, assembler.isa.spec.get("irq_vector", 0))
        self.assertEqual(assembler.ins_len, max(i.size_bytes for i in assembler.isa.all_instructions()))
        self.assertEqual(assembler.data_len, (assembler.isa.data_width + 7) // 8)
        self.assertEqual(assembler.tokenizer.INSR_LIST, assembler.isa.instructions)

    def test_macro_expands_before_isa_ir_pass(self):
        assembler = Assembler("mx11su.json")
        result = assembler.ir_pass(
            ".macro CLEAR\nNOP\n.endmacro\n.ins\nCLEAR\n"
        )

        self.assertEqual(len(result["ins"]), 1)


if __name__ == "__main__":
    unittest.main()