from .tokenizer import TokenType, Token
from .tokenizer import Tokenizer


class Assembler:
    def __init__(self, code, prod):
        self.tokenizer = Tokenizer(code)
        self.tokens = {}
        self.mem_dict = {}
        self.ins_dict = {}
        self.symbol_table = {}
        def unpack_int(sprod):
            import binascii
            if isinstance(sprod, dict):
                return {int(key) if key.isdigit() else key: unpack_int(value) for key, value in sprod.items()}
            elif isinstance(sprod, str):
                try:
                    return binascii.unhexlify(sprod.encode('utf-8'))
                except binascii.Error:
                    return sprod
            else:
                return sprod
        def unpack_prod(sprod: str):
            import json
            return unpack_int(json.loads(sprod))
        try:
            self.prod = unpack_prod(prod)
        except Exception as e:
            raise e

    def process(self):
        data_flag = False
        mem_addr = 0
        ins_addr = 0
        self.tokens = self.tokenizer.tokenize()
        for line_number in sorted(self.tokens, key=int):
            tokens = self.tokens[line_number]
            for i in range(len(tokens)):
                if tokens[i].type == TokenType.DIRECTIVE:
                    if tokens[i].value == '.data':
                        data_flag = True
                    elif tokens[i].value == '.ins':
                        data_flag = False
                if (data_flag):
                    if (tokens[i].type == TokenType.LABEL):
                        self.symbol_table[tokens[i].value] = mem_addr
                    if (tokens[i].type == TokenType.DIRECTIVE):
                        if(tokens[i].value == '.byte'):
                            if (i + 1 < len(tokens)):
                                self.mem_dict[mem_addr] = tokens[i+1]
                            mem_addr += 1
                        if(tokens[i].value == '.res'):
                            if (i + 1 < len(tokens)):
                                for _ in range(mem_addr, mem_addr+int(tokens[i+1].value, 10)):
                                    self.mem_dict[mem_addr] = Token(TokenType.DEC_NUMBER, '0', tokens[i].line, tokens[i].column)
                                    mem_addr += 1
                else:
                    if (tokens[i].type == TokenType.LABEL):
                        self.symbol_table[tokens[i].value] = ins_addr
                    if (tokens[i].type == TokenType.INSTRUCTION):
                        self.ins_dict[ins_addr] = tokens[i:]
                        ins_addr += 1
                        continue

        return {
            "INS": self.ins_dict,
            "DATA": self.mem_dict,
            "SYMBOL": self.symbol_table
        }


    def assemble_data(self):
        data = b''
        for x in self.mem_dict:
            if self.mem_dict[x].type == TokenType.ADDRESS_LABEL:
                data += (self.symbol_table[self.mem_dict[x].value[1:]] & 0xFF).to_bytes()
            if self.mem_dict[x].type == TokenType.HEX_NUMBER:
                data += (int(self.mem_dict[x].value, 16) & 0xFF).to_bytes()
            if self.mem_dict[x].type == TokenType.BIN_NUMBER:
                data += (int(self.mem_dict[x].value, 2) & 0xFF).to_bytes()
            if self.mem_dict[x].type == TokenType.OCT_NUMBER:
                data += (int(self.mem_dict[x].value, 8) & 0xFF).to_bytes()
            if self.mem_dict[x].type == TokenType.DEC_NUMBER:
                data += (int(self.mem_dict[x].value, 10) & 0xFF).to_bytes()
        return data

    def assemble_ins(self):
        ins = b''
        for line in self.ins_dict:
            insl = self.ins_dict[line]
            for x in range(len(insl)):
                try:
                    if insl[x].type == TokenType.ADDRESS_LABEL:
                        insl[x] = Token(
                            TokenType['HEX_NUMBER'],
                            (self.symbol_table[insl[x].value[1:]] & 0x0F),
                            insl[x].line,
                            insl[x].column
                        )
                        continue
                    if insl[x].type == TokenType.HEX_NUMBER:
                        insl[x].value = int(insl[x].value, 16)
                        continue
                    if insl[x].type == TokenType.DEC_NUMBER:
                        insl[x].value = int(insl[x].value, 10)
                        continue
                    if insl[x].type == TokenType.OCT_NUMBER:
                        insl[x].value = int(insl[x].value, 8)
                        continue
                    if insl[x].type == TokenType.BIN_NUMBER:
                        insl[x].value = int(insl[x].value, 2)
                        continue
                except Exception as e:
                    raise SyntaxError(
                        f"{insl[x].line+1}: {self.tokenizer.code[insl[x].line]}\n"
                        + f"Label {insl[x].value[1:]} not defined."
                    )
            try:
                type_s = ','.join([x.type.name for x in insl])
                bmap = self.prod[type_s]
                _ins = bmap
                for i in range(0, bmap['depth']):
                    try:
                        _ins = _ins[insl[i].value]
                    except Exception as e:
                        raise SyntaxError(
                            f"{insl[i].line+1}: {self.tokenizer.code[insl[i].line]}"
                        )
                ins += _ins
            except Exception as e:
                raise e

        return ins

    def assemble(self):
        self.__store__ = {}
        self.__store__['debug'] = self.process()
        self.__store__['data'] = self.assemble_data()
        self.__store__['ins'] = self.assemble_ins()

    @property
    def ins(self):
        try:
            return self.__store__['ins']
        except:
            self.assemble()
            return self.__store__['ins']

    @property
    def data(self):
        try:
            return self.__store__['data']
        except:
            self.assemble()
            return self.__store__['data']

    @property
    def debug_info(self):
        try:
            return self.__store__['debug']
        except:
            self.assemble()
            return self.__store__['debug']