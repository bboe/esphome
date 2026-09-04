#pragma once

#include "esphome/components/event/event.h"
#include "esphome/core/automation.h"
#include "esphome/core/component.h"

namespace esphome::event {

template<typename... Ts> class TriggerEventAction final : public Action<Ts...>, public Parented<Event> {
 public:
  TEMPLATABLE_VALUE(std::string, event_type)

#ifdef USE_EVENT_ATTRIBUTES
  // Initialize the FixedVector - called from Python codegen with the compile-time known
  // count. Must be called before any add_attribute(); capacity must match.
  void init_attributes(size_t count) { this->attributes_.init(count); }

  // Names are string literals from the YAML mapping keys and are never templatable, so
  // they stay in flash as const char *. Only the value can be a lambda.
  template<typename V> void add_attribute(const char *name, V &&value) {
    this->attributes_.emplace_back(name, std::forward<V>(value));
  }
#endif

  void play(const Ts &...x) override {
#ifdef USE_EVENT_ATTRIBUTES
    if (!this->attributes_.empty()) {
      // The values own whatever a lambda returned, and trigger() reads through them, so
      // they have to outlive the call. They are gone by the time play() returns, which is
      // the whole lifetime an event's attributes have.
      FixedVector<EventAttributeValue> values;
      values.init(this->attributes_.size());
      for (const auto &attribute : this->attributes_) {
        EventAttributeValue &value = values.emplace_back(attribute.value.value(x...));
        value.name = attribute.name;
      }
      this->parent_->trigger(this->event_type_.value(x...), values.begin(), static_cast<uint8_t>(values.size()));
      return;
    }
#endif
    this->parent_->trigger(this->event_type_.value(x...));
  }

#ifdef USE_EVENT_ATTRIBUTES
 protected:
  struct Attribute {
    // Default constructor needed for FixedVector::emplace_back()
    Attribute() = default;
    template<typename V> Attribute(const char *name, V value) : name(name), value(std::move(value)) {}

    const char *name{nullptr};
    TemplatableValue<EventAttributeValue, Ts...> value;
  };

  FixedVector<Attribute> attributes_;
#endif
};

class EventTrigger final : public Trigger<StringRef> {
 public:
  EventTrigger(Event *event) {
    event->add_on_event_callback([this](StringRef event_type) { this->trigger(event_type); });
  }
};

}  // namespace esphome::event
