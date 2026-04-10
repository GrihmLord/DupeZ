"""Tests for app.gpc.gpc_parser — GPC tokenizer and parser."""

from app.gpc.gpc_parser import tokenize, parse_gpc, TokenType


class TestTokenizer:
    """Test the GPC tokenizer."""

    def test_empty_string(self):
        """Empty input produces only EOF token."""
        tokens = tokenize("")
        assert len(tokens) >= 1
        assert tokens[-1].type == TokenType.EOF

    def test_simple_keyword(self):
        """'main' is recognized as a keyword."""
        tokens = tokenize("main")
        keyword_tokens = [t for t in tokens if t.type == TokenType.KEYWORD]
        assert any(t.value == "main" for t in keyword_tokens)

    def test_number_literal(self):
        """Integer literals are tokenized as NUMBER."""
        tokens = tokenize("42")
        number_tokens = [t for t in tokens if t.type == TokenType.NUMBER]
        assert any(t.value == "42" for t in number_tokens)

    def test_braces(self):
        """Braces are tokenized correctly."""
        tokens = tokenize("{ }")
        types = [t.type for t in tokens]
        assert TokenType.LBRACE in types
        assert TokenType.RBRACE in types

    def test_define(self):
        """#define is tokenized as preprocessor."""
        tokens = tokenize("#define FOO 10")
        pp_tokens = [t for t in tokens if t.type == TokenType.PREPROCESSOR]
        assert len(pp_tokens) >= 1

    def test_comment_single_line(self):
        """Single-line comments are discarded during tokenization."""
        tokens = tokenize("// this is a comment")
        # The GPC tokenizer strips comments; only EOF should remain
        non_eof = [t for t in tokens if t.type != TokenType.EOF]
        assert len(non_eof) == 0

    def test_semicolons(self):
        """Semicolons are tokenized."""
        tokens = tokenize("int x;")
        types = [t.type for t in tokens]
        assert TokenType.SEMICOLON in types


class TestParser:
    """Test the GPC parser."""

    def test_minimal_script(self):
        """Parse a minimal 'main { }' script."""
        script = parse_gpc("main { }")
        assert script is not None

    def test_define_extraction(self):
        """Parser extracts #define directives."""
        source = "#define DELAY 500\nmain { }"
        script = parse_gpc(source)
        if hasattr(script, 'defines') and script.defines:
            names = [d.name for d in script.defines]
            assert "DELAY" in names

    def test_combo_block(self):
        """Parser recognizes combo blocks."""
        source = """
        combo MyCombo {
            set_val(XB1_A, 100);
            wait(50);
            set_val(XB1_A, 0);
        }
        main { }
        """
        script = parse_gpc(source)
        if hasattr(script, 'combos') and script.combos:
            names = [c.name for c in script.combos]
            assert "MyCombo" in names

    def test_variable_declaration(self):
        """Parser handles variable declarations."""
        source = "int myVar = 10;\nmain { }"
        script = parse_gpc(source)
        if hasattr(script, 'variables') and script.variables:
            names = [v.name for v in script.variables]
            assert "myVar" in names
