#include "event.h"
#include "esphome/core/defines.h"
#include "esphome/core/controller_registry.h"
#include "esphome/core/log.h"

namespace esphome::event {

static const char *const TAG = "event";

const char *Event::find_event_type_(const std::string &event_type) const {
  // Linear search with strcmp - faster than std::set for small datasets (1-5 items typical)
  for (const char *type : this->types_) {
    if (strcmp(type, event_type.c_str()) == 0) {
      return type;
    }
  }
  ESP_LOGE(TAG, "'%s': invalid event type for trigger(): %s", this->get_name().c_str(), event_type.c_str());
  return nullptr;
}

void Event::dispatch_(const char *event_type) {
  this->last_event_type_ = event_type;
  ESP_LOGV(TAG, "'%s' >> '%s'", this->get_name().c_str(), this->last_event_type_);
  this->event_callback_.call(StringRef(event_type));
#if defined(USE_EVENT) && defined(USE_CONTROLLER_REGISTRY)
  ControllerRegistry::notify_event(this);
#endif
}

void Event::trigger(const std::string &event_type) {
  const char *found = this->find_event_type_(event_type);
  if (found == nullptr) {
    return;
  }
  this->dispatch_(found);
}

#ifdef USE_EVENT_ATTRIBUTES
namespace {

int32_t float_to_int(float value) {
  // A lambda can produce anything; casting a NaN or an out-of-range float to int32_t is
  // undefined, so the comparisons are written to send NaN down the first branch.
  if (!(value > -2147483648.0f)) {
    return std::numeric_limits<int32_t>::min();
  }
  if (!(value < 2147483648.0f)) {
    return std::numeric_limits<int32_t>::max();
  }
  return static_cast<int32_t>(value);
}

}  // namespace

bool Event::resolve_attribute_(const EventAttributeValue &value, EventAttributeState &state) const {
  if (value.name == nullptr) {
    return false;
  }
  for (uint8_t i = 0; i < this->attribute_count_; i++) {
    if (strcmp(this->attributes_[i].name, value.name) != 0) {
      continue;
    }
    state.index = i;
    // The declared type wins: the value carries whatever type its source produced, and a
    // number is converted rather than refused. A string is not a number either way, so
    // crossing that line is the one mismatch reported instead of converted.
    const EventAttributeType declared = this->attributes_[i].type;
    if ((declared == EventAttributeType::STRING) != (value.type == EventAttributeType::STRING)) {
      ESP_LOGE(TAG, "'%s': wrong value type for attribute '%s'", this->get_name().c_str(), value.name);
      return false;
    }
    switch (declared) {
      case EventAttributeType::INT:
        state.int_value = value.type == EventAttributeType::FLOAT  ? float_to_int(value.float_value)
                          : value.type == EventAttributeType::BOOL ? (value.bool_value ? 1 : 0)
                                                                   : value.int_value;
        break;
      case EventAttributeType::FLOAT:
        state.float_value = value.type == EventAttributeType::INT    ? static_cast<float>(value.int_value)
                            : value.type == EventAttributeType::BOOL ? (value.bool_value ? 1.0f : 0.0f)
                                                                     : value.float_value;
        break;
      case EventAttributeType::BOOL:
        state.bool_value = value.type == EventAttributeType::INT     ? value.int_value != 0
                           : value.type == EventAttributeType::FLOAT ? value.float_value != 0.0f
                                                                     : value.bool_value;
        break;
      case EventAttributeType::STRING:
        state.string_value = value.string_value.c_str();
        break;
    }
    return true;
  }
  ESP_LOGE(TAG, "'%s': undeclared attribute for trigger(): %s", this->get_name().c_str(), value.name);
  return false;
}

void Event::trigger(const std::string &event_type, const EventAttributeValue *values, uint8_t count) {
  const char *found = this->find_event_type_(event_type);
  if (found == nullptr) {
    return;
  }
  for (uint8_t i = 0; i < count; i++) {
    EventAttributeState state{};
    if (this->resolve_attribute_(values[i], state)) {
      this->attribute_states_.push_back(state);
    }
  }
  this->dispatch_(found);
  // The values belong to this trigger and to nothing after it. Dropping them here is what
  // stops a state message that could not be sent now, and is encoded when the socket
  // drains, from carrying a later trigger's attributes: it carries none.
  this->attribute_states_.clear();
}
#endif

void Event::set_event_types(const FixedVector<const char *> &event_types) {
  this->types_.init(event_types.size());
  for (const char *type : event_types) {
    this->types_.push_back(type);
  }
  this->last_event_type_ = nullptr;  // Reset when types change
}

void Event::set_event_types(const std::vector<const char *> &event_types) {
  this->types_.init(event_types.size());
  for (const char *type : event_types) {
    this->types_.push_back(type);
  }
  this->last_event_type_ = nullptr;  // Reset when types change
}

}  // namespace esphome::event
