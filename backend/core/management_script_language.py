"""Small deterministic expression language shared by management scripts."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
import unicodedata

from core.exceptions import ScriptValidationError

MAX_EXPRESSION_DEPTH = 20
MAX_EXPRESSION_TOKENS = 2_048
MAX_PROGRAM_STATEMENTS = 500
MAX_RUNTIME_STEPS = 10_000
MAX_LIST_VALUES = 100
MAX_VALUE_CHARACTERS = 8_192
MAX_TOTAL_OUTPUT_CHARACTERS = 65_536
MAX_SOURCE_CHARACTERS = 32_768

ScriptValue = str | int | bool | tuple[str, ...] | None

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_TARGET = re.compile(r"[A-Za-z_][A-Za-z0-9_. :/-]*")
_INVALID_PATH_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
SAFE_FUNCTION_NAMES = frozenset(
    {
        "default",
        "fallback",
        "if",
        "conditional",
        "equals",
        "eq",
        "contains",
        "replace",
        "slice",
        "pad",
        "lower",
        "upper",
        "title",
        "first",
        "join",
        "sortname",
        "sort_name",
        "asciifold",
        "ascii_fold",
        "pathsafe",
        "path_safe",
        "concat",
        "not",
        "all",
        "and",
        "any",
        "or",
        "is_empty",
        "empty",
    }
)
SAFE_FUNCTION_ARITY: dict[str, tuple[int, int]] = {
    "default": (1, MAX_LIST_VALUES),
    "fallback": (1, MAX_LIST_VALUES),
    "if": (3, 3),
    "conditional": (3, 3),
    "equals": (2, 2),
    "eq": (2, 2),
    "contains": (2, 2),
    "replace": (3, 3),
    "slice": (2, 3),
    "pad": (2, 3),
    "lower": (1, 1),
    "upper": (1, 1),
    "title": (1, 1),
    "first": (1, 1),
    "join": (1, 2),
    "sortname": (1, 1),
    "sort_name": (1, 1),
    "asciifold": (1, 1),
    "ascii_fold": (1, 1),
    "pathsafe": (1, 2),
    "path_safe": (1, 2),
    "concat": (1, MAX_LIST_VALUES),
    "not": (1, 1),
    "all": (1, MAX_LIST_VALUES),
    "and": (1, MAX_LIST_VALUES),
    "any": (1, MAX_LIST_VALUES),
    "or": (1, MAX_LIST_VALUES),
    "is_empty": (1, 1),
    "empty": (1, 1),
}


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class Expression:
    kind: str
    value: str | int | bool | None = None
    children: tuple["Expression", ...] = ()
    line: int = 1
    column: int = 1


@dataclass(frozen=True, slots=True)
class Statement:
    operation: str
    target: str | None
    expression: Expression | None
    body: tuple["Statement", ...]
    alternate: tuple["Statement", ...]
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class TemplateSegment:
    literal: str | None
    expression: Expression | None
    legacy_variable: str | None
    format_spec: str | None
    line: int
    column: int


@dataclass(slots=True)
class EvaluationBudget:
    script_name: str
    steps: int = 0
    output_characters: int = 0

    def consume(self, expression: Expression, amount: int = 1) -> None:
        self.steps += amount
        if self.steps > MAX_RUNTIME_STEPS:
            _error(
                "Script exceeded the runtime step limit.",
                self.script_name,
                expression.line,
                expression.column,
            )

    def account(self, expression: Expression, value: ScriptValue) -> ScriptValue:
        if isinstance(value, str):
            size = len(value)
            text_values = (value,)
        elif isinstance(value, tuple):
            if len(value) > MAX_LIST_VALUES:
                _error(
                    "Script produced too many list values.",
                    self.script_name,
                    expression.line,
                    expression.column,
                )
            size = sum(len(item) for item in value)
            text_values = value
        else:
            size = 0
            text_values = ()
        if any(
            "\x00" in item
            or any(0xD800 <= ord(character) <= 0xDFFF for character in item)
            for item in text_values
        ):
            _error(
                "Script produced unsafe text.",
                self.script_name,
                expression.line,
                expression.column,
            )
        if size > MAX_VALUE_CHARACTERS:
            _error(
                "Script produced a value that is too long.",
                self.script_name,
                expression.line,
                expression.column,
            )
        self.output_characters += size
        if self.output_characters > MAX_TOTAL_OUTPUT_CHARACTERS:
            _error(
                "Script exceeded the total output limit.",
                self.script_name,
                expression.line,
                expression.column,
            )
        return value


def _error(
    message: str,
    script_name: str,
    line: int,
    column: int,
) -> None:
    raise ScriptValidationError(
        message,
        script_name=script_name,
        line=line,
        column=column,
    )


def _decode_string(
    source: str,
    start: int,
    *,
    script_name: str,
    line: int,
    column: int,
) -> tuple[str, int, int, int]:
    quote = source[start]
    position = start + 1
    current_line = line
    current_column = column + 1
    result: list[str] = []
    escapes = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", quote: quote}
    while position < len(source):
        char = source[position]
        if char == quote:
            return "".join(result), position + 1, current_line, current_column + 1
        if char in "\r\n":
            _error(
                "String literals cannot span lines.",
                script_name,
                current_line,
                current_column,
            )
        if char != "\\":
            result.append(char)
            position += 1
            current_column += 1
            continue
        if position + 1 >= len(source):
            _error(
                "String literal ends with an escape.",
                script_name,
                current_line,
                current_column,
            )
        escaped = source[position + 1]
        if escaped == "u":
            digits = source[position + 2 : position + 6]
            if len(digits) != 4 or any(
                value not in "0123456789abcdefABCDEF" for value in digits
            ):
                _error(
                    "String has an invalid Unicode escape.",
                    script_name,
                    current_line,
                    current_column,
                )
            result.append(chr(int(digits, 16)))
            position += 6
            current_column += 6
            continue
        replacement = escapes.get(escaped)
        if replacement is None:
            _error(
                "String has an unsupported escape.",
                script_name,
                current_line,
                current_column,
            )
        result.append(replacement)
        position += 2
        current_column += 2
    _error("String literal is not closed.", script_name, line, column)


def _tokenize(
    source: str,
    *,
    script_name: str,
    line: int,
    column: int,
) -> tuple[Token, ...]:
    tokens: list[Token] = []
    position = 0
    current_line = line
    current_column = column
    while position < len(source):
        char = source[position]
        if char.isspace():
            if char == "\n":
                current_line += 1
                current_column = 1
            else:
                current_column += 1
            position += 1
            continue
        token_line = current_line
        token_column = current_column
        if char in "(),[]":
            tokens.append(Token(char, char, token_line, token_column))
            position += 1
            current_column += 1
        elif char in {'"', "'"}:
            value, position, current_line, current_column = _decode_string(
                source,
                position,
                script_name=script_name,
                line=current_line,
                column=current_column,
            )
            tokens.append(Token("string", value, token_line, token_column))
        elif char.isdigit():
            end = position + 1
            while end < len(source) and source[end].isdigit():
                end += 1
            value = source[position:end]
            tokens.append(Token("integer", value, token_line, token_column))
            current_column += end - position
            position = end
        else:
            match = _IDENTIFIER.match(source, position)
            if match is None:
                _error(
                    f"Unexpected character {char!r}.",
                    script_name,
                    token_line,
                    token_column,
                )
            value = match.group(0)
            tokens.append(Token("identifier", value, token_line, token_column))
            position = match.end()
            current_column += len(value)
        if len(tokens) > MAX_EXPRESSION_TOKENS:
            _error(
                "Expression has too many tokens.",
                script_name,
                token_line,
                token_column,
            )
    tokens.append(Token("eof", "", current_line, current_column))
    return tuple(tokens)


class _ExpressionParser:
    def __init__(self, tokens: tuple[Token, ...], script_name: str) -> None:
        self.tokens = tokens
        self.script_name = script_name
        self.position = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.position]

    def parse(self) -> Expression:
        expression = self._primary(1)
        if self.current.kind != "eof":
            _error(
                "Unexpected token after expression.",
                self.script_name,
                self.current.line,
                self.current.column,
            )
        return expression

    def _primary(self, depth: int) -> Expression:
        token = self.current
        if depth > MAX_EXPRESSION_DEPTH:
            _error(
                "Expression is nested too deeply.",
                self.script_name,
                token.line,
                token.column,
            )
        self.position += 1
        if token.kind == "string":
            return Expression(
                "literal", token.value, line=token.line, column=token.column
            )
        if token.kind == "integer":
            return Expression(
                "literal", int(token.value), line=token.line, column=token.column
            )
        if token.kind == "[":
            values = self._arguments("]", depth)
            return Expression(
                "list", children=values, line=token.line, column=token.column
            )
        if token.kind != "identifier":
            _error(
                "Expected a value, variable, list, or safe function call.",
                self.script_name,
                token.line,
                token.column,
            )
        lowered = token.value.casefold()
        if lowered in {"true", "false", "null"}:
            values: dict[str, ScriptValue] = {
                "true": True,
                "false": False,
                "null": None,
            }
            return Expression(
                "literal", values[lowered], line=token.line, column=token.column
            )
        if self.current.kind != "(":
            return Expression(
                "variable", token.value, line=token.line, column=token.column
            )
        self.position += 1
        arguments = self._arguments(")", depth)
        return Expression(
            "call",
            token.value,
            children=arguments,
            line=token.line,
            column=token.column,
        )

    def _arguments(self, closing: str, depth: int) -> tuple[Expression, ...]:
        values: list[Expression] = []
        if self.current.kind == closing:
            self.position += 1
            return ()
        while True:
            values.append(self._primary(depth + 1))
            if len(values) > MAX_LIST_VALUES:
                _error(
                    "Expression contains too many values.",
                    self.script_name,
                    self.current.line,
                    self.current.column,
                )
            if self.current.kind == closing:
                self.position += 1
                return tuple(values)
            if self.current.kind != ",":
                _error(
                    f"Expected ',' or '{closing}'.",
                    self.script_name,
                    self.current.line,
                    self.current.column,
                )
            self.position += 1


@lru_cache(maxsize=1_024)
def compile_expression(
    source: str,
    *,
    script_name: str = "script",
    line: int = 1,
    column: int = 1,
) -> Expression:
    if len(source) > MAX_SOURCE_CHARACTERS:
        _error("Expression source is too long.", script_name, line, column)
    if not source.strip():
        _error("Expression is empty.", script_name, line, column)
    expression = _ExpressionParser(
        _tokenize(
            source,
            script_name=script_name,
            line=line,
            column=column,
        ),
        script_name,
    ).parse()
    for node in walk_expressions(expression):
        if (
            node.kind == "call"
            and str(node.value).casefold() not in SAFE_FUNCTION_NAMES
        ):
            _error(
                f"Unknown safe function: {node.value}.",
                script_name,
                node.line,
                node.column,
            )
        if node.kind == "call":
            minimum, maximum = SAFE_FUNCTION_ARITY[str(node.value).casefold()]
            if not minimum <= len(node.children) <= maximum:
                expected = (
                    str(minimum) if minimum == maximum else f"{minimum}-{maximum}"
                )
                _error(
                    f"{node.value}() expects {expected} arguments.",
                    script_name,
                    node.line,
                    node.column,
                )
    return expression


@lru_cache(maxsize=256)
def compile_naming_template(
    source: str,
    *,
    script_name: str = "naming script",
) -> tuple[TemplateSegment, ...]:
    if len(source) > MAX_SOURCE_CHARACTERS:
        _error("Naming script source is too long.", script_name, 1, 1)
    if not source:
        _error("Naming script is empty.", script_name, 1, 1)
    segments: list[TemplateSegment] = []
    literal_start = 0
    position = 0
    line = 1
    column = 1
    while position < len(source):
        char = source[position]
        if char == "}":
            _error("Unexpected closing brace.", script_name, line, column)
        if char != "{":
            if char == "\n":
                line += 1
                column = 1
            else:
                column += 1
            position += 1
            continue
        if literal_start < position:
            literal = source[literal_start:position]
            literal_line = source.count("\n", 0, literal_start) + 1
            last_break = source.rfind("\n", 0, literal_start)
            literal_column = literal_start - last_break
            segments.append(
                TemplateSegment(
                    literal=literal,
                    expression=None,
                    legacy_variable=None,
                    format_spec=None,
                    line=literal_line,
                    column=literal_column,
                )
            )
        end = source.find("}", position + 1)
        if end < 0:
            _error("Expression brace is not closed.", script_name, line, column)
        body = source[position + 1 : end].strip()
        body_column = (
            column
            + 1
            + len(source[position + 1 : end])
            - len(source[position + 1 : end].lstrip())
        )
        if not body:
            _error("Naming expression is empty.", script_name, line, column)
        legacy = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?::([^{}]+))?", body)
        if legacy is not None:
            segments.append(
                TemplateSegment(
                    literal=None,
                    expression=None,
                    legacy_variable=legacy.group(1),
                    format_spec=legacy.group(2),
                    line=line,
                    column=column,
                )
            )
        else:
            segments.append(
                TemplateSegment(
                    literal=None,
                    expression=compile_expression(
                        body,
                        script_name=script_name,
                        line=line,
                        column=body_column,
                    ),
                    legacy_variable=None,
                    format_spec=None,
                    line=line,
                    column=column,
                )
            )
        consumed = source[position : end + 1]
        line += consumed.count("\n")
        if "\n" in consumed:
            column = len(consumed.rsplit("\n", 1)[1]) + 1
        else:
            column += len(consumed)
        position = end + 1
        literal_start = position
    if literal_start < len(source):
        literal = source[literal_start:]
        literal_line = source.count("\n", 0, literal_start) + 1
        last_break = source.rfind("\n", 0, literal_start)
        segments.append(
            TemplateSegment(
                literal=literal,
                expression=None,
                legacy_variable=None,
                format_spec=None,
                line=literal_line,
                column=literal_start - last_break,
            )
        )
    return tuple(segments)


def _parse_tagging_block(
    lines: tuple[str, ...],
    start: int,
    *,
    script_name: str,
    depth: int,
) -> tuple[tuple[Statement, ...], int, str | None]:
    if depth > MAX_EXPRESSION_DEPTH:
        _error("Conditional nesting is too deep.", script_name, start + 1, 1)
    statements: list[Statement] = []
    position = start
    while position < len(lines):
        raw = lines[position]
        stripped = raw.strip()
        line_number = position + 1
        column = len(raw) - len(raw.lstrip()) + 1
        if not stripped or stripped.startswith("#"):
            position += 1
            continue
        if stripped in {"else:", "end"}:
            return tuple(statements), position + 1, stripped
        if stripped.startswith("if "):
            if not stripped.endswith(":"):
                _error(
                    "Conditional must end with ':'.",
                    script_name,
                    line_number,
                    column,
                )
            expression_source = stripped[3:-1].strip()
            expression_column = raw.index(expression_source) + 1
            expression = compile_expression(
                expression_source,
                script_name=script_name,
                line=line_number,
                column=expression_column,
            )
            body, position, terminator = _parse_tagging_block(
                lines,
                position + 1,
                script_name=script_name,
                depth=depth + 1,
            )
            alternate: tuple[Statement, ...] = ()
            if terminator == "else:":
                alternate, position, terminator = _parse_tagging_block(
                    lines,
                    position,
                    script_name=script_name,
                    depth=depth + 1,
                )
            if terminator != "end":
                _error(
                    "Conditional is missing 'end'.",
                    script_name,
                    line_number,
                    column,
                )
            statements.append(
                Statement(
                    operation="if",
                    target=None,
                    expression=expression,
                    body=body,
                    alternate=alternate,
                    line=line_number,
                    column=column,
                )
            )
            continue
        if stripped.startswith("delete "):
            target = stripped[7:].strip()
            if not _TARGET.fullmatch(target):
                _error("Delete target is invalid.", script_name, line_number, column)
            statements.append(
                Statement("delete", target, None, (), (), line_number, column)
            )
            position += 1
            continue
        operation = None
        remainder = ""
        for candidate in ("set", "append"):
            prefix = f"{candidate} "
            if stripped.startswith(prefix):
                operation = candidate
                remainder = stripped[len(prefix) :]
                break
        if operation is None or "=" not in remainder:
            _error(
                "Expected set, append, delete, or if statement.",
                script_name,
                line_number,
                column,
            )
        target, expression_source = (value.strip() for value in remainder.split("=", 1))
        if not _TARGET.fullmatch(target):
            _error("Statement target is invalid.", script_name, line_number, column)
        expression_column = raw.index("=") + 2
        expression = compile_expression(
            expression_source,
            script_name=script_name,
            line=line_number,
            column=expression_column,
        )
        statements.append(
            Statement(operation, target, expression, (), (), line_number, column)
        )
        position += 1
        if len(statements) > MAX_PROGRAM_STATEMENTS:
            _error(
                "Tagging script has too many statements.",
                script_name,
                line_number,
                column,
            )
    return tuple(statements), position, None


@lru_cache(maxsize=256)
def compile_tagging_program(
    source: str,
    *,
    script_name: str = "tagging script",
) -> tuple[Statement, ...]:
    if len(source) > MAX_SOURCE_CHARACTERS:
        _error("Tagging script source is too long.", script_name, 1, 1)
    lines = tuple(source.splitlines())
    statements, _position, terminator = _parse_tagging_block(
        lines, 0, script_name=script_name, depth=1
    )
    if terminator is not None:
        _error(
            f"Unexpected '{terminator}'.",
            script_name,
            1,
            1,
        )
    if not statements:
        _error("Tagging script has no executable statements.", script_name, 1, 1)
    total = sum(1 for _ in walk_statements(statements))
    if total > MAX_PROGRAM_STATEMENTS:
        _error(
            "Tagging script has too many statements.",
            script_name,
            1,
            1,
        )
    return statements


def walk_statements(statements: tuple[Statement, ...]):
    for statement in statements:
        yield statement
        yield from walk_statements(statement.body)
        yield from walk_statements(statement.alternate)


def walk_expressions(expression: Expression):
    yield expression
    for child in expression.children:
        yield from walk_expressions(child)


def _is_empty(value: ScriptValue) -> bool:
    return value is None or value == "" or value == ()


def _text(value: ScriptValue) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, tuple):
        return "; ".join(value)
    return str(value)


def _integer(
    value: ScriptValue,
    expression: Expression,
    budget: EvaluationBudget,
) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        _error(
            "Function requires an integer.",
            budget.script_name,
            expression.line,
            expression.column,
        )
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ScriptValidationError(
            "Function requires an integer.",
            script_name=budget.script_name,
            line=expression.line,
            column=expression.column,
        ) from error


def _arity(
    name: str,
    values: tuple[ScriptValue, ...],
    minimum: int,
    maximum: int,
    expression: Expression,
    budget: EvaluationBudget,
) -> None:
    if not minimum <= len(values) <= maximum:
        expected = str(minimum) if minimum == maximum else f"{minimum}-{maximum}"
        _error(
            f"{name}() expects {expected} arguments.",
            budget.script_name,
            expression.line,
            expression.column,
        )


def _call(
    expression: Expression,
    values: tuple[ScriptValue, ...],
    budget: EvaluationBudget,
) -> ScriptValue:
    name = str(expression.value).casefold()
    if name not in SAFE_FUNCTION_NAMES:
        _error(
            f"Unknown safe function: {expression.value}.",
            budget.script_name,
            expression.line,
            expression.column,
        )
    if name in {"default", "fallback"}:
        _arity(name, values, 1, MAX_LIST_VALUES, expression, budget)
        return next((value for value in values if not _is_empty(value)), None)
    if name in {"if", "conditional"}:
        _arity(name, values, 3, 3, expression, budget)
        return values[1] if bool(values[0]) else values[2]
    if name in {"equals", "eq"}:
        _arity(name, values, 2, 2, expression, budget)
        return values[0] == values[1]
    if name == "contains":
        _arity(name, values, 2, 2, expression, budget)
        container, needle = values
        if isinstance(container, tuple):
            return _text(needle) in container
        return _text(needle) in _text(container)
    if name == "replace":
        _arity(name, values, 3, 3, expression, budget)
        return _text(values[0]).replace(_text(values[1]), _text(values[2]))
    if name == "slice":
        _arity(name, values, 2, 3, expression, budget)
        start = _integer(values[1], expression, budget)
        end = _integer(values[2], expression, budget) if len(values) == 3 else None
        value = values[0]
        return value[start:end] if isinstance(value, tuple) else _text(value)[start:end]
    if name == "pad":
        _arity(name, values, 2, 3, expression, budget)
        width = _integer(values[1], expression, budget)
        fill = _text(values[2]) if len(values) == 3 else "0"
        if width < 0 or width > 1_024 or len(fill) != 1:
            _error(
                "pad() width or fill is invalid.",
                budget.script_name,
                expression.line,
                expression.column,
            )
        return _text(values[0]).rjust(width, fill)
    if name in {"lower", "upper", "title"}:
        _arity(name, values, 1, 1, expression, budget)
        text = _text(values[0])
        return {"lower": str.lower, "upper": str.upper, "title": str.title}[name](text)
    if name == "first":
        _arity(name, values, 1, 1, expression, budget)
        value = values[0]
        return value[0] if isinstance(value, tuple) and value else value
    if name == "join":
        _arity(name, values, 1, 2, expression, budget)
        value = values[0]
        separator = _text(values[1]) if len(values) == 2 else "; "
        return separator.join(value) if isinstance(value, tuple) else _text(value)
    if name in {"sortname", "sort_name"}:
        _arity(name, values, 1, 1, expression, budget)
        text = _text(values[0]).strip()
        for article in ("The ", "An ", "A "):
            if text.casefold().startswith(article.casefold()):
                return f"{text[len(article):]}, {text[: len(article) - 1]}"
        return text
    if name in {"asciifold", "ascii_fold"}:
        _arity(name, values, 1, 1, expression, budget)
        return (
            unicodedata.normalize("NFKD", _text(values[0]))
            .encode("ascii", "ignore")
            .decode()
        )
    if name in {"pathsafe", "path_safe"}:
        _arity(name, values, 1, 2, expression, budget)
        replacement = _text(values[1]) if len(values) == 2 else "_"
        if len(replacement) != 1 or replacement in "/\\\x00":
            _error(
                "path_safe() replacement must be one safe character.",
                budget.script_name,
                expression.line,
                expression.column,
            )
        return _INVALID_PATH_CHARACTERS.sub(replacement, _text(values[0]))
    if name == "concat":
        _arity(name, values, 1, MAX_LIST_VALUES, expression, budget)
        return "".join(_text(value) for value in values)
    if name == "not":
        _arity(name, values, 1, 1, expression, budget)
        return not bool(values[0])
    if name in {"all", "and"}:
        _arity(name, values, 1, MAX_LIST_VALUES, expression, budget)
        return all(bool(value) for value in values)
    if name in {"any", "or"}:
        _arity(name, values, 1, MAX_LIST_VALUES, expression, budget)
        return any(bool(value) for value in values)
    if name in {"is_empty", "empty"}:
        _arity(name, values, 1, 1, expression, budget)
        return _is_empty(values[0])
    _error(
        "Safe function is not implemented.",
        budget.script_name,
        expression.line,
        expression.column,
    )


def evaluate_expression(
    expression: Expression,
    variables: dict[str, ScriptValue],
    budget: EvaluationBudget,
) -> ScriptValue:
    budget.consume(expression)
    if expression.kind == "literal":
        return budget.account(expression, expression.value)
    if expression.kind == "variable":
        return budget.account(expression, variables.get(str(expression.value)))
    if expression.kind == "list":
        value = tuple(
            _text(evaluate_expression(child, variables, budget))
            for child in expression.children
        )
        return budget.account(expression, value)
    if expression.kind == "call":
        values = tuple(
            evaluate_expression(child, variables, budget)
            for child in expression.children
        )
        return budget.account(expression, _call(expression, values, budget))
    _error(
        "Expression node is invalid.",
        budget.script_name,
        expression.line,
        expression.column,
    )
