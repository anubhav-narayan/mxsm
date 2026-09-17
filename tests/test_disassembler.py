import unittest

from mxsm.disassembler import Disassembler


class DisassemblerTests(unittest.TestCase):
    def test_decodes_registers_and_selectors(self):
        disassembler = Disassembler('mx11su.json')

        self.assertEqual(
            disassembler.disassemble(b'\xa8\xc2'),
            '0x00:\t0xA8\t; BZ INSP, A\n0x01:\t0xC2\t; ADD Y',
        )
        self.assertEqual(disassembler.string_decoding, 'BZ INSP, A\nADD Y')

    def test_decodes_little_endian_split_signed_field(self):
        disassembler = Disassembler('rv32i.json')

        disassembler.disassemble(b'\x63\x01\x00\x00')

        self.assertEqual(disassembler.string_decoding, 'BEQ 2, x0, x0')

    def test_handles_variable_instruction_sizes(self):
        disassembler = Disassembler('mos6502.json')

        disassembler.disassemble(b'\xa9\x2a\x00')

        self.assertEqual(disassembler.string_decoding, 'LDA 42\nBRK')


if __name__ == '__main__':
    unittest.main()