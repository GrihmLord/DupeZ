#!/usr/bin/env python3
"""
GPC Script Parser — tokenize and parse CronusZEN/MAX .gpc files.

GPC is a C-like scripting language used by Cronus devices.  Key constructs:
  - #define / #include / #pragma
  - int, data types (no float)
  - main { ... }  — runs every ~10ms
  - combo name { ... }  — macro sequences with wait()
  - function name() { ... }
  - if / else / while / for
  - Built-in functions: get_val(), set_val(), combo_run(), combo_stop(),
    wait(), event_press(), event_release(), get_ptime(), etc.
  - Controller constants: XB1_A, XB1_B, PS4_CROSS, etc.

This parser extracts:
  1. Metadata (defines, variables)
  2. Combo blocks (name, steps with timing)
  3. Main logic flow
  4. Enough structure to modify timing values for DupeZ sync
"""

import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from app.logs.logger import log_info, log_error


# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------
class TokenType:
    PREPROCESSOR = "PREPROCESSOR"   # #define, #include, #pragma
    KEYWORD      = "KEYWORD"        # main, combo, function, if, else, while, for, int, data
    IDENTIFIER   = "IDENTIFIER"     # variable/function/combo names
    NUMBER       = "NUMBER"         # integer literals
    STRING       = "STRING"         # "string literals"
    OPERATOR     = "OPERATOR"       # = == != < > <= >= + - * / % & | ^ ! && ||
    LBRACE       = "LBRACE"         # {
    RBRACE       = "RBRACE"         # }
    LPAREN       = "LPAREN"        # (
    RPAREN       = "RPAREN"        # )
    LBRACKET     = "LBRACKET"       # [
    RBRACKET     = "RBRACKET"       # ]
    SEMICOLON    = "SEMICOLON"      # ;
    COMMA        = "COMMA"          # ,
    COMMENT      = "COMMENT"        # // or /* */
    EOF          = "EOF"


@dataclass
class Token:
    type: str
    value: str
    line: int
    col: int


# ---------------------------------------------------------------------------
# Parsed structures
# ---------------------------------------------------------------------------
@dataclass
class GPCDefine:
    name: str
    value: str
    line: int


@dataclass
class GPCVariable:
    type: str    # "int" or "data"
    name: str
    initial_value: Optional[str] = None
    is_array: bool = False
    array_size: Optional[int] = None
    line: int = 0


@dataclass
class GPCComboStep:
    """A single step inside a combo block."""
    function: str          # set_val, wait, etc.
    args: List[str] = field(default_factory=list)
    raw: str = ""


@dataclass
class GPCCombo:
    name: str
    steps: List[GPCComboStep] = field(default_factory=list)
    line: int = 0

    @property
    def total_wait_ms(self) -> int:
        """Sum of all wait() calls in this combo."""
        total = 0
        for step in self.steps:
            if step.function == "wait" and step.args:
                try:
                    total += int(step.args[0])
                except (ValueError, IndexError):
                    pass
        return total


@dataclass
class GPCScript:
    """Full parsed representation of a .gpc file."""
    source: str = ""
    defines: List[GPCDefine] = field(default_factory=list)
    variables: List[GPCVariable] = field(default_factory=list)
    combos: List[GPCCombo] = field(default_factory=list)
    main_body: str = ""
    functions: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def define_map(self) -> Dict[str, str]:
        return {d.name: d.value for d in self.defines}

    def get_combo(self, name: str) -> Optional[GPCCombo]:
        for c in self.combos:
            if c.name == name:
                return c
        return None


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------
KEYWORDS = {
    "main", "combo", "function", "if", "else", "while", "for",
    "int", "data", "return", "break", "continue",
}

# Regex patterns for tokenizing (order matters)
TOKEN_PATTERNS = [
    (TokenType.COMMENT,      r'//[^\n]*'),
    (TokenType.COMMENT,      r'/\*[\s\S]*?\*/'),
    (TokenType.PREPROCESSOR, r'#\w+[^\n]*'),
    (TokenType.STRING,       r'"[^"]*"'),
    (TokenType.NUMBER,       r'\b\d+\b'),
    (TokenType.OPERATOR,     r'&&|\|\||==|!=|<=|>=|<<|>>|[+\-*/%=<>!&|^~]'),
    (TokenType.LBRACE,       r'\{'),
    (TokenType.RBRACE,       r'\}'),
    (TokenType.LPAREN,       r'\('),
    (TokenType.RPAREN,       r'\)'),
    (TokenType.LBRACKET,     r'\['),
    (TokenType.RBRACKET,     r'\]'),
    (TokenType.SEMICOLON,    r';'),
    (TokenType.COMMA,        r','),
    (TokenType.IDENTIFIER,   r'[A-Za-z_]\w*'),
]


def tokenize(source: str) -> List[Token]:
    """Tokenize GPC source code into a list of tokens."""
    tokens = []
    pos = 0
    line = 1
    line_start = 0

    master_pattern = '|'.join(
        f'(?P<T{i}>{pat})' for i, (_, pat) in enumerate(TOKEN_PATTERNS)
    )
    # Add whitespace skip
    master_pattern = f'(?P<WS>\\s+)|{master_pattern}'

    for m in re.finditer(master_pattern, source):
        if m.group('WS'):
            # Track line numbers
            newlines = m.group('WS').count('\n')
            if newlines:
                line += newlines
                line_start = m.end()
            continue

        for i, (ttype, _) in enumerate(TOKEN_PATTERNS):
            g = m.group(f'T{i}')
            if g is not None:
                col = m.start() - line_start + 1
                # Skip comments
                if ttype == TokenType.COMMENT:
                    newlines = g.count('\n')
                    if newlines:
                        line += newlines
                    break

                # Reclassify identifiers that are keywords
                if ttype == TokenType.IDENTIFIER and g in KEYWORDS:
                    ttype = TokenType.KEYWORD

                tokens.append(Token(type=ttype, value=g, line=line, col=col))
                break

    tokens.append(Token(type=TokenType.EOF, value="", line=line, col=0))
    return tokens


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
class GPCParser:
    """Parse tokenized GPC into a GPCScript structure."""

    def __init__(self, tokens: List[Token], source: str = ""):
        self._tokens = tokens
        self._pos = 0
        self._source = source
        self.script = GPCScript(source=source)

    def parse(self) -> GPCScript:
        """Parse the full token stream."""
        while not self._at_end():
            try:
                self._parse_top_level()
            except Exception as e:
                tok = self._peek()
                self.script.errors.append(
                    f"Line {tok.line}: parse error: {e}")
                self._advance()  # skip past error
        return self.script

    def _parse_top_level(self):
        tok = self._peek()

        if tok.type == TokenType.PREPROCESSOR:
            self._parse_preprocessor()
        elif tok.type == TokenType.KEYWORD:
            if tok.value == "main":
                self._parse_main()
            elif tok.value == "combo":
                self._parse_combo()
            elif tok.value == "function":
                self._parse_function()
            elif tok.value in ("int", "data"):
                self._parse_variable()
            else:
                self._advance()
        elif tok.type == TokenType.EOF:
            self._advance()
        else:
            self._advance()

    def _parse_preprocessor(self):
        tok = self._advance()
        text = tok.value.strip()

        # Extract #define NAME VALUE
        m = re.match(r'#define\s+(\w+)\s*=?\s*(.*?)(?:;|$)', text)
        if m:
            self.script.defines.append(GPCDefine(
                name=m.group(1),
                value=m.group(2).strip().rstrip(';'),
                line=tok.line,
            ))

    def _parse_variable(self):
        type_tok = self._advance()  # int or data
        name_tok = self._advance()  # variable name

        var = GPCVariable(
            type=type_tok.value,
            name=name_tok.value,
            line=type_tok.line,
        )

        # Check for array
        if self._check(TokenType.LBRACKET):
            self._advance()  # [
            var.is_array = True
            if self._check(TokenType.NUMBER):
                var.array_size = int(self._advance().value)
            if self._check(TokenType.RBRACKET):
                self._advance()  # ]

        # Check for initializer
        if self._check(TokenType.OPERATOR) and self._peek().value == '=':
            self._advance()  # =
            if not self._at_end() and not self._check(TokenType.SEMICOLON):
                var.initial_value = self._advance().value

        # Skip to semicolon
        self._skip_to_semicolon()
        self.script.variables.append(var)

    def _parse_main(self):
        self._advance()  # 'main'
        body = self._extract_block()
        self.script.main_body = body

    def _parse_combo(self):
        self._advance()  # 'combo'
        name_tok = self._advance()  # combo name
        combo = GPCCombo(name=name_tok.value, line=name_tok.line)

        if not self._check(TokenType.LBRACE):
            self.script.errors.append(
                f"Line {name_tok.line}: expected '{{' after combo {name_tok.value}")
            return

        self._advance()  # {
        depth = 1

        while not self._at_end() and depth > 0:
            tok = self._peek()
            if tok.type == TokenType.LBRACE:
                depth += 1
                self._advance()
            elif tok.type == TokenType.RBRACE:
                depth -= 1
                self._advance()
            elif tok.type == TokenType.IDENTIFIER:
                # Parse function call: name(args);
                func_name = self._advance().value
                args = []
                if self._check(TokenType.LPAREN):
                    args = self._parse_arg_list()
                combo.steps.append(GPCComboStep(
                    function=func_name, args=args,
                    raw=f"{func_name}({', '.join(args)})",
                ))
                self._skip_to_semicolon()
            else:
                self._advance()

        self.script.combos.append(combo)

    def _parse_function(self):
        self._advance()  # 'function'
        name_tok = self._advance()
        # Just record function name, skip body
        self.script.functions.append(name_tok.value)
        # Skip past args
        if self._check(TokenType.LPAREN):
            while not self._at_end() and not self._check(TokenType.RPAREN):
                self._advance()
            if self._check(TokenType.RPAREN):
                self._advance()
        # Skip body block
        self._extract_block()

    def _parse_arg_list(self) -> List[str]:
        """Parse (arg1, arg2, ...) and return list of arg strings."""
        args = []
        if not self._check(TokenType.LPAREN):
            return args
        self._advance()  # (

        current_arg = []
        depth = 0
        while not self._at_end():
            tok = self._peek()
            if tok.type == TokenType.RPAREN and depth == 0:
                self._advance()  # )
                if current_arg:
                    args.append(' '.join(current_arg))
                break
            elif tok.type == TokenType.LPAREN:
                depth += 1
                current_arg.append(tok.value)
                self._advance()
            elif tok.type == TokenType.RPAREN:
                depth -= 1
                current_arg.append(tok.value)
                self._advance()
            elif tok.type == TokenType.COMMA and depth == 0:
                if current_arg:
                    args.append(' '.join(current_arg))
                    current_arg = []
                self._advance()
            else:
                current_arg.append(tok.value)
                self._advance()

        return args

    def _extract_block(self) -> str:
        """Skip and return the raw text of a { ... } block."""
        if not self._check(TokenType.LBRACE):
            return ""
        self._advance()  # {
        depth = 1
        parts = []
        while not self._at_end() and depth > 0:
            tok = self._advance()
            if tok.type == TokenType.LBRACE:
                depth += 1
                parts.append('{')
            elif tok.type == TokenType.RBRACE:
                depth -= 1
                if depth > 0:
                    parts.append('}')
            else:
                parts.append(tok.value)
        return ' '.join(parts)

    # Helpers
    def _peek(self) -> Token:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return Token(TokenType.EOF, "", 0, 0)

    def _advance(self) -> Token:
        tok = self._peek()
        self._pos += 1
        return tok

    def _check(self, ttype: str) -> bool:
        return self._peek().type == ttype

    def _at_end(self) -> bool:
        return self._pos >= len(self._tokens) or self._peek().type == TokenType.EOF

    def _skip_to_semicolon(self):
        while not self._at_end() and not self._check(TokenType.SEMICOLON):
            self._advance()
        if self._check(TokenType.SEMICOLON):
            self._advance()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def parse_gpc(source: str) -> GPCScript:
    """Parse GPC source code string into a GPCScript."""
    tokens = tokenize(source)
    parser = GPCParser(tokens, source)
    script = parser.parse()

    log_info(f"GPCParser: parsed {len(script.defines)} defines, "
             f"{len(script.variables)} vars, {len(script.combos)} combos, "
             f"{len(script.functions)} functions, {len(script.errors)} errors")

    return script


def parse_gpc_file(path: str) -> GPCScript:
    """Parse a .gpc file from disk."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            source = f.read()
        return parse_gpc(source)
    except Exception as e:
        log_error(f"GPCParser: failed to read {path}: {e}")
        script = GPCScript()
        script.errors.append(f"Failed to read file: {e}")
        return script
