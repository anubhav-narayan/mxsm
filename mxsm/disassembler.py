from typing import Any
from .production_tree import ProductionTree

class Disassembler:
    """
    Disassembler Class

    This class is responsible for the disassembly translation

    Usage:
        ```python
        asm = Disassembler(prod)
        asm.disassemble(code)
        ```

        Here `code` is the assembled code and `prod` is the raw production json 
    """
    def __init__(self, prod):
        def unpack_prod(sprod: str) -> dict:
            import json
            return json.loads(sprod)
        tab = unpack_prod(prod)
        self.prod = ProductionTree(tab['PROD'])
        self.ins_len = tab['INSTRUCTION_LENGTH']
        self.data_len = tab['DATA_LENGTH']
        self.dec = ''
        self.sdec = []

    def search_code(self, code: int) -> str:
        try:
            node = self.prod.search_code(code)
            node = node[0]
            depth = filter(lambda node: hasattr(node, 'idepth') and node.depth > 0, node.path)
            depth = next(depth).idepth
            ins = ' '.join([n.name for n in node.path][-depth:])
            self.sdec.append(ins)
            return f"0x{code:0{self.ins_len*2}X}\t; {ins}"
        except Exception:
            return f"0x{code:0{self.ins_len*2}X}\t; Not Found"


    def disassemble(self, code: bytes) -> str:
        disasm = []
        for i in range(0, len(code), self.ins_len):
            ins_code = int.from_bytes(code[i:i+self.ins_len], 'big')
            disasm .append(f"0x{i:0{self.data_len*2}X}:\t{self.search_code(ins_code)}")
        self.dec = '\n'.join(disasm)
        return self.dec

    @property
    def string_decoding(self):
        return '\n'.join(self.sdec) 