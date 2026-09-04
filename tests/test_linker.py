import json
import tempfile
import unittest
from pathlib import Path

from mxsm.linker import LinkError, StaticLinker
from mxsm.object_format import pack_object
from mxsm.linker import executable_images


def object_file(*, isa="MX11", endianness="big"):
    return {
        "format": "mxsm-object",
        "version": 1,
        "isa": isa,
        "address_width": 8,
        "data_width": 8,
        "endianness": endianness,
        "sections": [
            {"name": "ins", "records": [{"address": 0, "data": "00"}]},
        ],
        "symbols": {},
        "relocations": [],
    }


class LinkerInputTests(unittest.TestCase):
    def test_adds_and_normalizes_json_object(self):
        linker = StaticLinker()
        result = linker.add_object(json.dumps(object_file()))

        self.assertEqual(result.name, "<json>")
        self.assertEqual(len(linker.objects), 1)
        self.assertEqual(linker.isa["isa"], "MX11")

    def test_accepts_packed_objects(self):
        linker = StaticLinker()
        linker.add_object({
            **object_file(),
            "format": "mxsm-packed",
            "sections": [{"name": "ins", "address": 0, "data": "00"}],
        })

        self.assertEqual(len(linker.objects), 1)

    def test_accepts_binary_mxo_objects(self):
        binary = pack_object({
            "format": "mxsm-packed",
            "version": 1,
            "isa": "MX11",
            "address_width": 8,
            "data_width": 8,
            "endianness": "big",
            "sections": [{"name": "ins", "address": 0, "data": "00"}],
            "symbols": {},
            "relocations": [],
        })

        linker = StaticLinker()
        result = linker.add_object(binary)

        self.assertEqual(result.definition["sections"][0]["data"], "00")
        self.assertEqual(result.definition["format"], "mxsm-packed")

    def test_rejects_incompatible_isa_metadata(self):
        linker = StaticLinker()
        linker.add_object(object_file())

        with self.assertRaisesRegex(LinkError, "incompatible"):
            linker.add_object(object_file(endianness="little"))

    def test_rejects_malformed_section_data(self):
        malformed = object_file()
        malformed["sections"][0]["records"][0]["data"] = "not-hex"

        with self.assertRaisesRegex(LinkError, "invalid record data"):
            StaticLinker().add_object(malformed)

    def test_does_not_claim_linking_is_implemented(self):
        linked = StaticLinker()
        linked.add_object(object_file())
        self.assertEqual(linked.link()["format"], "mxsm-executable")

    def test_resolves_and_applies_data_relocation(self):
        source = object_file()
        source["sections"] = [
            {"name": "data", "records": [{"address": 0, "data": "00"}]},
            {"name": "ins", "records": [{"address": 0, "data": "00"}]},
        ]
        source["symbols"] = {"start": {"section": "ins", "offset": 0}}
        source["relocations"] = [{
            "section": "data",
            "offset": 0,
            "symbol": "start",
            "type": "absolute",
            "width": 8,
        }]
        linker = StaticLinker()
        linker.add_object(source)

        linked = linker.link(entry="start")

        self.assertEqual(linked["entry"], 0)
        data = next(section for section in linked["sections"] if section["name"] == "data")
        self.assertEqual(data["data"], "00")

    def test_emits_mxe_executable(self):
        linker = StaticLinker()
        linker.add_object(object_file())

        image = linker.emit_executable()

        self.assertEqual(image[:4], b"MXE\0")
        self.assertGreater(len(image), 20)

    def test_extracts_raw_images_from_mxe(self):
        linker = StaticLinker()
        source = object_file()
        source["sections"] = [
            {"name": "ins", "records": [{"address": 0, "data": "00"}]},
            {"name": "nmi", "records": [{"address": 128, "data": "fe"}]},
            {"name": "irq", "records": [{"address": 192, "data": "fd"}]},
        ]
        linker.add_object(source)
        image = linker.emit_executable()
        images = executable_images(image)
        self.assertEqual(images["ins"][0], 0)
        self.assertEqual(images["ins"][128], 0xfe)
        self.assertEqual(images["ins"][192], 0xfd)
        self.assertEqual(len(images["ins"]), 256)

    def test_emit_images_includes_interrupt_vectors(self):
        source = object_file()
        source["sections"] = [
            {"name": "nmi", "records": [{"address": 128, "data": "fe"}]},
            {"name": "irq", "records": [{"address": 192, "data": "fd"}]},
        ]
        linker = StaticLinker()
        linker.add_object(source)
        images = linker.emit_images()
        self.assertEqual(images["ins"][128], 0xfe)
        self.assertEqual(images["ins"][192], 0xfd)

    def test_layout_concatenates_relocatable_sections(self):
        linker = StaticLinker()
        linker.add_object(object_file())
        linker.add_object(object_file())

        sections = linker.layout_sections()

        self.assertEqual(sections["ins"].address, 0)
        self.assertEqual(sections["ins"].data, b"\x00\x00")

    def test_layout_preserves_interrupt_vector_addresses(self):
        linker = StaticLinker({
            "isa": "MX11",
            "address_width": 8,
            "data_width": 8,
            "endianness": "big",
            "nmi_vector": 128,
            "irq_vector": 192,
        })
        first = object_file()
        first["sections"] = [{"name": "nmi", "records": [{"address": 128, "data": "00"}]}]
        linker.add_object(first)

        sections = linker.layout_sections()

        self.assertEqual(sections["nmi"].address, 128)
        self.assertEqual(sections["nmi"].data, b"\x00")

    def test_link_cli_writes_layout(self):
        from click.testing import CliRunner
        from mxsm.cli import link_main

        with tempfile.TemporaryDirectory() as directory:
            object_path = Path(directory) / "main.mxp"
            output_path = Path(directory) / "linked.mxp"
            object_path.write_text(json.dumps(object_file()))
            result = CliRunner().invoke(
                link_main,
                ["-o", str(output_path), str(object_path)],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(json.loads(output_path.read_text())["format"], "mxsm-linked")

    def test_link_cli_writes_executable(self):
        from click.testing import CliRunner
        from mxsm.cli import link_main

        with tempfile.TemporaryDirectory() as directory:
            object_path = Path(directory) / "main.mxp"
            output_path = Path(directory) / "program.mxe"
            object_path.write_text(json.dumps(object_file()))
            result = CliRunner().invoke(
                link_main,
                [
                    "--format", "executable",
                    "-o", str(output_path),
                    str(object_path),
                ],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(output_path.read_bytes()[:4], b"MXE\0")


if __name__ == "__main__":
    unittest.main()
