#include "network.hpp"
#include <cstdlib>
#include <iostream>

int main(int argc, char **argv) {
  if (argc != 2)
    return 2;
  try {
    const unsigned port = static_cast<unsigned>(std::stoul(argv[1]));
    const std::string address = chestlink::discoverPCServer(port, 1800);
    if (address.empty())
      return 1;
    std::cout << address << '\n';
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
