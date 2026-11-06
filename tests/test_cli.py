import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from mxsm.cli import main


class MifCliTests(unittest.TestCase):
    def test_bin2mif_subcommand_converts_binary_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.bin"
            output_path = Path(directory) / "output.mif"
            input_path.write_bytes(b"\x00\xAB\xFF")

            result = CliRunner().invoke(
                main,
                ["bin2mif", str(input_path), "-o", str(output_path)],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(
                output_path.read_text(),
                "WIDTH=8;\n"
                "DEPTH=3;\n"
                "\n"
                "ADDRESS_RADIX=HEX;\n"
                "DATA_RADIX=HEX;\n"
                "\n"
                "CONTENT BEGIN\n"
                "    00 : 00;\n"
                "    01 : AB;\n"
                "    02 : FF;\n"
                "END;\n",
            )

    def test_hex2mif_subcommand_accepts_whitespace_separated_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.hex"
            output_path = Path(directory) / "output.mif"
            input_path.write_text("00\nAB FF\n")

            result = CliRunner().invoke(
                main,
                ["hex2mif", str(input_path), "-o", str(output_path)],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("DEPTH=3;\n", output_path.read_text())
            self.assertTrue(output_path.read_text().endswith("    02 : FF;\nEND;\n"))

    def test_bin2mif_supports_wide_big_endian_words_and_zero_padding(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.bin"
            output_path = Path(directory) / "output.mif"
            input_path.write_bytes(b"\x01\x02\x03")

            result = CliRunner().invoke(
                main,
                ["bin2mif", str(input_path), "-o", str(output_path), "--width", "16"],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(
                output_path.read_text(),
                "WIDTH=16;\n"
                "DEPTH=2;\n"
                "\n"
                "ADDRESS_RADIX=HEX;\n"
                "DATA_RADIX=HEX;\n"
                "\n"
                "CONTENT BEGIN\n"
                "    00 : 0102;\n"
                "    01 : 0300;\n"
                "END;\n",
            )

    def test_hex2mif_supports_little_endian_words(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.hex"
            output_path = Path(directory) / "output.mif"
            input_path.write_text("01 02 03")

            result = CliRunner().invoke(
                main,
                [
                    "hex2mif", str(input_path), "-o", str(output_path),
                    "--width", "16", "--byte-order", "little",
                ],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("    00 : 0201;\n    01 : 0003;\n", output_path.read_text())

    def test_mif_width_must_be_byte_aligned(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.bin"
            output_path = Path(directory) / "output.mif"
            input_path.write_bytes(b"\x01")

            result = CliRunner().invoke(
                main,
                ["bin2mif", str(input_path), "-o", str(output_path), "--width", "12"],
            )

            self.assertEqual(result.exit_code, 2)
            self.assertIn("must be a multiple of 8 bits", result.output)

    def test_hex2mif_reports_invalid_hex_input(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.hex"
            output_path = Path(directory) / "output.mif"
            input_path.write_text("not hex")

            result = CliRunner().invoke(
                main,
                ["hex2mif", str(input_path), "-o", str(output_path)],
            )

            self.assertEqual(result.exit_code, 1)
            self.assertIn("invalid hexadecimal input", result.output)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
