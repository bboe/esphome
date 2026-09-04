"""Unit tests for script/api_protobuf/api_protobuf.py generator logic.

ci-api-proto.yml only checks that the committed output matches what the
generator currently produces, so a semantic regression in the generator would
be committed and matched without anything failing. These tests pin the
semantics directly.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[4] / "script" / "api_protobuf"))

import aioesphomeapi.api_options_pb2 as pb  # noqa: E402
from api_protobuf import (  # noqa: E402
    MAX_MESSAGE_ID,
    _make_ifdef_line,
    calculate_message_estimated_size,
    get_varint64_ifdef,
    validate_message_id,
)
from google.protobuf import descriptor_pb2  # noqa: E402


def _file_with_messages(
    *messages: tuple[str, int, bool],
) -> descriptor_pb2.FileDescriptorProto:
    """Build a FileDescriptorProto with one single-field message per entry.

    Each entry is (message_name, field_type, deprecated).
    """
    file_desc = descriptor_pb2.FileDescriptorProto(name="test.proto")
    for name, field_type, deprecated in messages:
        msg = file_desc.message_type.add(name=name)
        field = msg.field.add(name="value", number=1, type=field_type)
        field.options.deprecated = deprecated
    return file_desc


UINT64 = descriptor_pb2.FieldDescriptorProto.TYPE_UINT64
INT64 = descriptor_pb2.FieldDescriptorProto.TYPE_INT64
SINT64 = descriptor_pb2.FieldDescriptorProto.TYPE_SINT64
UINT32 = descriptor_pb2.FieldDescriptorProto.TYPE_UINT32
FIXED64 = descriptor_pb2.FieldDescriptorProto.TYPE_FIXED64


def test_no_varint64_fields() -> None:
    file_desc = _file_with_messages(("A", UINT32, False), ("B", FIXED64, False))
    assert get_varint64_ifdef(file_desc, {}) == (False, None)


@pytest.mark.parametrize("field_type", [UINT64, INT64, SINT64])
def test_single_guard_is_kept(field_type: int) -> None:
    file_desc = _file_with_messages(("A", field_type, False))
    assert get_varint64_ifdef(file_desc, {"A": "USE_X"}) == (True, "USE_X")


def test_two_guards_emit_the_union() -> None:
    # The regression this pins: multiple guards used to collapse to
    # unconditional, pulling 64-bit varint support into unrelated builds.
    file_desc = _file_with_messages(("A", UINT64, False), ("B", INT64, False))
    guards = {"A": "USE_X", "B": "USE_Y"}
    assert get_varint64_ifdef(file_desc, guards) == (True, "USE_X || USE_Y")


def test_union_is_sorted_for_deterministic_output() -> None:
    file_desc = _file_with_messages(("B", UINT64, False), ("A", INT64, False))
    guards = {"B": "USE_Y", "A": "USE_X"}
    assert get_varint64_ifdef(file_desc, guards) == (True, "USE_X || USE_Y")


def test_any_unconditional_message_wins() -> None:
    file_desc = _file_with_messages(("A", UINT64, False), ("B", INT64, False))
    assert get_varint64_ifdef(file_desc, {"A": "USE_X"}) == (True, None)


def test_deprecated_fields_and_messages_are_ignored() -> None:
    file_desc = _file_with_messages(("A", UINT64, True), ("B", INT64, False))
    file_desc.message_type[1].options.deprecated = True
    assert get_varint64_ifdef(file_desc, {"A": "USE_X", "B": "USE_Y"}) == (False, None)


def test_make_ifdef_line_simple_identifier() -> None:
    assert _make_ifdef_line("USE_X") == "#ifdef USE_X"


def test_make_ifdef_line_union_wraps_each_identifier() -> None:
    # The second half of the varint64 union guard: compound conditions must
    # become #if defined(A) || defined(B), never #ifdef of the raw string.
    assert _make_ifdef_line("USE_X || USE_Y") == "#if defined(USE_X) || defined(USE_Y)"


def test_make_ifdef_line_conjunction_and_negation() -> None:
    assert (
        _make_ifdef_line("USE_X && !USE_Y") == "#if defined(USE_X) && !defined(USE_Y)"
    )


def test_message_id_at_maximum_is_accepted() -> None:
    # 16383 is the largest ID whose plaintext type varint fits the 2 bytes
    # budgeted in HEADER_PADDING.
    validate_message_id(MAX_MESSAGE_ID, "MaxMessage")


def test_message_id_above_maximum_is_rejected() -> None:
    with pytest.raises(ValueError, match="exceeds the plaintext"):
        validate_message_id(MAX_MESSAGE_ID + 1, "TooBigMessage")


def _message_with_fields(
    *fields: tuple[str, int, str | None],
) -> descriptor_pb2.DescriptorProto:
    """Build a DescriptorProto from (field_name, field_type, field_ifdef) entries."""
    msg = descriptor_pb2.DescriptorProto(name="Msg")
    for number, (name, field_type, ifdef) in enumerate(fields, start=1):
        field = msg.field.add(name=name, number=number, type=field_type)
        if ifdef is not None:
            field.options.Extensions[pb.field_ifdef] = ifdef
    return msg


def test_estimated_size_counts_unguarded_fields_in_the_base() -> None:
    msg = _message_with_fields(("a", UINT32, None), ("b", UINT32, None))
    base, conditional = calculate_message_estimated_size(msg)
    assert base > 0
    assert not conditional


def test_estimated_size_keeps_a_guarded_field_out_of_the_base() -> None:
    # The regression this pins: a field the build compiled out was still
    # counted, so every device paid for every optional field in the message.
    plain = _message_with_fields(("a", UINT32, None))
    guarded = _message_with_fields(("a", UINT32, None), ("b", UINT32, "USE_X"))

    plain_base, _ = calculate_message_estimated_size(plain)
    base, conditional = calculate_message_estimated_size(guarded)

    assert base == plain_base
    assert conditional == {"USE_X": 4}


def test_estimated_size_sums_fields_sharing_one_guard() -> None:
    msg = _message_with_fields(
        ("a", UINT32, "USE_X"), ("b", UINT32, "USE_X"), ("c", UINT32, "USE_Y")
    )
    base, conditional = calculate_message_estimated_size(msg)
    assert base == 0
    assert conditional == {"USE_X": 8, "USE_Y": 4}


def test_estimated_size_ignores_deprecated_guarded_fields() -> None:
    msg = _message_with_fields(("a", UINT32, "USE_X"))
    msg.field[0].options.deprecated = True
    assert calculate_message_estimated_size(msg) == (0, {})
