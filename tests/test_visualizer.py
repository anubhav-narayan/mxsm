import unittest

from mxsm import ISA, ISAVisualizer


class ISAVisualizerTests(unittest.TestCase):
    def test_renders_structured_instruction_groups_and_registers(self):
        isa = ISA.from_dict({
            "isa": "MX-test",
            "registers": {"A": 0},
            "control_set": {
                "name": "Control/System",
                "instructions": [{
                    "mnemonic": "DSEL",
                    "encoding": "11110000",
                    "operation": "DAR <- A",
                }],
            },
            "domains": [{
                "dar": 1,
                "name": "Device",
                "context_registers": {"RX": 0},
                "instructions": [{
                    "mnemonic": "LOAD",
                    "encoding": "10 {reg:2}",
                    "operands": [{
                        "name": "reg",
                        "type": "context_register",
                    }],
                    "aliases": [{"operands": ["RECEIVE"], "values": {"reg": "RX"}}],
                    "description": "Load a register.",
                }],
            }],
        })

        diagram = ISAVisualizer(isa).to_mermaid()

        self.assertIn("ISA: MX-test", diagram)
        self.assertIn("A = 0", diagram)
        self.assertIn("Control/System", diagram)
        self.assertIn("DAR 1: Device", diagram)
        self.assertIn("Domain context (metadata): RX = 0", diagram)
        self.assertIn("LOAD<br/>10 {reg:2}<br/>4 bits", diagram)
        self.assertIn("reg: context_register (2 bits) [RX=0]", diagram)
        self.assertIn("Description: Load a register.", diagram)
        self.assertIn("Aliases: RECEIVE", diagram)
        self.assertIn("Effect: DAR &lt;- A", diagram)

    def test_renders_ascii_tree_with_context_register_type(self):
        visualizer = ISAVisualizer({
            "isa": "MX-test",
            "registers": {"A": 0},
            "control_set": {"name": "Control/System", "instructions": []},
            "domains": [{
                "dar": 1,
                "name": "Device",
                "context_registers": {"RX": 0},
                "instructions": [{
                    "mnemonic": "LOAD",
                    "encoding": "10 {local:2}",
                    "operands": [{"name": "local", "type": "context_register"}],
                }],
            }],
        })

        tree = visualizer.to_ascii_tree()

        self.assertEqual(tree, visualizer.to_ascii())
        self.assertTrue(tree.isascii())
        self.assertIn("MX-test (address=8, data=8, endianness=big)", tree)
        self.assertIn("|-- Assembler registers", tree)
        self.assertIn("|-- Control/System", tree)
        self.assertIn("DAR 1: Device", tree)
        self.assertIn("Context registers (domain metadata)", tree)
        self.assertIn("Operand: local [context_register, 2 bits] {RX=0}", tree)
        self.assertNotIn("  \n", tree)

    def test_renders_legacy_spec_and_markdown_wrapper(self):
        visualizer = ISAVisualizer({
            "isa": "Simple8",
            "instructions": [{"mnemonic": "NOP", "encoding": "00000000"}],
        })

        diagram = visualizer.to_mermaid()

        self.assertIn('subgraph instructions["Instructions"]', diagram)
        self.assertIn("NOP<br/>00000000<br/>8 bits", diagram)
        self.assertEqual(
            visualizer.to_markdown(),
            f"```mermaid\n{diagram}\n```",
        )

    def test_escapes_isa_metadata_in_mermaid_labels(self):
        diagram = ISAVisualizer({
            "isa": 'MX "quoted"',
            "instructions": [{
                "mnemonic": "INFO",
                "encoding": "00000000",
                "description": 'A < B & "C"',
            }],
        }).to_mermaid()

        self.assertIn("ISA: MX &quot;quoted&quot;", diagram)
        self.assertIn("Address width: 8 bits", diagram)
        self.assertIn("Description: A &lt; B &amp; &quot;C&quot;", diagram)


if __name__ == "__main__":
    unittest.main()
