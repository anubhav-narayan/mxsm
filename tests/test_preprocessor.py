import unittest

from mxsm.preprocessor import MacroError, MacroProcessor


class MacroProcessorTests(unittest.TestCase):
    def test_expands_positional_and_named_arguments(self):
        source = ".macro MOVE dst, src\nMOV \\dst, \\src\n.endmacro\nMOVE A, src=X\n"

        lines = MacroProcessor().process(source)

        self.assertEqual([line.text for line in lines], ["MOV A, X"])

    def test_allows_forward_macro_invocation(self):
        source = "HELLO\n.macro HELLO\nNOP\n.endmacro\n"

        self.assertEqual([line.text for line in MacroProcessor().process(source)], ["NOP"])

    def test_expands_nested_macros(self):
        source = ".macro INNER\nNOP\n.endmacro\n.macro OUTER\nINNER\n.endmacro\nOUTER\n"

        self.assertEqual([line.text for line in MacroProcessor().process(source)], ["NOP"])

    def test_rewrites_local_labels_per_expansion(self):
        source = ".macro LOOP\n%%again:\nJNZ %%again\n.endmacro\nLOOP\nLOOP\n"

        lines = [line.text for line in MacroProcessor().process(source)]

        self.assertEqual(lines, ["__LOOP_1_again:", "JNZ __LOOP_1_again", "__LOOP_2_again:", "JNZ __LOOP_2_again"])

    def test_rejects_recursive_expansion(self):
        source = ".macro LOOP\nLOOP\n.endmacro\nLOOP\n"

        with self.assertRaisesRegex(MacroError, "recursive macro expansion"):
            MacroProcessor().process(source)

    def test_preserves_semicolons_in_strings(self):
        source = ".macro MESSAGE text\n.byte \\text\n.endmacro\nMESSAGE \"a;b\"\n"

        self.assertEqual([line.text for line in MacroProcessor().process(source)], ['.byte "a;b"'])


if __name__ == "__main__":
    unittest.main()