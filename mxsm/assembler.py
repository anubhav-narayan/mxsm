from typing import Any
from .tokenizer import TokenType, Token
from .tokenizer import Tokenizer
from .production_tree import ProductionTree


class Assembler:
    """
    Assembler Class

    This class is responsible for the assembly translation

    Usage:
        ```python
        asm = Assembler(prod)
        asm.assemble(code)
        ```

        Here `code` is the assembly code and `prod` is the raw production json 
    """
    def __init__(self, prod):
        self.tokens = {}
        self.mem_dict = {}
        self.ins_dict = {}
        self.symbol_table = {}
        def unpack_prod(sprod: str) -> dict:
            import json
            return json.loads(sprod)
        try:
            tab = unpack_prod(prod)
            self.prod = ProductionTree(tab['PROD'])
            self.tokenizer = Tokenizer(tab['INS'], tab['REGS'])
            self.nmi_addr = tab['NMI_ADDR']
            self.irq_addr = tab['IRQ_ADDR']
            self.ins_len = tab['INSTRUCTION_LENGTH']
            self.data_len = tab['DATA_LENGTH']
            # Internal DS
            self.code = ''
            self.ins = b''
            self.data = b''
            self.section_regions = [
                ("data", 0x00),
                ("ins", 0x00),
                ("nmi", self.nmi_addr),
                ("irq", self.irq_addr)
            ]
            self.section_labels = [i[0] for i in self.section_regions]
            self.tokens = {}
            self.symbol_table = {}
            self.mem_dict = {}
            self.ins_dict = {}
            self.sections = {keys:{} for keys in self.section_labels}
        except Exception as e:
            raise e

    def tokenize(self, code) -> dict:
        self.code = code
        self.tokens = self.tokenizer.tokenize(code)
        return self.tokens

    def split_sections(self) -> dict:
        """
        Split into sections
        """
        current_section = "ins"
        for line_number in sorted(self.tokens, key=int):
            if len(self.tokens[line_number]) > 0:
                if self.tokens[line_number][0].type is TokenType.DIRECTIVE and self.tokens[line_number][0].value[1:] in self.section_labels:
                    current_section = self.tokens[line_number][0].value[1:]
                else:
                    self.sections[current_section][line_number] = self.tokens[line_number]
        return self.sections

    def generate_section_ir(self, section, base_address) -> None:
        section = self.sections[section]
        for line_number in sorted(section, key=int):
            tokens = section[line_number]
            for i in range(len(tokens)):
                if tokens[i].type == TokenType.LABEL:
                    self.symbol_table[tokens[i].value] = str(base_address)
                if (tokens[i].type == TokenType.DIRECTIVE):
                    if(tokens[i].value == '.byte'):
                        if (len(tokens) > 1):
                            for token in tokens[1:]:
                                if token.type == TokenType.NUMBER:
                                    self.mem_dict[base_address] = token
                                    base_address += 1
                                    continue
                                if token.type == TokenType.STRING:
                                    for x in token.value.strip('"'):
                                        self.mem_dict[base_address] = Token(TokenType.NUMBER , str(ord(x)), token.line, token.column)
                                        base_address += 1
                                    continue
                                if token.type == TokenType.ADDRESS_LABEL:
                                    self.mem_dict[base_address] = token
                                    base_address += 1
                                    continue
                    if(tokens[i].value == '.res'):
                        if (i + 1 < len(tokens)):
                            for _ in range(base_address, base_address+int(tokens[i+1].value, 0)):
                                self.mem_dict[base_address] = Token(TokenType.NUMBER, '0', tokens[i].line, tokens[i].column)
                                base_address += 1
                if (tokens[i].type == TokenType.INSTRUCTION):
                    self.ins_dict[base_address] = tokens[i:]
                    base_address += 1
                    continue

    def generate_ir(self) -> dict:
        for x in self.section_regions:
            self.generate_section_ir(*x)

        return {
            "ins": self.ins_dict,
            "data": self.mem_dict,
            "symbol": self.symbol_table
        }

    def ir_pass(self, code) -> dict:
        self.tokenize(code)
        self.split_sections()
        return self.generate_ir()

    def assemble_data(self) -> bytes:
        """
        Process the data dictionary to bytes

        Returns:
            bytes: Byte code for memory
        """
        self.data = b''
        mask = (2**(self.data_len * 8)) - 1
        for x in self.mem_dict:
            if self.mem_dict[x].type == TokenType.ADDRESS_LABEL:
                self.data += (int(self.symbol_table[self.mem_dict[x].value[1:]], 0) & mask).to_bytes(self.data_len, 'big')
            if self.mem_dict[x].type == TokenType.NUMBER:
                self.data += (int(self.mem_dict[x].value, 0) & mask).to_bytes(self.data_len, 'big')
        return self.data

    def assemble_ins(self) -> bytes:
        """
        Process the instruction dictionary to bytes

        Returns:
            bytes: Byte code for instructions

        Raises:
            SyntaxError: for unrecognised operations and labels
        """
        self.ins = [b'\x00' * self.ins_len] * 2**(self.data_len * 8)
        mask = (2**(self.ins_len * 8)) - 1
        for line in self.ins_dict:
            insl = self.ins_dict[line]
            for x in range(len(insl)):
                try:
                    if insl[x].type == TokenType.ADDRESS_LABEL:
                        insl[x] = Token(
                            TokenType.NUMBER,
                            str(int(self.symbol_table[self.mem_dict[x].value[1:]], 0) & mask),
                            insl[x].line,
                            insl[x].column
                        )
                        continue
                    if insl[x].type == TokenType.NUMBER:
                        insl[x].value = str(int(insl[x].value, 0) & mask)
                        continue
                except Exception as e:
                    raise SyntaxError(
                        f"{insl[x].line+1}: {self.code[insl[x].line]}\n"
                        + f"Label {insl[x].value[1:]} not defined."
                    )
            try:
                type_s = ','.join([x.type.name for x in insl])
                fmt = '/'.join([x.value for x in insl])
                try:
                    _ins = self.prod.get_production(type_s)
                except Exception as e:
                    raise SyntaxError(
                        f"\"{insl[0].line+1}: {self.code[insl[0].line]}\" is an invalid production\n"
                    )
                try:
                    _ins = _ins.search_path(fmt).value
                except Exception as e:
                    raise SyntaxError(
                        f"\"{insl[i].line+1}: {self.code[insl[i].line]}\" is not a recognised operation"
                    )
                self.ins[line] = _ins.to_bytes(self.ins_len, 'big')
            except Exception as e:
                raise e
        
        self.ins = b''.join(self.ins)
        return self.ins

    def mr_pass(self) -> dict:
        self.assemble_ins()
        self.assemble_data()
        return {
            'ins': self.ins,
            'data': self.data
        }

    def assemble(self, code) -> dict:
        """
        Macro fuction for `ir_pass()` `mr_pass()`

        Stores results in internal storage
        """
        self.ir_pass(code)
        return self.mr_pass()

    @property
    def debug_info(self) -> dict:
        """

        Returns:
            dict: Debug information
        """
        return self.sections
