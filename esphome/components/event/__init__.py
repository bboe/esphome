from esphome import automation
import esphome.codegen as cg
from esphome.components import mqtt, web_server
import esphome.config_validation as cv
from esphome.const import (
    CONF_DEVICE_CLASS,
    CONF_ENTITY_CATEGORY,
    CONF_EVENT_TYPE,
    CONF_ICON,
    CONF_ID,
    CONF_MQTT_ID,
    CONF_ON_EVENT,
    CONF_WEB_SERVER,
    DEVICE_CLASS_BUTTON,
    DEVICE_CLASS_DOORBELL,
    DEVICE_CLASS_EMPTY,
    DEVICE_CLASS_MOTION,
)
from esphome.core import CORE, ID, CoroPriority, coroutine_with_priority
from esphome.core.entity_helpers import (
    entity_duplicate_validator,
    queue_entity_register,
    setup_device_class,
    setup_entity,
)
from esphome.cpp_generator import MockObj, MockObjClass, TemplateArgsType
from esphome.types import ConfigType

CODEOWNERS = ["@nohat"]
IS_PLATFORM_COMPONENT = True

DEVICE_CLASSES = [
    DEVICE_CLASS_BUTTON,
    DEVICE_CLASS_DOORBELL,
    DEVICE_CLASS_EMPTY,
    DEVICE_CLASS_MOTION,
]

event_ns = cg.esphome_ns.namespace("event")
Event = event_ns.class_("Event", cg.EntityBase)
EventPtr = Event.operator("ptr")

TriggerEventAction = event_ns.class_("TriggerEventAction", automation.Action)

# Only this component and zigbee use the key, so it stays out of const.py.
CONF_ATTRIBUTES = "attributes"

EventAttributeInfo = event_ns.struct("EventAttributeInfo")
EventAttributeType = event_ns.enum("EventAttributeType", is_class=True)
EventAttributeValue = event_ns.struct("EventAttributeValue")

# The type an attribute is declared with, and the enumerator that names it in C++.
ATTRIBUTE_TYPES = {
    "int": EventAttributeType.INT,
    "float": EventAttributeType.FLOAT,
    "bool": EventAttributeType.BOOL,
    "string": EventAttributeType.STRING,
}

# Both API messages hold their attributes in a stack array sized to the largest
# declaration in the build, so one wasteful entity would widen every event message.
# Home Assistant's own event standard defines a single attribute; eight is room to
# spare at 192 bytes of stack for the state message.
MAX_ATTRIBUTES = 8

_ATTRIBUTE_COUNT_KEY = "event_attribute_count"

validate_device_class = cv.one_of(*DEVICE_CLASSES, lower=True, space="_")


def _validate_attribute_name(value: str) -> str:
    """An attribute name reaches Home Assistant as a key of the event's data dict."""
    value = cv.string_strict(value)
    if not value or not value.replace("_", "").isalnum() or not value[0].isalpha():
        raise cv.Invalid(
            f"Attribute name '{value}' must start with a letter and contain only "
            f"letters, digits and underscores"
        )
    return value


ATTRIBUTES_SCHEMA = cv.All(
    cv.Schema({_validate_attribute_name: cv.one_of(*ATTRIBUTE_TYPES, lower=True)}),
    cv.Length(max=MAX_ATTRIBUTES),
)


@coroutine_with_priority(CoroPriority.FINAL)
async def _emit_attribute_count() -> None:
    """Emit the array bound once every event entity has declared its attributes."""
    cg.add_define("USE_EVENT_ATTRIBUTES")
    cg.add_define("ESPHOME_EVENT_ATTRIBUTE_COUNT", CORE.data[_ATTRIBUTE_COUNT_KEY])


def _request_attribute_count(count: int) -> None:
    previous = CORE.data.get(_ATTRIBUTE_COUNT_KEY)
    CORE.data[_ATTRIBUTE_COUNT_KEY] = (
        count if previous is None else max(previous, count)
    )
    if previous is None:
        CORE.add_job(_emit_attribute_count)


_EVENT_SCHEMA = (
    cv.ENTITY_BASE_SCHEMA.extend(web_server.WEBSERVER_SORTING_SCHEMA)
    .extend(cv.MQTT_COMPONENT_SCHEMA)
    .extend(
        {
            cv.OnlyWith(CONF_MQTT_ID, "mqtt"): cv.declare_id(mqtt.MQTTEventComponent),
            cv.GenerateID(): cv.declare_id(Event),
            cv.Optional(
                CONF_DEVICE_CLASS, visibility=cv.Visibility.ADVANCED
            ): validate_device_class,
            cv.Optional(CONF_ON_EVENT): automation.validate_automation({}),
            cv.Optional(CONF_ATTRIBUTES): ATTRIBUTES_SCHEMA,
        }
    )
)


_EVENT_SCHEMA.add_extra(entity_duplicate_validator("event"))


def event_schema(
    class_: MockObjClass = cv.UNDEFINED,
    *,
    icon: str = cv.UNDEFINED,
    entity_category: str = cv.UNDEFINED,
    device_class: str = cv.UNDEFINED,
) -> cv.Schema:
    schema = {}

    if class_ is not cv.UNDEFINED:
        schema[cv.GenerateID()] = cv.declare_id(class_)

    for key, default, validator in [
        (CONF_ICON, icon, cv.icon),
        (CONF_ENTITY_CATEGORY, entity_category, cv.entity_category),
        (CONF_DEVICE_CLASS, device_class, validate_device_class),
    ]:
        if default is not cv.UNDEFINED:
            schema[cv.Optional(key, default=default)] = validator

    return _EVENT_SCHEMA.extend(schema)


_CALLBACK_AUTOMATIONS = (
    automation.CallbackAutomation(
        CONF_ON_EVENT, "add_on_event_callback", [(cg.StringRef, "event_type")]
    ),
)


@setup_entity("event")
async def setup_event_core_(
    var: MockObj, config: ConfigType, *, event_types: list[str]
) -> None:
    await automation.build_callback_automations(var, config, _CALLBACK_AUTOMATIONS)

    cg.add(var.set_event_types(event_types))

    if attributes := config.get(CONF_ATTRIBUTES):
        _request_attribute_count(len(attributes))
        array = cg.static_const_array(
            ID(
                f"{config[CONF_ID].id}_attributes",
                is_declaration=True,
                type=EventAttributeInfo,
            ),
            cg.ArrayInitializer(
                *(
                    cg.StructInitializer(
                        EventAttributeInfo,
                        ("name", name),
                        ("type", ATTRIBUTE_TYPES[type_]),
                    )
                    for name, type_ in attributes.items()
                ),
                multiline=True,
            ),
        )
        cg.add(var.set_attributes(array, len(attributes)))

    setup_device_class(config)

    if mqtt_id := config.get(CONF_MQTT_ID):
        mqtt_ = cg.new_Pvariable(mqtt_id, var)
        await mqtt.register_mqtt_component(mqtt_, config)

    if web_server_config := config.get(CONF_WEB_SERVER):
        await web_server.add_entity_config(var, web_server_config)


async def register_event(
    var: MockObj, config: ConfigType, *, event_types: list[str]
) -> None:
    if not CORE.has_id(config[CONF_ID]):
        var = cg.Pvariable(config[CONF_ID], var)
    queue_entity_register("event", config)
    CORE.register_platform_component("event", var)
    await setup_event_core_(var, config, event_types=event_types)


async def new_event(config: ConfigType, *, event_types: list[str]) -> MockObj:
    var = cg.new_Pvariable(config[CONF_ID])
    await register_event(var, config, event_types=event_types)
    return var


def _attribute_value(value: object) -> object:
    """Keep the YAML value's own type: it is what picks the C++ type of the value."""
    if isinstance(value, (bool, int, float)):
        return value
    return cv.string_strict(value)


TRIGGER_EVENT_SCHEMA = cv.Schema(
    {
        cv.Required(CONF_ID): cv.use_id(Event),
        cv.Required(CONF_EVENT_TYPE): cv.templatable(cv.string_strict),
        cv.Optional(CONF_ATTRIBUTES): cv.Schema(
            {_validate_attribute_name: cv.templatable(_attribute_value)}
        ),
    }
)


@automation.register_action(
    "event.trigger", TriggerEventAction, TRIGGER_EVENT_SCHEMA, synchronous=True
)
async def event_fire_to_code(
    config: ConfigType,
    action_id: ID,
    template_arg: cg.TemplateArguments,
    args: TemplateArgsType,
) -> MockObj:
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    templ = await cg.templatable(config[CONF_EVENT_TYPE], args, cg.std_string)
    cg.add(var.set_event_type(templ))
    if attributes := config.get(CONF_ATTRIBUTES):
        cg.add(var.init_attributes(len(attributes)))
        for name, value in attributes.items():
            # EventAttributeValue converts from whatever the value is, so a lambda keeps
            # its own return type and the entity's declaration decides the wire type.
            cg.add(
                var.add_attribute(
                    name, await cg.templatable(value, args, EventAttributeValue)
                )
            )
    return var


@coroutine_with_priority(CoroPriority.CORE)
async def to_code(config: ConfigType) -> None:
    cg.add_global(event_ns.using)
