"""Mermaid visualizations for validated ISA specifications."""
from __future__ import annotations

from html import escape
from pathlib import Path

from .schema import ISA, InstructionDef


class ISAVisualizer:
    """Render an ISA specification as a Mermaid flowchart or ASCII tree."""

    def __init__(self, isa_source: ISA | dict | str | Path):
        self.isa = isa_source if isinstance(isa_source, ISA) else ISA.from_json(isa_source)

    @staticmethod
    def _label(value: str) -> str:
        return escape(value, quote=True).replace("\n", "<br/>")

    @staticmethod
    def _tree_text(value: object) -> str:
        text = " ".join(str(value).split())
        return text.encode("ascii", "backslashreplace").decode("ascii")

    def _tree_instruction_details(self, instruction: InstructionDef) -> list[str]:
        details = [
            f"Encoding: {instruction.encoding} ({instruction.pattern.width_bits} bits)"
        ]
        for operand in instruction.operands:
            description = (
                f"Operand: {operand.name} [{operand.type}, "
                f"{instruction.pattern.field_widths[operand.name]} bits]"
            )
            values = self.isa.values_for(operand, instruction)
            if values:
                options = ", ".join(f"{name}={value}" for name, value in values.items())
                description += f" {{{options}}}"
            details.append(description)
        if instruction.description:
            details.append(f"Description: {instruction.description}")
        if instruction.operation:
            details.append(f"Effect: {instruction.operation}")
        for alias in instruction.aliases:
            details.append(f"Alias: {', '.join(alias.get('operands', []))}")
        return [self._tree_text(detail) for detail in details]

    @staticmethod
    def _append_tree(
        lines: list[str], prefix: str, label: str, children: list[tuple[str, list]]
    ) -> None:
        if label:
            lines.append(f"{prefix}{label}")
        for index, (child_label, descendants) in enumerate(children):
            last_child = index == len(children) - 1
            branch = "`-- " if last_child else "|-- "
            child_prefix = "    " if last_child else "|   "
            lines.append(f"{prefix}{branch}{child_label}")
            ISAVisualizer._append_tree(lines, prefix + child_prefix, "", descendants)

    def to_ascii_tree(self) -> str:
        """Return a plain-ASCII tree of ISA settings, register maps, and forms."""
        isa_label = self._tree_text(
            f"{self.isa.name} "
            f"(address={self.isa.address_width}, data={self.isa.data_width}, "
            f"endianness={self.isa.endianness})"
        )
        children: list[tuple[str, list]] = []

        registers = self.isa.spec.get("registers", {})
        if registers:
            register_children = [
                (self._tree_text(f"{name} = {code}"), [])
                for name, code in registers.items()
            ]
            children.append(("Assembler registers", register_children))

        groups: list[tuple[str, list[InstructionDef], dict[str, int]]] = []
        if self.isa.control_set_name is not None:
            groups.append((
                self.isa.control_set_name,
                self.isa.control_instructions,
                {},
            ))
            for dar, name in self.isa.domain_names.items():
                groups.append((
                    f"DAR {dar}: {name}",
                    self.isa.domain_instructions.get(dar, []),
                    self.isa.domain_context_register_codes.get(dar, {}),
                ))
        else:
            groups.append(("Instructions", self.isa.all_instructions(), {}))

        for group_name, instructions, context_registers in groups:
            group_children: list[tuple[str, list]] = []
            if context_registers:
                context_children = [
                    (self._tree_text(f"{name} = {code}"), [])
                    for name, code in context_registers.items()
                ]
                group_children.append(("Context registers (domain metadata)", context_children))
            for instruction in instructions:
                details = self._tree_instruction_details(instruction)
                group_children.append((self._tree_text(instruction.mnemonic), [(detail, []) for detail in details]))
            if not group_children:
                group_children.append(("No instructions", []))
            children.append((self._tree_text(group_name), group_children))

        lines: list[str] = []
        self._append_tree(lines, "", isa_label, children)
        return "\n".join(lines)

    def to_ascii(self) -> str:
        """Alias for :meth:`to_ascii_tree`."""
        return self.to_ascii_tree()

    def _instruction_label(self, instruction: InstructionDef) -> str:
        parts = [
            instruction.mnemonic,
            instruction.encoding,
            f"{instruction.pattern.width_bits} bits",
        ]
        if instruction.operands:
            operand_descriptions = []
            for operand in instruction.operands:
                description = (
                    f"{operand.name}: {operand.type} "
                    f"({instruction.pattern.field_widths[operand.name]} bits)"
                )
                operand_values = self.isa.values_for(operand, instruction)
                if operand_values:
                    values_label = ", ".join(
                        f"{name}={value}" for name, value in operand_values.items()
                    )
                    description += f" [{values_label}]"
                operand_descriptions.append(description)
            parts.append("Operands: " + ", ".join(operand_descriptions))
        if instruction.description:
            parts.append(f"Description: {instruction.description}")
        if instruction.operation:
            parts.append(f"Effect: {instruction.operation}")
        if instruction.aliases:
            aliases = [
                ", ".join(str(operand) for operand in alias.get("operands", []))
                for alias in instruction.aliases
            ]
            parts.append("Aliases: " + "; ".join(aliases))
        return self._label("\n".join(parts))

    def to_mermaid(self) -> str:
        """Return a Mermaid flowchart showing registers and instruction groups."""
        isa_label = "\n".join([
            f"ISA: {self.isa.name}",
            f"Address width: {self.isa.address_width} bits",
            f"Data width: {self.isa.data_width} bits",
            f"Endianness: {self.isa.endianness}",
        ])
        lines = ["flowchart LR", f'  isa["{self._label(isa_label)}"]']

        registers = self.isa.spec.get("registers", {})
        if registers:
            lines.extend([
                '  subgraph assembler_registers["Assembler registers"]',
                "    direction TB",
            ])
            for index, (name, code) in enumerate(registers.items()):
                register_label = self._label(f"{name} = {code}")
                lines.append(f'    register_{index}["{register_label}"]')
            lines.extend(["  end", "  isa --> assembler_registers"])

        groups: list[tuple[str, str, list[InstructionDef], dict[str, int]]] = []
        if self.isa.control_set_name is not None:
            groups.append((
                "control",
                self.isa.control_set_name,
                self.isa.control_instructions,
                {},
            ))
            for dar, name in self.isa.domain_names.items():
                groups.append((
                    f"domain_{dar}",
                    f"DAR {dar}: {name}",
                    self.isa.domain_instructions.get(dar, []),
                    self.isa.domain_context_register_codes.get(dar, {}),
                ))
        else:
            groups.append(("instructions", "Instructions", self.isa.all_instructions(), {}))

        instruction_index = 0
        for group_id, group_name, instructions, context_registers in groups:
            lines.extend([
                f'  subgraph {group_id}["{self._label(group_name)}"]',
                "    direction TB",
            ])
            if context_registers:
                context_label = ", ".join(
                    f"{name} = {code}" for name, code in context_registers.items()
                )
                lines.append(
                    f'    {group_id}_context["Domain context (metadata): '
                    f'{self._label(context_label)}"]'
                )
            if instructions:
                for instruction in instructions:
                    lines.append(
                        f'    instruction_{instruction_index}["'
                        f'{self._instruction_label(instruction)}"]'
                    )
                    instruction_index += 1
            else:
                lines.append(f'    {group_id}_empty["No instructions"]')
            lines.extend(["  end", f"  isa --> {group_id}"])

        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Return the visualization inside a Markdown Mermaid code fence."""
        return f"```mermaid\n{self.to_mermaid()}\n```"
