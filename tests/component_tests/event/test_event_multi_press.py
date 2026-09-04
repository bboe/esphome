"""Tests for the multi_press_count attribute on the event.trigger action."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def test_multi_press_count_is_set_only_when_configured(
    generate_main: Callable[[str | Path], str],
    component_config_path: Callable[[str], Path],
) -> None:
    """A configured count reaches the action as a uint32_t lambda; an absent one emits nothing.

    ``TemplatableFn::value()`` returns ``T{}`` for an unset field, so an
    ``event.trigger`` without ``multi_press_count`` passes 0 and the API skips
    the field entirely. Emitting ``set_multi_press_count(0)`` there instead
    would be harmless on the wire but would hide that distinction, so the
    absence is asserted as well as the presence.
    """
    main_cpp = generate_main(component_config_path("event_multi_press.yaml"))

    # The return type is uint32_t rather than int, so TemplatableFn stores the
    # lambda directly instead of falling back to the deprecated casting trampoline.
    assert "set_multi_press_count([]() -> uint32_t {\n    return 3;\n});" in main_cpp
    # A templated count is emitted the same way, with the user's lambda body.
    assert "set_multi_press_count([]() -> uint32_t {" in main_cpp
    assert "return 2;" in main_cpp
    # Exactly the two triggers that configured a count emit a setter; the third
    # (press_start, which carries no attribute) emits none.
    assert main_cpp.count("set_multi_press_count(") == 2
    assert main_cpp.count("set_event_type(") == 3
