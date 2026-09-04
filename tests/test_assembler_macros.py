import json
import tempfile
import unittest
from pathlib import Path

from mxsm.assembler import Assembler
from mxsm.object_format import make_magic, unpack_header, unpack_object
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

    def test_assemble_object_preserves_sparse_sections_and_symbols(self):
        assembler = Assembler("mx11su.json")

        result = assembler.assemble_object(
            ".ins\nstart:\nNOP\n.nmi\nhandler:\nNOP\n"
        )

        self.assertEqual(result["format"], "mxsm-object")
        self.assertEqual(result["symbols"]["start"], {"section": "ins", "offset": 0})
        self.assertEqual(result["symbols"]["handler"], {"section": "nmi", "offset": 0})
        self.assertEqual(
            result["sections"],
            [
                {"name": "ins", "records": [{"address": 0, "data": "00"}]},
                {"name": "nmi", "records": [{"address": 128, "data": "00"}]},
            ],
        )
        json.dumps(result)

    def test_assemble_object_keeps_symbol_relocations(self):
        assembler = Assembler("mx11su.json")

        result = assembler.assemble_object(".ins\nstart:\nNOP\n.data\n.byte &start\n")

        self.assertEqual(result["sections"][0]["records"][0]["data"], "00")
        self.assertEqual(result["relocations"][0]["symbol"], "start")
        self.assertEqual(result["relocations"][0]["section"], "data")

    def test_assemble_packed_combines_section_records(self):
        assembler = Assembler("mx11su.json")

        result = assembler.assemble_object(".ins\nNOP\n", packed=True)

        self.assertEqual(result["format"], "mxsm-packed")
        self.assertEqual(result["sections"], [{"name": "ins", "address": 0, "data": "00"}])

    def test_assemble_binary_object_has_linker_tables(self):
        assembler = Assembler("mx11su.json")

        result = assembler.assemble_binary_object(".ins\nstart:\nNOP\n")
        header = unpack_header(result)

        self.assertEqual(result[:8], make_magic(1, 1))
        self.assertEqual(header["section_count"], 1)
        self.assertLess(len(result), 100)

    def test_binary_object_preserves_imported_relocation_symbols(self):
        result = Assembler("mx11su.json").assemble_binary_object(
            ".import external\n.data\n.byte &external\n"
        )
        decoded = unpack_object(result)
        self.assertEqual(decoded["imports"], ["external"])
        self.assertEqual(decoded["relocations"][0]["symbol"], "external")

    def test_assemble_object_does_not_allocate_address_space(self):
        assembler = Assembler({
            "isa": "wide",
            "word_size": 8,
            "address_width": 32,
            "instructions": [{"mnemonic": "NOP", "encoding": "00000000"}],
        })

        result = assembler.assemble_object("NOP\n")

        self.assertEqual(
            result["sections"][0]["records"],
            [{"address": 0, "data": "00"}],
        )

    def test_include_import_export_and_layout_directives(self):
        with tempfile.TemporaryDirectory() as directory:
            include_path = Path(directory) / "constants.mx11"
            include_path.write_text(".data\n.export shared\nshared:\n.byte 7\n")
            source_path = Path(directory) / "main.mx11"
            source_path.write_text(
                f'.include "{include_path.name}"\n.import external\n.data\n.align 4\n.byte &external\n.space 1\n'
            )
            result = Assembler("mx11su.json").assemble_object(
                source_path.read_text(), packed=True, source_name=str(source_path)
            )

        self.assertEqual(result["exports"], ["shared"])
        self.assertEqual(result["imports"], ["external"])
        self.assertEqual(result["sections"][0]["address"], 0)
        self.assertEqual(result["sections"][0]["data"], "070000000000")


if __name__ == "__main__":
    unittest.main()