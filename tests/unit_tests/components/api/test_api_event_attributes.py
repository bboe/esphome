"""Wire contract for event entity attributes.

Home Assistant's EventEntity accepts a dict of attributes alongside the event
type, and its button event standard (home-assistant/architecture#1377) defines
exactly one of them. Naming attributes in the protocol would mean a field per
attribute and a protocol change for each, so the names and the types are
declared once per entity in ListEntitiesEventResponse and each EventResponse
carries values against that declaration.

These pin the parts that are contract rather than implementation:

* The field numbers. A deployed client decodes by number, so renumbering is a
  silent breaking change nothing else in CI sees.
* The values are addressed by index rather than by name, and the index is not
  force-encoded, so the common single-attribute case pays nothing for it.
* Both repeated fields are behind ``USE_EVENT_ATTRIBUTES``, which codegen emits
  only when some entity declares an attribute: a build that declares none has
  the previous encoder, not a new one that happens to write nothing.
* The protocol names no attribute of its own.

Every assertion is made against the file with its comments stripped: the
comment above the event section names ``multi_press_count`` as the standard's
one attribute, and a search that read prose would find it there and call it a
declaration.
"""

from __future__ import annotations

from pathlib import Path
import re

import esphome

API_DIR = Path(esphome.__file__).parent / "components" / "api"


def _strip_comments(text: str) -> str:
    """Drop // comments; the assertions are about declarations, not prose."""
    return re.sub(r"//[^\n]*", "", text)


PROTO_RAW = (API_DIR / "api.proto").read_text(encoding="utf-8")
PROTO_TEXT = _strip_comments(PROTO_RAW)
CPP_TEXT = _strip_comments((API_DIR / "api_pb2.cpp").read_text(encoding="utf-8"))
API_CONNECTION_TEXT = _strip_comments(
    (API_DIR / "api_connection.cpp").read_text(encoding="utf-8")
)


def _proto_message(name: str) -> str:
    match = re.search(
        rf"^message {re.escape(name)}\s*\{{(.*?)^\}}",
        PROTO_TEXT,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"could not find `message {name}` in api.proto"
    return match.group(1)


def _proto_fields(message: str) -> dict[str, int]:
    """{field name: field number} for one message body."""
    return {
        match.group(1): int(match.group(2))
        for match in re.finditer(
            r"(?:^|\s)(?:repeated\s+)?\w[\w.]*\s+(\w+)\s*=\s*(\d+)", message
        )
    }


def test_the_repeated_fields_keep_their_numbers() -> None:
    """A deployed client reads these by number."""
    assert _proto_fields(_proto_message("EventResponse"))["attributes"] == 4
    assert (
        _proto_fields(_proto_message("ListEntitiesEventResponse"))["attributes"] == 11
    )


def test_a_value_names_its_attribute_by_index() -> None:
    """Sparse without the name's bytes on every event.

    The index is a plain uint32 rather than a forced one, so it costs nothing at
    0 -- the entity with one attribute, which is what the standard asks for.
    """
    fields = _proto_fields(_proto_message("EventAttribute"))
    assert fields["index"] == 1
    assert "(force)" not in _proto_message("EventAttribute")


def test_the_value_types_are_parallel_and_typed() -> None:
    """One field per type, the shape ExecuteServiceArgument already uses.

    A string key/value bag would put a cast back on every consumer; a typed
    field keeps the declared type all the way to Home Assistant.
    """
    assert _proto_fields(_proto_message("EventAttribute")) == {
        "index": 1,
        "int_": 2,
        "float_": 3,
        "bool_": 4,
        "string_": 5,
    }
    assert _proto_fields(_proto_message("ListEntitiesEventAttribute")) == {
        "name": 1,
        "type": 2,
    }


def test_the_protocol_names_no_attribute() -> None:
    """The point of the mechanism: an attribute is data, never a field.

    A protocol that named one would need a change for the next, and the
    non-standard ones -- a hold duration, say -- would have to be argued into it.
    """
    match = re.search(r"====+ EVENT ====+(.*?)====+ [A-Z]", PROTO_RAW, re.DOTALL)
    assert match is not None, "could not find the event section of api.proto"
    section = _strip_comments(match.group(1))
    assert "EventAttribute" in section, "the section is not the one being asserted on"
    for attribute in ("multi_press_count", "duration", "press_count", "count"):
        assert attribute not in section


def test_the_encoders_are_behind_the_define() -> None:
    """A build with no declared attribute compiles the encoder it always had."""
    for message in ("EventResponse", "ListEntitiesEventResponse"):
        match = re.search(
            rf"uint8_t \*{message}::encode\(.*?\n\}}", CPP_TEXT, re.DOTALL
        )
        assert match is not None, f"could not find {message}::encode in api_pb2.cpp"
        body = match.group(0)
        assert "attributes" in body
        loop = body.index("for (uint16_t i = 0; i < this->attributes_len; i++)")
        guard = body.rindex("#ifdef USE_EVENT_ATTRIBUTES", 0, loop)
        assert "#endif" not in body[guard:loop]


def test_the_device_reads_the_values_from_the_entity() -> None:
    """A response built without reading them would compile and send nothing."""
    assert "event->get_attribute_states()" in API_CONNECTION_TEXT
    assert "event->get_attributes()" in API_CONNECTION_TEXT
    assert "event->get_attribute_count()" in API_CONNECTION_TEXT
