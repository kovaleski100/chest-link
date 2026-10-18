#include "network.hpp"
#include "update.hpp"
#include "version.hpp"
#include <cstdio>
#include <cstdlib>
using namespace chestlink;

int main(int argc, char **argv) {
  try {
    if (argc != 7 && argc != 8)
      throw Error("Uso: update-probe IP PIN VERSAO DESTINO ACEITAR PORTA [ds]");
    auto connection = Connection::connect(argv[1], std::stoul(argv[6]));
    auto wire = connection.wire();
    const bool nds = argc == 8 && std::string(argv[7]) == "ds";
    const std::string targetDirectory = argv[4];
    std::string installPath = nds ? std::string() : targetDirectory;
    auto accept = [accepted = std::stoul(argv[5]) != 0, nds, &installPath,
                   &targetDirectory](uint32_t remote, uint32_t, uint32_t) {
      if (nds)
        installPath = targetDirectory + "/ChestLink_DS_v" +
                      appVersionText(remote) + ".nds";
      return accepted;
    };
    auto result = nds
                      ? updateNDS(wire, std::stoul(argv[2]),
                                  std::stoul(argv[3]), installPath, accept)
                      : update3DS(wire, std::stoul(argv[2]),
                                  std::stoul(argv[3]), installPath, accept);
    const char *state = result.state == UpdateState::installed
                            ? "INSTALLED"
                            : result.state == UpdateState::cancelled ? "CANCELLED"
                                                                     : "CURRENT";
    std::printf("%s %s %u\n", state, appVersionText(result.version).c_str(),
                unsigned(result.bytes));
    return 0;
  } catch (const std::exception &error) {
    std::fprintf(stderr, "%s\n", error.what());
    return 1;
  }
}
