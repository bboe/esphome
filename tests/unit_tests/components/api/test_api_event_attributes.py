"""Invariant tests for the EventResponse.multi_press_count attribute.

Home Assistant's button event standard (home-assistant/architecture#1377)
specifies ``multi_press_count`` as an int, so it travels as its own typed
protobuf field rather than as an entry in a string key/value map. These tests
pin the three properties that are wire contract rather than implementation:

* The field number. An already-deployed client decodes by number, not by name,
  so renumbering it is a silent breaking change that nothing else in CI sees.
* The field is not force-encoded. A count of 0 must occupy no bytes, because
  that is what makes "old device, new client" and "new device, old client"
  read identically as "no attribute". A ``force`` option here would put a
  zero on the wire for every non-multi-press event, and a client would then
  have to know that 0 means absent rather than reading the field's presence.
* The value the device sends comes from the entity. A response built without
  reading it would compile, pass every other test, and send 0 for ever.

Group A reads api.proto as plain text (no protoc); Group B asserts on the
checked-in generated files, since "present in the generated C++" is exactly
equivalent to "the device sends it".
"""

from __future__ import annotations

from pathlib import Path
import re

import esphome

API_DIR = Path(esphome.__file__).parent / "components" / "api"

PROTO_TEXT = (API_DIR / "api.proto").read_text(encoding="utf-8")
HEADER_TEXT = (API_DIR / "api_pb2.h").read_text(encoding="utf-8")
CPP_TEXT = (API_DIR / "api_pb2.cpp").read_text(encoding="utf-8")
API_CONNECTION_TEXT = (API_DIR / "api_connection.cpp").read_text(encoding="utf-8")

FIELD_NAME = "multi_press_count"
FIELD_NUMBER = 4


def _extract_proto_message(message_name: str) -> str:
    match = re.search(
        rf"^message {re.escape(message_name)}\s*\{{(.*?)^\}}",
        PROTO_TEXT,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"could not find `message {message_name}` in api.proto"
    return match.group(1)


def _extract_braced_region(text: str, anchor_pattern: str) -> str:
    anchor_match = re.search(anchor_pattern, text)
    assert anchor_match is not None, f"could not find a match for {anchor_pattern!r}"
    open_brace = text.index("{", anchor_match.start())
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[anchor_match.start() : i + 1]
    raise AssertionError(f"unbalanced braces while scanning after {anchor_pattern!r}")


# ==================== Group A: api.proto ====================


def test_multi_press_count_field_number_is_pinned() -> None:
    """The field number is the wire contract; a rename is harmless, a renumber is not."""
    body = _extract_proto_message("EventResponse")
    match = re.search(rf"\buint32\s+{FIELD_NAME}\s*=\s*(\d+)", body)
    assert match is not None, (
        f"EventResponse.{FIELD_NAME} is missing or is no longer a uint32. "
        "The Home Assistant standard specifies an int; a string-typed "
        "attribute would put the cast back on every consumer."
    )
    assert int(match.group(1)) == FIELD_NUMBER


def test_multi_press_count_is_not_forced_or_deprecated() -> None:
    """No `force`, so a zero count is absent from the wire, and no `deprecated`.

    ``script/api_protobuf/api_protobuf.py`` skips a field marked
    ``[deprecated = true]`` entirely, generating no C++ for it at all.
    """
    body = _extract_proto_message("EventResponse")
    line = next(
        line
        for line in body.splitlines()
        if re.search(rf"\b{FIELD_NAME}\s*=\s*\d+", line)
    )
    assert "(force)" not in line
    assert "deprecated" not in line


# ==================== Group B: generated code ====================


def test_generated_header_declares_the_field() -> None:
    body = _extract_braced_region(HEADER_TEXT, r"class EventResponse\b")
    assert f"uint32_t {FIELD_NAME}{{0}};" in body


def test_generated_encoder_uses_the_pinned_number_and_skips_zero() -> None:
    """The non-`_force` encoder is what omits a zero count from the wire."""
    encode = _extract_braced_region(CPP_TEXT, r"uint8_t \*EventResponse::encode\(")
    assert (
        f"ProtoEncode::encode_uint32(pos PROTO_ENCODE_DEBUG_ARG, {FIELD_NUMBER}, "
        f"this->{FIELD_NAME});" in encode
    )
    assert "encode_uint32_force" not in encode

    size = _extract_braced_region(CPP_TEXT, r"uint32_t EventResponse::calculate_size\(")
    assert f"ProtoSize::calc_uint32(1, this->{FIELD_NAME});" in size
    assert "calc_uint32_force" not in size


def test_response_carries_the_entity_value() -> None:
    """A response that never reads the entity would send 0 for ever and pass everything else."""
    body = _extract_braced_region(
        API_CONNECTION_TEXT, r"uint16_t APIConnection::try_send_event_response\("
    )
    # Line-by-line rather than a substring search: the same text appears in the
    # comment above the statement, so a commented-out assignment would pass.
    statement = f"resp.{FIELD_NAME} = event->get_last_{FIELD_NAME}();"
    assert any(line.strip() == statement for line in body.splitlines())
