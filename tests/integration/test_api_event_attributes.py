"""An event entity's multi_press_count reaches the wire, and only when set.

Home Assistant's button event standard (home-assistant/architecture#1377)
specifies multi_press_count as an int, so EventResponse carries it as its own
typed field rather than as a string in a key/value map.

The payload is read as raw bytes rather than through aioesphomeapi, because
the client library has no such field yet: it would drop the value into unknown
fields and the assertion would pass against a device that sent nothing. Reading
the bytes is also the only way to prove the *absence* half, which is what keeps
an older client working -- a zero count must occupy no bytes at all, so that
"this device does not send the field" and "this event carries no count" look
identical to every client that predates it.
"""

from __future__ import annotations

from aioesphomeapi import api_pb2
import pytest

from .raw_api_client import MESSAGE_TYPE_OF, RawApiClient, decode_varint
from .types import RunCompiledFunction

EVENT_RESPONSE = MESSAGE_TYPE_OF[api_pb2.EventResponse]

FIELD_EVENT_TYPE = 2
FIELD_MULTI_PRESS_COUNT = 4

WIRE_VARINT = 0
WIRE_FIXED64 = 1
WIRE_LENGTH_DELIMITED = 2
WIRE_FIXED32 = 5


def _parse_fields(payload: bytes) -> dict[int, int | bytes]:
    """Decode one protobuf payload into {field number: value}.

    Hand-rolled rather than handed to api_pb2.EventResponse, whose descriptor
    does not know field 4 and would silently file it away as an unknown field.
    """
    buf = bytearray(payload)
    fields: dict[int, int | bytes] = {}
    pos = 0
    while pos < len(buf):
        decoded = decode_varint(buf, pos)
        assert decoded is not None, "truncated tag"
        tag, pos = decoded
        field_number, wire_type = tag >> 3, tag & 0x07
        if wire_type == WIRE_VARINT:
            decoded = decode_varint(buf, pos)
            assert decoded is not None, "truncated varint"
            fields[field_number], pos = decoded
        elif wire_type == WIRE_LENGTH_DELIMITED:
            decoded = decode_varint(buf, pos)
            assert decoded is not None, "truncated length"
            length, pos = decoded
            fields[field_number] = bytes(buf[pos : pos + length])
            pos += length
        elif wire_type == WIRE_FIXED32:
            fields[field_number] = int.from_bytes(buf[pos : pos + 4], "little")
            pos += 4
        elif wire_type == WIRE_FIXED64:
            fields[field_number] = int.from_bytes(buf[pos : pos + 8], "little")
            pos += 8
        else:
            raise AssertionError(f"unexpected wire type {wire_type}")
    return fields


@pytest.mark.asyncio
async def test_api_event_attributes_on_the_wire(
    yaml_config: str,
    run_compiled: RunCompiledFunction,
    unused_tcp_port: int,
) -> None:
    """The count is encoded with the event that carries it and omitted from the one that does not."""
    async with (
        run_compiled(yaml_config),
        RawApiClient(unused_tcp_port, capture_frames=True) as client,
    ):
        await client.connect(client_info="event-attributes-client")
        await client.send_message(api_pb2.SubscribeStatesRequest())
        # One tick fires both events, so two responses cover both cases
        # wherever in the tick the subscription landed.
        await client.read_until_frame(EVENT_RESPONSE, timeout=10.0, count=2)

    by_type: dict[str, dict[int, int | bytes]] = {}
    for msg_type, payload in client.frames:
        if msg_type != EVENT_RESPONSE:
            continue
        fields = _parse_fields(payload)
        event_type = fields[FIELD_EVENT_TYPE]
        assert isinstance(event_type, bytes)
        by_type[event_type.decode()] = fields

    assert set(by_type) == {"multi_press_end", "press_start"}
    assert by_type["multi_press_end"][FIELD_MULTI_PRESS_COUNT] == 3
    assert FIELD_MULTI_PRESS_COUNT not in by_type["press_start"]
