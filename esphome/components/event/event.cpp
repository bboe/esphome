#include "event.h"
#include "esphome/core/defines.h"
#include "esphome/core/controller_registry.h"
#include "esphome/core/log.h"

namespace esphome::event {

static const char *const TAG = "event";

void Event::trigger(const std::string &event_type, uint32_t multi_press_count) {
  // Linear search with strcmp - faster than std::set for small datasets (1-5 items typical)
  const char *found = nullptr;
  for (const char *type : this->types_) {
    if (strcmp(type, event_type.c_str()) == 0) {
      found = type;
      break;
    }
  }
  if (found == nullptr) {
    ESP_LOGE(TAG, "'%s': invalid event type for trigger(): %s", this->get_name().c_str(), event_type.c_str());
    return;
  }
  this->last_event_type_ = found;
  this->last_multi_press_count_ =
      static_cast<uint8_t>(std::min<uint32_t>(multi_press_count, std::numeric_limits<uint8_t>::max()));
  ESP_LOGV(TAG, "'%s' >> '%s'", this->get_name().c_str(), this->last_event_type_);
  this->event_callback_.call(StringRef(found));
#if defined(USE_EVENT) && defined(USE_CONTROLLER_REGISTRY)
  ControllerRegistry::notify_event(this);
#endif
}

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
