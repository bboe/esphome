"""Codegen for event entity attributes.

The names and the types are declared once per entity and reach C++ as a static
array; the values live on the ``event.trigger`` action. The bound the API's
arrays are sized to is the largest declaration in the build, which is only
knowable once every entity has been generated.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from esphome.core import CORE


def _defines() -> dict[str, str]:
    """The emitted defines, values rendered the way defines.h will carry them."""
    return {define.name: str(define.value) for define in CORE.defines}


def test_attributes_are_declared_once_per_entity(
    generate_main: Callable[[str | Path], str],
    component_config_path: Callable[[str], Path],
) -> None:
    """Each entity's declaration becomes a static array in flash, in YAML order.

    The order is the contract: a value on the wire names its attribute by index
    into this array rather than by name, so reordering it is a wire change.
    """
    main_cpp = generate_main(component_config_path("event_attributes.yaml"))

    assert (
        "static const event::EventAttributeInfo attributed_button_attributes[] = {"
        in main_cpp
    )
    for name, type_ in (
        ("multi_press_count", "INT"),
        ("duration", "FLOAT"),
        ("pressed", "BOOL"),
        ("label", "STRING"),
    ):
        assert f'.name = "{name}",' in main_cpp
        assert f".type = event::EventAttributeType::{type_}," in main_cpp
    assert (
        "attributed_button->set_attributes(attributed_button_attributes, 4);"
        in main_cpp
    )
    assert (
        "attributed_doorbell->set_attributes(attributed_doorbell_attributes, 1);"
        in main_cpp
    )
    # The entity that declares none gets no array and no call.
    assert "attributeless_event->set_attributes(" not in main_cpp


def test_trigger_action_emits_a_value_per_attribute(
    generate_main: Callable[[str | Path], str],
    component_config_path: Callable[[str], Path],
) -> None:
    """Values are named, not positional, and a trigger that sets none emits nothing.

    Each value is wrapped in a lambda returning EventAttributeValue, which the
    value's own C++ type converts to: that is what lets a lambda keep its return
    type instead of being cast to one the protocol chose.
    """
    main_cpp = generate_main(component_config_path("event_attributes.yaml"))

    assert main_cpp.count("init_attributes(1);") == 1
    assert main_cpp.count("init_attributes(3);") == 1
    # Three event.trigger actions, two of which carry values.
    assert main_cpp.count("set_event_type(") == 3
    assert main_cpp.count("init_attributes(") == 2
    assert main_cpp.count("add_attribute(") == 4

    assert (
        'add_attribute("multi_press_count", []() -> event::EventAttributeValue {'
        in main_cpp
    )
    assert 'add_attribute("duration", []() -> event::EventAttributeValue {' in main_cpp
    assert 'add_attribute("pressed", []() -> event::EventAttributeValue {' in main_cpp
    assert 'add_attribute("label", []() -> event::EventAttributeValue {' in main_cpp


def test_the_array_bound_is_the_largest_declaration(
    generate_main: Callable[[str | Path], str],
    component_config_path: Callable[[str], Path],
) -> None:
    """Both API messages hold a stack array sized to this, so it is a maximum.

    Four for the entity that declares four, not five for the two entities put
    together and not one for the last entity generated.
    """
    generate_main(component_config_path("event_attributes.yaml"))

    defines = _defines()
    assert "USE_EVENT_ATTRIBUTES" in defines
    assert defines["ESPHOME_EVENT_ATTRIBUTE_COUNT"] == "4"


def test_an_event_without_attributes_compiles_none_of_it(
    generate_main: Callable[[str | Path], str],
    component_config_path: Callable[[str], Path],
) -> None:
    """Nothing declared, nothing defined: the API's repeated field is ifdef'd out.

    This is the other half of the backward compatibility argument. The wire test
    shows an event with no *values* encoding to the bytes it always did; here the
    field is not compiled at all, so such a build's encoder is the previous one.
    """
    main_cpp = generate_main(component_config_path("event_no_attributes.yaml"))

    defines = _defines()
    assert "USE_EVENT_ATTRIBUTES" not in defines
    assert "ESPHOME_EVENT_ATTRIBUTE_COUNT" not in defines
    assert "set_attributes(" not in main_cpp
    assert "init_attributes(" not in main_cpp
