#pragma once
class PubSubClient {
 public:
  bool publish(const char*, const char*, bool);
  bool connected();
};
