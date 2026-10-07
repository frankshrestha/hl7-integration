import re
from collections.abc import Mapping

DEFAULT_ENCODING_CHARACTERS: Mapping[str, str] = {
    "FIELD": "|",
    "COMPONENT": "^",
    "REPETITION": "~",
    "ESCAPE": "\\",
    "SUBCOMPONENT": "&",
}


def unescape_value(
    value: str, encoding_characters: Mapping[str, str] = DEFAULT_ENCODING_CHARACTERS
) -> str:
    escape = encoding_characters["ESCAPE"]
    if escape not in value:
        return value
    replacements = {
        "F": encoding_characters["FIELD"],
        "S": encoding_characters["COMPONENT"],
        "T": encoding_characters["SUBCOMPONENT"],
        "R": encoding_characters["REPETITION"],
        "E": escape,
    }
    pattern = re.compile(re.escape(escape) + r"([FSTRE])" + re.escape(escape))
    return pattern.sub(lambda match: replacements[match.group(1)], value)


def escape_value(
    value: str, encoding_characters: Mapping[str, str] = DEFAULT_ENCODING_CHARACTERS
) -> str:
    escape = encoding_characters["ESCAPE"]
    escaped_value = value.replace(escape, f"{escape}E{escape}")
    for character_name, code in (
        ("FIELD", "F"),
        ("COMPONENT", "S"),
        ("SUBCOMPONENT", "T"),
        ("REPETITION", "R"),
    ):
        escaped_value = escaped_value.replace(
            encoding_characters[character_name], f"{escape}{code}{escape}"
        )
    return escaped_value
