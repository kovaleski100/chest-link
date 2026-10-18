#include "../platform/3ds/pksm_storage.hpp"
#include <iostream>
#include <stdexcept>

int main() {
  using platform_detail::pksmUseExtData;
  auto check = [](bool ok, const char *message) {
    if (!ok)
      throw std::runtime_error(message);
  };
  auto ext = pksmUseExtData(R"({"version":13,"useExtData":true})");
  check(ext && *ext, "select ExtData when enabled");
  auto sd = pksmUseExtData(R"({"useExtData" : false,"autoBackup":true})");
  check(sd && !*sd, "select SD when ExtData is disabled");
  auto nested = pksmUseExtData(
      R"({"note":"\"useExtData\":false","nested":{"useExtData":false},"useExtData":true})");
  check(nested && *nested, "read only the top-level setting");
  check(!pksmUseExtData(R"({"useExtData":"false"})"),
        "ignore a setting with the wrong type");
  check(!pksmUseExtData(R"({"useExtData":trueish})"),
        "reject a non-boolean token");
  check(!pksmUseExtData(R"({"other":true})"), "missing setting uses fallback");
  check(!pksmUseExtData("not json"), "invalid config uses fallback");
  std::cout << "PASS PKSM storage selection config\n";
}
