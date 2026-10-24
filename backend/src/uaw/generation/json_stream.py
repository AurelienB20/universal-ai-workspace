"""Reads the answer text out of a JSON document that arrives in pieces.

The model answers with structured output, ``{"answer": "...", "insufficient_context":
...}``, so a stream delivers fragments of JSON, cut anywhere: inside a key, in the
middle of an escape sequence, between the two halves of a surrogate pair. To show the
answer while it is written, ``AnswerTextExtractor`` decodes the value of the top-level
``answer`` string as it arrives and ignores everything else.

It only displays a draft: the complete document is still validated once the stream
ends, so a malformed fragment can at worst garble the preview, never the answer.
"""

_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
REPLACEMENT = "�"


class _StringDecoder:
    """Decodes the inside of a JSON string, one character at a time."""

    def __init__(self) -> None:
        # None outside an escape; "" right after the backslash; "u12" while reading hex.
        self._escape: str | None = None
        self._high_surrogate: int | None = None

    def feed(self, char: str) -> tuple[str, bool]:
        """Returns the decoded text, and whether this character closed the string."""
        if self._escape is not None:
            return self._continue_escape(char), False
        if char == "\\":
            self._escape = ""
            return "", False
        if char == '"':
            return self._flush(), True
        return self._flush() + char, False

    def _continue_escape(self, char: str) -> str:
        assert self._escape is not None
        if self._escape == "":
            if char == "u":
                self._escape = "u"
                return ""
            self._escape = None
            # An unknown escape is invalid JSON: show the character, validation decides.
            return self._flush() + _SIMPLE_ESCAPES.get(char, char)
        self._escape += char
        if len(self._escape) < 5:
            return ""
        digits, self._escape = self._escape[1:], None
        try:
            code = int(digits, 16)
        except ValueError:
            return self._flush() + REPLACEMENT
        return self._code_point(code)

    def _code_point(self, code: int) -> str:
        if 0xD800 <= code <= 0xDBFF:
            # The first half of a pair: wait for the second one.
            pending = self._flush()
            self._high_surrogate = code
            return pending
        if 0xDC00 <= code <= 0xDFFF:
            if self._high_surrogate is None:
                return REPLACEMENT
            high, self._high_surrogate = self._high_surrogate, None
            return chr(0x10000 + ((high - 0xD800) << 10) + (code - 0xDC00))
        return self._flush() + chr(code)

    def _flush(self) -> str:
        """A first half that is not followed by a second one cannot be shown."""
        if self._high_surrogate is None:
            return ""
        self._high_surrogate = None
        return REPLACEMENT


class AnswerTextExtractor:
    """Feed it the JSON fragments in order; it returns the new answer text each time."""

    def __init__(self, field: str = "answer") -> None:
        self._field = field
        self._depth = 0
        # What the string being read is: a top-level key, the answer, or anything else.
        self._string: str | None = None
        self._decoder = _StringDecoder()
        self._key: list[str] = []
        self._last_key: str | None = None
        self._expecting_value = False

    def feed(self, fragment: str) -> str:
        return "".join(self._char(char) for char in fragment)

    def _char(self, char: str) -> str:
        if self._string is not None:
            return self._string_char(char)
        if char.isspace():
            return ""
        if self._expecting_value:
            self._expecting_value = False
            if char == '"':
                self._start_string("answer" if self._last_key == self._field else "other")
                return ""
        if char in "{[":
            self._depth += 1
        elif char in "}]":
            self._depth -= 1
        elif char == ":" and self._depth == 1 and self._last_key is not None:
            self._expecting_value = True
        elif char == '"':
            self._start_string("key" if self._depth == 1 else "other")
        elif char == ",":
            self._last_key = None
        return ""

    def _start_string(self, role: str) -> None:
        self._string = role
        self._decoder = _StringDecoder()
        self._key = []

    def _string_char(self, char: str) -> str:
        text, closed = self._decoder.feed(char)
        role = self._string
        if closed:
            self._string = None
        if role == "answer":
            return text
        if role == "key":
            self._key.append(text)
            if closed:
                self._last_key = "".join(self._key)
        return ""
