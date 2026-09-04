#pragma once

#include <cstring>
#include <limits>
#include <string>
#include <type_traits>
#include <vector>

#include "esphome/core/component.h"
#include "esphome/core/defines.h"
#include "esphome/core/entity_base.h"
#include "esphome/core/helpers.h"
#include "esphome/core/string_ref.h"

namespace esphome::event {

#ifdef USE_EVENT_ATTRIBUTES
enum class EventAttributeType : uint8_t {
  INT = 0,
  FLOAT = 1,
  BOOL = 2,
  STRING = 3,
};

/// One attribute an event entity declares. Lives in flash: the name and the type are
/// fixed at compile time and are what the API sends in the entity listing.
struct EventAttributeInfo {
  const char *name;
  EventAttributeType type;
};

/// A value handed to trigger(), owned by the caller for the length of that call. The
/// type is the one the value's own C++ type gives it, so a lambda in an automation is
/// written the way it would be anywhere else and needs no cast; trigger() converts it
/// to the type the entity declared for that attribute.
struct EventAttributeValue {
  EventAttributeValue() = default;
  template<typename T, enable_if_t<std::is_integral<T>::value && !std::is_same<T, bool>::value, int> = 0>
  EventAttributeValue(T value)  // NOLINT(google-explicit-constructor)
      : type(EventAttributeType::INT), int_value(static_cast<int32_t>(value)) {}
  template<typename T, enable_if_t<std::is_floating_point<T>::value, int> = 0>
  EventAttributeValue(T value)  // NOLINT(google-explicit-constructor)
      : type(EventAttributeType::FLOAT), float_value(static_cast<float>(value)) {}
  EventAttributeValue(bool value)  // NOLINT(google-explicit-constructor)
      : type(EventAttributeType::BOOL), bool_value(value) {}
  EventAttributeValue(const char *value)  // NOLINT(google-explicit-constructor)
      : type(EventAttributeType::STRING), string_value(value) {}
  EventAttributeValue(std::string value)  // NOLINT(google-explicit-constructor)
      : type(EventAttributeType::STRING), string_value(std::move(value)) {}
  EventAttributeValue(const StringRef &value)  // NOLINT(google-explicit-constructor)
      : type(EventAttributeType::STRING), string_value(value.c_str(), value.size()) {}

  const char *name{nullptr};
  EventAttributeType type{EventAttributeType::INT};
  int32_t int_value{0};
  float float_value{0.0f};
  bool bool_value{false};
  std::string string_value;
};

/// A value resolved against the declaration, for the trigger being dispatched. The
/// declared type at `index` says which member of the union is the live one, so a
/// string is a pointer into the caller's storage rather than a copy.
struct EventAttributeState {
  uint8_t index;
  union {
    int32_t int_value;
    float float_value;
    bool bool_value;
    const char *string_value;
  };
};
#endif

#define LOG_EVENT(prefix, type, obj) \
  if ((obj) != nullptr) { \
    ESP_LOGCONFIG(TAG, "%s%s '%s'", prefix, LOG_STR_LITERAL(type), (obj)->get_name().c_str()); \
    LOG_ENTITY_ICON(TAG, prefix, *(obj)); \
    LOG_ENTITY_DEVICE_CLASS(TAG, prefix, *(obj)); \
  }

class Event : public EntityBase {
 public:
  void trigger(const std::string &event_type);

#ifdef USE_EVENT_ATTRIBUTES
  /// Trigger the event with attribute values. The values are matched to the declared
  /// attributes by name and must outlive the call; nothing is kept once it returns.
  void trigger(const std::string &event_type, const EventAttributeValue *values, uint8_t count);

  /// Set the attributes this event declares (a static array, kept by pointer). The count
  /// is clamped to the size of the API's arrays, which codegen takes from the largest
  /// declaration in the build: a C++ caller that never passed through that count would
  /// otherwise write past them.
  void set_attributes(const EventAttributeInfo *attributes, uint8_t count) {
    this->attributes_ = attributes;
    this->attribute_count_ = count < ESPHOME_EVENT_ATTRIBUTE_COUNT ? count : ESPHOME_EVENT_ATTRIBUTE_COUNT;
    this->attribute_states_.init(this->attribute_count_);
  }

  /// Return the declared attributes, or nullptr if this event declares none.
  const EventAttributeInfo *get_attributes() const { return this->attributes_; }
  uint8_t get_attribute_count() const { return this->attribute_count_; }

  /// Attribute values of the trigger currently being dispatched. Empty at every other
  /// moment: they are cleared once the trigger has been reported.
  const FixedVector<EventAttributeState> &get_attribute_states() const { return this->attribute_states_; }
#endif

  /// Set the event types supported by this event (from initializer list).
  void set_event_types(std::initializer_list<const char *> event_types) {
    this->types_ = event_types;
    this->last_event_type_ = nullptr;  // Reset when types change
  }
  /// Set the event types supported by this event (from FixedVector).
  void set_event_types(const FixedVector<const char *> &event_types);
  /// Set the event types supported by this event (from vector).
  void set_event_types(const std::vector<const char *> &event_types);

  // Deleted overloads to catch incorrect std::string usage at compile time with clear error messages
  void set_event_types(std::initializer_list<std::string> event_types) = delete;
  void set_event_types(const FixedVector<std::string> &event_types) = delete;
  void set_event_types(const std::vector<std::string> &event_types) = delete;

  /// Return the event types supported by this event.
  const FixedVector<const char *> &get_event_types() const { return this->types_; }

  /// Return the last triggered event type, or empty StringRef if no event triggered yet.
  StringRef get_last_event_type() const { return StringRef::from_maybe_nullptr(this->last_event_type_); }

  /// Return event type by index, or nullptr if index is out of bounds.
  const char *get_event_type(uint8_t index) const {
    return index < this->types_.size() ? this->types_[index] : nullptr;
  }

  /// Return index of last triggered event type, or max uint8_t if no event triggered yet.
  uint8_t get_last_event_type_index() const {
    if (this->last_event_type_ == nullptr)
      return std::numeric_limits<uint8_t>::max();
    // Most events have <3 types, uint8_t is sufficient for all reasonable scenarios
    const uint8_t size = static_cast<uint8_t>(this->types_.size());
    for (uint8_t i = 0; i < size; i++) {
      if (this->types_[i] == this->last_event_type_)
        return i;
    }
    return std::numeric_limits<uint8_t>::max();
  }

  /// Check if an event has been triggered.
  bool has_event() const { return this->last_event_type_ != nullptr; }

  template<typename F> void add_on_event_callback(F &&callback) {
    this->event_callback_.add(std::forward<F>(callback));
  }

 protected:
  /// Find the entry in types_ matching event_type, or nullptr (logged) if there is none.
  const char *find_event_type_(const std::string &event_type) const;
  /// Record the event type and report it to the callbacks and the controllers.
  void dispatch_(const char *event_type);
#ifdef USE_EVENT_ATTRIBUTES
  /// Match a value to a declared attribute by name and convert it to the declared type.
  bool resolve_attribute_(const EventAttributeValue &value, EventAttributeState &state) const;
#endif

  LazyCallbackManager<void(StringRef event_type)> event_callback_;
  FixedVector<const char *> types_;

 private:
  /// Last triggered event type - must point to entry in types_ to ensure valid lifetime.
  /// Set by trigger() after validation, reset to nullptr when types_ changes.
  const char *last_event_type_{nullptr};
#ifdef USE_EVENT_ATTRIBUTES
  const EventAttributeInfo *attributes_{nullptr};
  uint8_t attribute_count_{0};
  FixedVector<EventAttributeState> attribute_states_;
#endif
};

}  // namespace esphome::event
