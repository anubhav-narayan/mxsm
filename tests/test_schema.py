import json
import tempfile
import unittest
from pathlib import Path

from mxsm.assembler import Assembler
from mxsm.bitfield import EncodingError
from mxsm.line_assembler import assemble_line
from mxsm.schema import ISA, ISAError, ISAEncodingIndex, ISAProductionTree


def rv32i_test_spec():
    return {
        "isa": "RV32I-test",
        "word_size": 32,
        "address_width": 32,
        "data_width": 32,
        "endianness": "little",
        "registers": {"x0": 0},
        "instructions": [
            {
                "mnemonic": "BEQ",
                "operands": [
                    {"name": "offset", "signed": True},
                    {"name": "rs1", "type": "register"},
                    {"name": "rs2", "type": "register"},
                ],
                "encoding": "{offset[12:12]} {offset[10:5]} {rs2:5} {rs1:5} 000 {offset[4:1]} {offset[11:11]} 1100011",
            },
            {
                "mnemonic": "ADDI",
                "operands": [
                    {"name": "imm", "signed": True},
                    {"name": "rs1", "type": "register"},
                    {"name": "rd", "type": "register"},
                ],
                "encoding": "{imm[11:0]} {rs1:5} 000 {rd:5} 0010011",
            },
        ],
    }


class ISASchemaTests(unittest.TestCase):
    def test_loads_current_mx11_definition(self):
        isa = ISA.from_json("mx11su.json")

        self.assertEqual(isa.schema_version, 1)
        self.assertEqual(isa.name, "MX/11-70")
        self.assertEqual(isa.address_width, 8)
        self.assertEqual(isa.data_width, 8)
        self.assertEqual(len(isa.all_instructions()), 33)
        self.assertEqual(isa.control_set_name, "Control/System")
        self.assertEqual(len(isa.control_instructions), 16)
        self.assertEqual(set(isa.domain_instructions), {0})
        self.assertEqual(isa.domain_names[0], "Base")
        self.assertEqual(len(isa.domain_instructions[0]), 17)
        self.assertEqual(
            next(instruction for instruction in isa.control_instructions if instruction.mnemonic == "DSEL").operation,
            "DAR <- A",
        )

    def test_rejects_domain_encoding_that_overrides_control_set(self):
        definition = {
            "isa": "MX/11-domain-test",
            "control_set": {
                "name": "Control/System",
                "instructions": [{"mnemonic": "DSEL", "encoding": "11110000"}],
            },
            "domains": [{
                "dar": 0,
                "name": "Base",
                "instructions": [{"mnemonic": "OVERRIDE", "encoding": "1111 {value:4}",
                                  "operands": [{"name": "value"}]}],
            }],
        }

        with self.assertRaisesRegex(ISAError, "overlaps Control/System instruction DSEL"):
            ISA.from_dict(definition)

    def test_selector_operand_may_be_absent_or_present(self):
        isa = ISA.from_json("mx11su.json")

        without_selector = assemble_line(isa, "BNZ A")
        with_selector = assemble_line(isa, "BNZ INSP, A")

        self.assertEqual(without_selector.encoded, b"\xa0")
        self.assertEqual(with_selector.encoded, b"\xa8")

    def test_alias_can_have_different_operand_count(self):
        isa = ISA.from_json("mx11su.json")

        implicit = assemble_line(isa, "ADD")
        explicit = assemble_line(isa, "ADD X, Y")

        self.assertEqual(implicit.encoded, b"\xc0")
        self.assertEqual(explicit.encoded, b"\xc0")

    def test_alias_rewrites_source_operands(self):
        isa = ISA.from_json("mx11su.json")

        result = assemble_line(isa, "MOV MBR, X")

        self.assertEqual(result.encoded, b"\x11")

    def test_build_expands_instruction_form(self):
        isa = ISA.from_dict({
            "isa": "X",
            "registers": {"A": 0, "X": 1},
            "instructions": [{
                "mnemonic": "MOV",
                "operands": [
                    {"name": "dst", "type": "register"},
                    {"name": "value", "type": "immediate"},
                ],
                "encoding": "{dst:1} {value:2} 00000",
            }],
        })

        expansions = isa.build(isa.search_mnemonic("MOV")[0])

        self.assertEqual(len(expansions), 8)
        self.assertEqual(expansions[0], ({"dst": 0, "value": 0}, b"\x00"))
        self.assertEqual(expansions[-1], ({"dst": 1, "value": 3}, b"\xe0"))

    def test_models_instruction_and_address_widths(self):
        isa = ISA.from_dict({
            "isa": "6502-test",
            "address_width": 16,
            "data_width": 8,
            "endianness": "big",
            "instructions": [
                {
                    "mnemonic": "LDA",
                    "operands": [{"name": "value", "size": 8}],
                    "encoding": "10101001 {value:8}",
                },
                {
                    "mnemonic": "LDA",
                    "operands": [{"name": "address", "type": "memory", "size": 16}],
                    "encoding": "10101101 {address[7:0]} {address[15:8]}",
                },
            ],
        })

        self.assertEqual(isa.address_width, 16)
        self.assertEqual(isa.data_width, 8)
        self.assertEqual(isa.find("LDA", 1).size_bytes, 2)
        self.assertEqual(isa.find("LDA", 1).operands[0].size, 8)

        absolute = isa.search_mnemonic("LDA")[1]
        self.assertEqual(absolute.encode({"address": 0x1234}), b"\xad\x34\x12")

    def test_encodes_and_indexes_rv32i_split_immediate(self):
        isa = ISA.from_dict(rv32i_test_spec())
        index = ISAEncodingIndex(isa)

        self.assertEqual(isa.address_width, 32)
        self.assertEqual(isa.data_width, 32)
        self.assertEqual(len(index.entries), 2)

        branch = isa.find("BEQ", 3)
        encoded = branch.encode({"offset": 2, "rs1": 0, "rs2": 0}, endianness=isa.endianness)
        self.assertEqual(encoded, b"\x63\x01\x00\x00")
        matches = index.search_bytes(encoded)
        self.assertEqual(matches[0][0].mnemonic, "BEQ")
        self.assertEqual(matches[0][1]["offset"], 2)

    def test_rejects_operand_size_smaller_than_encoding(self):
        definition = {
            "isa": "X",
            "instructions": [{
                "mnemonic": "LDI",
                "operands": [{"name": "value", "size": 3}],
                "encoding": "1111 {value:4}",
            }],
        }

        with self.assertRaisesRegex(ISAError, "smaller than encoded width"):
            ISA.from_dict(definition)

    def test_rejects_non_object_instructions(self):
        with self.assertRaisesRegex(ISAError, "instructions must be an array"):
            ISA.from_dict({"isa": "X", "instructions": {}})

    def test_rejects_unsupported_schema_version(self):
        with self.assertRaisesRegex(ISAError, "schema_version must be 1"):
            ISA.from_dict({"isa": "X", "schema_version": 2, "instructions": []})

    def test_rejects_duplicate_register_codes(self):
        with self.assertRaisesRegex(ISAError, "duplicate register code"):
            ISA.from_dict({"isa": "X", "registers": {"A": 0, "B": 0}, "instructions": []})

    def test_rejects_duplicate_operand_names(self):
        definition = {
            "isa": "X",
            "instructions": [{
                "mnemonic": "MOV",
                "operands": [{"name": "reg"}, {"name": "reg"}],
                "encoding": "{reg:4} {reg:4}",
            }],
        }

        with self.assertRaisesRegex(ISAError, "duplicate operand name"):
            ISA.from_dict(definition)

    def test_allows_empty_selector_value(self):
        definition = {
            "isa": "X",
            "instructions": [{
                "mnemonic": "BZ",
                "operands": [{"name": "base", "type": "selector", "values": {"": 0}}],
                "encoding": "0000000 {base:1}",
            }],
        }

        self.assertEqual(ISA.from_dict(definition).find("BZ", 1).operands[0].values, {"": 0})

    def test_enforces_signed_and_scattered_field_ranges(self):
        instruction = {
            "mnemonic": "BR",
            "operands": [{"name": "offset", "signed": True}],
            "encoding": "1 {offset[7:4]} 000 {offset[3:0]} 0",
        }
        isa = ISA.from_dict({"isa": "X", "instructions": [instruction]})
        definition = isa.find("BR", 1)

        self.assertEqual(definition.encode({"offset": -1}), b"\x1f\x1e")
        with self.assertRaisesRegex(EncodingError, "outside the 8-bit range"):
            definition.encode({"offset": 128})

    def test_rejects_unsigned_negative_values(self):
        definition = ISA.from_dict({
            "isa": "X",
            "instructions": [{
                "mnemonic": "LDI",
                "operands": [{"name": "value"}],
                "encoding": "1111 {value:4}",
            }],
        }).find("LDI", 1)

        with self.assertRaisesRegex(EncodingError, "outside the 4-bit range"):
            definition.encode({"value": -1})

    def test_supports_non_byte_aligned_patterns(self):
        pattern = ISA.from_dict({
            "isa": "X",
            "instructions": [{"mnemonic": "BIT", "encoding": "101"}],
        }).find("BIT", 0).pattern

        self.assertEqual(pattern.width_bits, 3)
        self.assertEqual(pattern.width_bytes, 1)
        self.assertEqual(pattern.encode({}), b"\x05")
        self.assertTrue(pattern.matches(0b101))
        self.assertFalse(pattern.matches(0b1101))

    def test_encoding_index_does_not_expand_wide_fields(self):
        definition = {
            "isa": "RV32I-like",
            "word_size": 32,
            "instructions": [{
                "mnemonic": "ADDI",
                "operands": [
                    {"name": "imm", "signed": True},
                    {"name": "rs1", "type": "register"},
                    {"name": "rd", "type": "register"},
                ],
                "encoding": "{imm[11:0]} {rs1:5} 000 {rd:5} 0010011",
            }],
        }

        index = ISAEncodingIndex(ISA.from_dict(definition))

        self.assertEqual(len(index.entries), 1)
        self.assertEqual(index.search(0x00000013, bit_width=32)[0][0].mnemonic, "ADDI")

    def test_production_tree_expands_only_when_searched(self):
        tree = ISAProductionTree.from_dict(rv32i_test_spec())

        match = tree.reverse_search(0x00000013, bit_width=32)
        self.assertEqual(match[0][0].mnemonic, "ADDI")
        self.assertEqual(match[0][1]["imm"], 0)

    def test_rejects_duplicate_instruction_definitions(self):
        definition = {
            "isa": "X",
            "instructions": [
                {"mnemonic": "A", "operands": [{"name": "left"}], "encoding": "0000 {left:4}"},
                {"mnemonic": "A", "operands": [{"name": "left"}], "encoding": "0000 {left:4}"},
            ],
        }

        with self.assertRaisesRegex(ISAError, "duplicate instruction definition"):
            ISA.from_dict(definition)

    def test_accepts_disjoint_instruction_encodings(self):
        definition = {
            "isa": "X",
            "instructions": [
                {"mnemonic": "A", "encoding": "0000 0000"},
                {"mnemonic": "B", "encoding": "0000 0001"},
            ],
        }

        self.assertEqual(len(ISA.from_dict(definition).all_instructions()), 2)

    def test_instruction_documentation_fields(self):
        isa = ISA.from_dict({
            "isa": "X",
            "instructions": [{
                "mnemonic": "ADD",
                "encoding": "00000000",
                "description": "Add the selected value to the accumulator.",
                "operation": "A <- A + value",
            }],
        })

        instruction = isa.find("ADD", 0)
        self.assertEqual(instruction.description, "Add the selected value to the accumulator.")
        self.assertEqual(instruction.operation, "A <- A + value")

    def test_assembler_loads_relative_base_spec_and_extension(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "base.json").write_text(json.dumps({
                "isa": "MX/11-base",
                "registers": {"A": 0},
                "instructions": [{"mnemonic": "NOP", "encoding": "00000000"}],
            }))
            extension_path = directory / "extension.json"
            extension_path.write_text(json.dumps({
                "isa": "MX/11-domain",
                "base": "base.json",
                "instructions": [{"mnemonic": "EXT", "encoding": "00000001"}],
            }))

            assembler = Assembler(extension_path)
            output = assembler.assemble_object(".ins\nNOP\nEXT\n", packed=True)

        self.assertEqual(assembler.isa.name, "MX/11-domain")
        self.assertEqual(assembler.isa.instructions, ["NOP", "EXT"])
        self.assertEqual(bytes.fromhex(output["sections"][0]["data"]), b"\x00\x01")

    def test_rejects_circular_base_specs(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            first_path = directory / "first.json"
            second_path = directory / "second.json"
            first_path.write_text(json.dumps({"isa": "A", "base": "second.json", "instructions": []}))
            second_path.write_text(json.dumps({"isa": "B", "base": "first.json", "instructions": []}))

            with self.assertRaisesRegex(ISAError, "circular ISA base reference"):
                ISA.from_json(first_path)


if __name__ == "__main__":
    unittest.main()