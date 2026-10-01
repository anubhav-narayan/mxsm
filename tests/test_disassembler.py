import unittest

from mxsm.disassembler import Disassembler


class DisassemblerTests(unittest.TestCase):
    def test_decodes_registers_and_selectors(self):
        disassembler = Disassembler('mx11su.json')

        self.assertEqual(
            disassembler.disassemble(b'\xa8\xc2'),
            '0x00:\t0xA8\t; BNZ INSP, A\n0x01:\t0xC2\t; ADD Y',
        )
        self.assertEqual(disassembler.string_decoding, 'BNZ INSP, A\nADD Y')

    def test_decodes_little_endian_split_signed_field(self):
        disassembler = Disassembler({
            'isa': 'RV32I-test',
            'word_size': 32,
            'address_width': 32,
            'data_width': 32,
            'endianness': 'little',
            'registers': {'x0': 0},
            'instructions': [{
                'mnemonic': 'BEQ',
                'operands': [
                    {'name': 'offset', 'signed': True},
                    {'name': 'rs1', 'type': 'register'},
                    {'name': 'rs2', 'type': 'register'},
                ],
                'encoding': '{offset[12:12]} {offset[10:5]} {rs2:5} {rs1:5} 000 {offset[4:1]} {offset[11:11]} 1100011',
            }],
        })

        disassembler.disassemble(b'\x63\x01\x00\x00')

        self.assertEqual(disassembler.string_decoding, 'BEQ 2, x0, x0')

    def test_handles_variable_instruction_sizes(self):
        disassembler = Disassembler({
            'isa': '6502-test',
            'address_width': 16,
            'data_width': 8,
            'endianness': 'big',
            'instructions': [
                {
                    'mnemonic': 'LDA',
                    'operands': [{'name': 'value'}],
                    'encoding': '10101001 {value:8}',
                },
                {'mnemonic': 'BRK', 'encoding': '00000000'},
            ],
        })

        disassembler.disassemble(b'\xa9\x2a\x00')

        self.assertEqual(disassembler.string_decoding, 'LDA 42\nBRK')


if __name__ == '__main__':
    unittest.main()