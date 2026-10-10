#include "AccessEventCatalog.h"
#include <iostream>
int main() {
  for (int code = 0; code <= static_cast<int>(sgk::EventCode::kAccessSessionCompleted); ++code)
    for (int transport = 0; transport <= static_cast<int>(sgk::ResultReason::kInternalFailClosed); ++transport)
      for (int reason = 0; reason <= static_cast<int>(sgk::EventReason::kTargetBusy); ++reason) {
        sgk::Event event{};
        event.code = static_cast<sgk::EventCode>(code);
        event.transport_reason = static_cast<sgk::ResultReason>(transport);
        event.reason = static_cast<sgk::EventReason>(reason);
        sgk::AccessCatalog fields;
        if (sgk::buildAccessCatalog(event, &fields))
          std::cout << fields.event_code << '|' << fields.stage << '|'
                    << fields.outcome << '|' << fields.reason_code << '\n';
      }
}
