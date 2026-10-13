#include "network_status.hpp"
#include <cassert>
#include <iostream>
using namespace chestlink;
int main() {
  InternetProbeSchedule probe;
  assert(!probe.due(0));
  assert(probe.link("ChestLink-DS", "10.231.42.2", true));
  assert(probe.due(0));
  probe.begin(0);
  assert(probe.pending() && probe.result() == InternetAccess::checking);
  assert(!probe.expired(3999) && probe.expired(4000));
  probe.finish(false, 4000);
  assert(probe.result() == InternetAccess::unconfirmed);
  assert(!probe.due(33999) && probe.due(34000));
  probe.begin(34000); probe.finish(true, 34001);
  assert(probe.result() == InternetAccess::reachable);
  assert(!probe.link("ChestLink-DS", "10.231.42.2", true));
  assert(probe.link("TestNetwork", "", false));
  assert(probe.result() == InternetAccess::unknown && !probe.due(99999));
  assert(probe.link("TestNetwork", "192.0.2.25", true));
  assert(probe.due(100000)); probe.begin(100000);
  assert(probe.link("", "", false));
  probe.finish(true, 100001); // A result from the old link cannot promote it.
  assert(probe.result() == InternetAccess::unknown && !probe.pending());
  assert(probe.link("TestNetwork", "192.0.2.26", true));
  assert(probe.due(100002));
  std::cout << "PASS internet probe timing, timeout, route changes and stale results\n";
}
