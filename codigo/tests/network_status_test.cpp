#include "network_status.hpp"
#include <cassert>
#include <iostream>
using namespace chestlink;
int main() {
  ServerProbeSchedule probe;
  assert(!probe.due(0));
  assert(probe.link("ChestLink-DS", "10.231.42.2", true));
  assert(probe.due(0));
  probe.begin(0);
  assert(probe.pending() && probe.result() == ServerAvailability::searching);
  assert(!probe.expired(2999) && probe.expired(3000));
  probe.finish({}, 3000);
  assert(probe.result() == ServerAvailability::notFound);
  assert(!probe.due(32999) && probe.due(33000));
  probe.begin(33000); probe.finish("10.231.42.9", 33001);
  assert(probe.result() == ServerAvailability::connected &&
         probe.serverIP() == "10.231.42.9");
  assert(!probe.link("ChestLink-DS", "10.231.42.2", true));
  assert(probe.link("TestNetwork", "", false));
  assert(probe.result() == ServerAvailability::unknown && !probe.due(99999));
  assert(probe.link("TestNetwork", "192.0.2.25", true));
  assert(probe.due(100000)); probe.begin(100000);
  assert(probe.link("", "", false));
  probe.finish("192.0.2.9", 100001); // Old network results cannot promote a new link.
  assert(probe.result() == ServerAvailability::unknown && !probe.pending());
  assert(probe.link("TestNetwork", "192.0.2.26", true));
  assert(probe.due(100002));
  std::cout << "PASS server discovery timing, timeout, route changes and stale results\n";
}
