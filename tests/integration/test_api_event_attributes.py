"""Event entity attributes, read as raw protobuf off the socket.

Home Assistant's EventEntity accepts a dict of attributes alongside the event
type. ListEntitiesEventResponse declares the names and the types once, and each
EventResponse carries values against that declaration, so the protocol names no
attribute of its own.

The payloads are read as bytes rather than through aioesphomeapi, because the
client library has no such fields yet: it would file them away as unknown fields
and an assertion made through it would pass against a device that sent nothing.
Bytes are also the only way to prove the *absence* half, which is what keeps an
older client working.
"""

from __future__ import annotations

import re
import struct

from aioesphomeapi import api_pb2
import pytest

from .raw_api_client import MESSAGE_TYPE_OF, RawApiClient, decode_varint
from .types import RunCompiledFunction

EVENT_RESPONSE = MESSAGE_TYPE_OF[api_pb2.EventResponse]
LIST_ENTITIES_EVENT_RESPONSE = MESSAGE_TYPE_OF[api_pb2.ListEntitiesEventResponse]
LIST_ENTITIES_DONE = MESSAGE_TYPE_OF[api_pb2.ListEntitiesDoneResponse]

# EventResponse
EVENT_FIELD_KEY = 1
EVENT_FIELD_EVENT_TYPE = 2
EVENT_FIELD_ATTRIBUTES = 4
# ListEntitiesEventResponse
INFO_FIELD_KEY = 2
INFO_FIELD_ATTRIBUTES = 11
# ListEntitiesEventAttribute
ATTRIBUTE_INFO_FIELD_NAME = 1
ATTRIBUTE_INFO_FIELD_TYPE = 2

WIRE_VARINT = 0
WIRE_FIXED64 = 1
WIRE_LENGTH_DELIMITED = 2
WIRE_FIXED32 = 5


def _parse_fields(payload: bytes) -> dict[int, list[int | bytes]]:
    """Decode one protobuf payload into {field number: [values]}.

    Hand-rolled rather than handed to api_pb2, whose descriptors do not know
    these field numbers and would silently file them away as unknown fields.
    Every field is a list because the attributes are repeated.
    """
    buf = bytearray(payload)
    fields: dict[int, list[int | bytes]] = {}
    pos = 0
    while pos < len(buf):
        decoded = decode_varint(buf, pos)
        assert decoded is not None, "truncated tag"
        tag, pos = decoded
        field_number, wire_type = tag >> 3, tag & 0x07
        if wire_type == WIRE_VARINT:
            decoded = decode_varint(buf, pos)
            assert decoded is not None, "truncated varint"
            value, pos = decoded
        elif wire_type == WIRE_LENGTH_DELIMITED:
            decoded = decode_varint(buf, pos)
            assert decoded is not None, "truncated length"
            length, pos = decoded
            value = bytes(buf[pos : pos + length])
            pos += length
        elif wire_type == WIRE_FIXED32:
            value = int.from_bytes(buf[pos : pos + 4], "little")
            pos += 4
        elif wire_type == WIRE_FIXED64:
            value = int.from_bytes(buf[pos : pos + 8], "little")
            pos += 8
        else:
            raise AssertionError(f"unexpected wire type {wire_type}")
        fields.setdefault(field_number, []).append(value)
    return fields


def _event_payloads(client: RawApiClient) -> dict[str, bytes]:
    """The last EventResponse payload seen for each event type."""
    payloads: dict[str, bytes] = {}
    for msg_type, payload in client.frames:
        if msg_type != EVENT_RESPONSE:
            continue
        event_type = _parse_fields(payload)[EVENT_FIELD_EVENT_TYPE][0]
        assert isinstance(event_type, bytes)
        payloads[event_type.decode()] = payload
    return payloads


def _expected_bare_payload(key: int, event_type: bytes) -> bytes:
    """EventResponse with a key and an event type and nothing else.

    Written out by hand rather than re-encoded through anything under test: it
    is the whole of what the message was before it could carry attributes.
    """
    return (
        struct.pack("<BI", (EVENT_FIELD_KEY << 3) | WIRE_FIXED32, key)
        + bytes(
            [(EVENT_FIELD_EVENT_TYPE << 3) | WIRE_LENGTH_DELIMITED, len(event_type)]
        )
        + event_type
    )


@pytest.mark.asyncio
async def test_api_event_attributes_byte_identical(
    yaml_config: str,
    run_compiled: RunCompiledFunction,
    unused_tcp_port: int,
) -> None:
    """An event that carries no attributes encodes to exactly what it did before.

    An empty repeated field occupies no bytes, so this is the whole of the
    backward compatibility argument in both directions: a client older than the
    field decodes nothing extra, and a device older than it encodes nothing
    extra, and neither can tell the two apart. The entity here *declares* an
    attribute, so the field is compiled in and the encoder really does walk it.
    """
    async with (
        run_compiled(yaml_config),
        RawApiClient(unused_tcp_port, capture_frames=True) as client,
    ):
        await client.connect(client_info="event-attributes-client")
        await client.send_message(api_pb2.ListEntitiesRequest())
        await client.read_until_frame(LIST_ENTITIES_DONE, timeout=10.0)
        await client.send_message(api_pb2.SubscribeStatesRequest())
        await client.read_until_frame(EVENT_RESPONSE, timeout=10.0)

    keys = [
        _parse_fields(payload)[INFO_FIELD_KEY][0]
        for msg_type, payload in client.frames
        if msg_type == LIST_ENTITIES_EVENT_RESPONSE
    ]
    assert len(keys) == 1
    key = keys[0]
    assert isinstance(key, int)

    payloads = _event_payloads(client)
    assert set(payloads) == {"press"}
    assert payloads["press"] == _expected_bare_payload(key, b"press")


@pytest.mark.asyncio
async def test_api_event_attributes_on_the_wire(
    yaml_config: str,
    run_compiled: RunCompiledFunction,
    unused_tcp_port: int,
) -> None:
    """The listing declares the attributes and each event carries its own subset."""
    retained: list[str] = []

    def _on_log_line(line: str) -> None:
        # The logger colours its output, so read the digits rather than the tail.
        if match := re.search(r"retained attributes: (\d+)", line):
            retained.append(match.group(1))

    async with (
        run_compiled(yaml_config, line_callback=_on_log_line),
        RawApiClient(unused_tcp_port, capture_frames=True) as client,
    ):
        await client.connect(client_info="event-attributes-client")
        await client.send_message(api_pb2.ListEntitiesRequest())
        await client.read_until_frame(LIST_ENTITIES_DONE, timeout=10.0)
        await client.send_message(api_pb2.SubscribeStatesRequest())
        # One tick fires all three, so three responses cover every case wherever
        # in the tick the subscription landed.
        await client.read_until_frame(EVENT_RESPONSE, timeout=10.0, count=6)

    infos = [
        payload
        for msg_type, payload in client.frames
        if msg_type == LIST_ENTITIES_EVENT_RESPONSE
    ]
    assert len(infos) == 1
    declared = []
    for attribute in _parse_fields(infos[0])[INFO_FIELD_ATTRIBUTES]:
        assert isinstance(attribute, bytes)
        fields = _parse_fields(attribute)
        name = fields[ATTRIBUTE_INFO_FIELD_NAME][0]
        assert isinstance(name, bytes)
        # An enumerator of 0 (int) is the proto3 default and occupies no bytes.
        type_ = fields.get(ATTRIBUTE_INFO_FIELD_TYPE, [0])[0]
        declared.append((name.decode(), type_))
    # EVENT_ATTRIBUTE_TYPE_INT/FLOAT/BOOL/STRING are 0/1/2/3, and the order is
    # the order they were declared in: it is what the index on a value means.
    assert declared == [
        ("multi_press_count", 0),
        ("duration", 1),
        ("pressed", 2),
        ("label", 3),
    ]

    payloads = _event_payloads(client)
    assert set(payloads) == {"press", "multi_press_end", "long_press_end"}

    # Attribute 0 (multi_press_count) as a sint32 3: the index is 0 and so is
    # omitted, and zigzag(3) is 6.
    multi_press = _parse_fields(payloads["multi_press_end"])
    assert multi_press[EVENT_FIELD_ATTRIBUTES] == [b"\x10\x06"]

    # duration=1.5 at index 1, pressed=true at index 2, label="held" at index 3.
    long_press = _parse_fields(payloads["long_press_end"])
    assert long_press[EVENT_FIELD_ATTRIBUTES] == [
        b"\x08\x01\x1d" + struct.pack("<f", 1.5),
        b"\x08\x02 \x01",
        b"\x08\x03*\x04held",
    ]

    # The event type that sets nothing carries nothing, in the same connection
    # and from the same entity as the two that do.
    assert EVENT_FIELD_ATTRIBUTES not in _parse_fields(payloads["press"])

    # The values live for the trigger and no longer. That is what makes a
    # deferred response safe: it is encoded after the trigger has returned, so
    # it carries no attributes rather than a later trigger's.
    assert retained
    assert set(retained) == {"0"}
