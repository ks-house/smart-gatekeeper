#include "TargetCommandSecurity.h"

// No device/network effects: execute the actual deployed access-session parser.
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  sgk::SignedCommandAccessTracker tracker;
  return tracker.begin(sgk::SignedCommandAccessTracker::Mode::kManualRemote,
                       argv[1]) ? 0 : 1;
}
