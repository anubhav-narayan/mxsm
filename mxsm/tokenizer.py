import re
from enum import Enum, auto

class TokenType(Enum):
    INSTRUCTION = auto()
    REGISTER = auto()
    HEX_NUMBER = auto()
    OCT_NUMBER = auto()
    BIN_NUMBER = auto()
    DEC_NUMBER = auto()
    LABEL = auto()
    STRING = auto()
    DIRECTIVE = auto()
    ADDRESS_LABEL = auto()
    ADDRESS_HEX_NUMBER = auto()
    ADDRESS_OCT_NUMBER = auto()
    ADDRESS_BIN_NUMBER = auto()
    ADDRESS_DEC_NUMBER = auto()
    COMMENT = auto()
    WHITESPACE = auto()

class Token:

    def __init__(self, type_, value, line, column):
        self.type = type_
        self.value = value
        self.line = line
        self.column = column

    def __repr__(self):
        return f'Token(type={self.type}, value={self.value}, line={self.line}, column={self.column})'


class Tokenizer:
    def __init__(self, code, insr_list, reg_list):
        self.code = code.splitlines()
        self.tokens = {}
        self.INSR_LIST = insr_list
        self.REG_LIST = reg_list
        self.token_specification = [
            (TokenType.INSTRUCTION, rf'\b(?:{"|".join(self.INSR_LIST)})'),
            (TokenType.REGISTER, rf'{"|".join(self.REG_LIST)}\b'),
            (TokenType.HEX_NUMBER, r'\b0[xX][0-9a-fA-F]+\b'),
            (TokenType.OCT_NUMBER, r'\b0[oO]?[0-7]+\b'),
            (TokenType.BIN_NUMBER, r'\b0[bB][01]+\b'),
            (TokenType.DEC_NUMBER, r'\b\d+\b'),
            (TokenType.LABEL, r'^(?:(?!\:)[A-Za-z_][A-Za-z0-9_]*)+'),
            (TokenType.DIRECTIVE, r'\.[A-Za-z_][A-Za-z0-9_]*\b'),
            (TokenType.ADDRESS_LABEL, r'&[A-Za-z_][A-Za-z0-9_]*\b'),
            (TokenType.ADDRESS_HEX_NUMBER, r'&0[xX][0-9a-fA-F]+\b'),
            (TokenType.ADDRESS_OCT_NUMBER, r'&0[oO]?[0-7]+\b'),
            (TokenType.ADDRESS_BIN_NUMBER, r'&0[bB][01]+\b'),
            (TokenType.ADDRESS_DEC_NUMBER, r'&\d+\b'),
            (TokenType.STRING, r'"([^"\\]|\\.)*"'),
            (TokenType.COMMENT, r';.*'),
            (TokenType.WHITESPACE, r'[ \t\n]+')
        ]

        self.token_re = '|'.join(f'(?P<{pair[0].name}>{pair[1]})' for pair in self.token_specification)

    def tokenize(self):
        for line in range(len(self.code)):
            self.tokens[line] = self.tokenize_line(self.code[line], line)
        return self.tokens

    def tokenize_line(self, line, line_number):
        tokens = []
        for match in re.finditer(self.token_re, line):
            type_name = match.lastgroup
            value = match.group(type_name)
            start_pos = match.start()
            column = start_pos + 1  # Adjusting to 1-based column index

            if type_name in [TokenType.WHITESPACE.name, TokenType.COMMENT.name]:
                continue

            token = Token(TokenType[type_name], value, line_number, column)
            tokens.append(token)

        return tokens
