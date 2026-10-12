#include "update.hpp"
#include "protocol_io.hpp"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <utility>

namespace chestlink {
namespace {
using namespace wireio;
constexpr uint32_t MAX_UPDATE_BYTES = 16 * 1024 * 1024;

void updateHello(Wire &wire, uint32_t pin, uint32_t command) {
  if (pin > 999999)
    throw Error("PIN invalido.");
  uint8_t header[20];
  std::memcpy(header, "CLMAIL01", 8);
  put32(header + 8, 1);
  put32(header + 12, pin);
  put32(header + 16, command);
  wire.write(header, sizeof(header));
  result(wire);
}

std::string previousPath(const std::string &installPath) {
  for (unsigned i = 0; i < 100; ++i) {
    std::string suffix = i ? ".previous" + std::to_string(i) : ".previous";
    std::string candidate = installPath + suffix;
    if (!exists(candidate))
      return candidate;
  }
  throw Error("Muitos backups antigos; remova um arquivo .previous no SD.");
}
} // namespace

UpdateResult updateBinary(
    Wire &wire, uint32_t pin, uint32_t currentVersion,
    const std::string &installPath, uint32_t command, bool requireExisting,
    std::function<bool(uint32_t, uint32_t, uint32_t)> accept,
    Progress progress) {
  if (requireExisting && (installPath.empty() || !exists(installPath)))
    throw Error("Destino do app nao encontrado no armazenamento.");

  updateHello(wire, pin, command);
  result(wire); // Availability/error frame after the protocol handshake.
  uint8_t manifest[48];
  wire.read(manifest, sizeof(manifest));
  if (std::memcmp(manifest, "CLUPD001", 8))
    throw Error("Manifesto de atualizacao invalido.");
  const uint32_t version = le32(manifest + 8);
  const uint32_t bytes = le32(manifest + 12);
  Digest expected{};
  std::memcpy(expected.data(), manifest + 16, expected.size());
  if (!version || !bytes || bytes > MAX_UPDATE_BYTES)
    throw Error("Tamanho ou versao da atualizacao invalido.");

  auto decline = [&wire]() {
    uint8_t decision[4];
    put32(decision, 0);
    wire.write(decision, sizeof(decision));
  };
  if (version <= currentVersion) {
    decline();
    return {UpdateState::current, version, bytes};
  }
  if (!accept || !accept(version, bytes, currentVersion)) {
    decline();
    return {UpdateState::cancelled, version, bytes};
  }
  if (installPath.empty())
    throw Error("Destino da atualizacao nao definido.");

  const std::string temporary = installPath + ".download";
  std::remove(temporary.c_str());
  FILE *file = std::fopen(temporary.c_str(), "wb");
  if (!file)
    throw Error("Nao foi possivel gravar no SD. Confira o cartao.");
  bool installedBackup = false;
  std::string backup;
  try {
    uint8_t decision[4];
    put32(decision, 1);
    wire.write(decision, sizeof(decision));
    result(wire);

    Sha256 sha;
    uint8_t block[4096];
    uint32_t done = 0;
    while (done < bytes) {
      size_t n = std::min<size_t>(sizeof(block), bytes - done);
      wire.read(block, n);
      if (std::fwrite(block, 1, n, file) != n)
        throw Error("Falha ao gravar atualizacao no SD.");
      sha.update(block, n);
      done += static_cast<uint32_t>(n);
      if (progress && !progress(done, bytes))
        throw Error("Cancelado. O app instalado foi preservado.");
    }
    int flushError = std::fflush(file);
    int closeError = std::fclose(file);
    file = nullptr;
    if (flushError || closeError) {
      throw Error("Falha ao finalizar o arquivo no SD.");
    }
    if (sha.finish() != expected)
      throw Error("SHA-256 diferente. O app instalado foi preservado.");

    if (exists(installPath)) {
      backup = previousPath(installPath);
      if (std::rename(installPath.c_str(), backup.c_str()))
        throw Error("Nao foi possivel preservar o app atual no armazenamento.");
      installedBackup = true;
    }
    if (std::rename(temporary.c_str(), installPath.c_str())) {
      if (!std::rename(backup.c_str(), installPath.c_str()))
        installedBackup = false;
      throw Error(installedBackup
                      ? "Falha ao instalar; app anterior preservado em " + backup
                      : "Nao foi possivel instalar a atualizacao; app anterior restaurado.");
    }
  } catch (...) {
    if (file)
      std::fclose(file);
    std::remove(temporary.c_str());
    if (installedBackup && !exists(installPath))
      std::rename(backup.c_str(), installPath.c_str());
    throw;
  }
  return {UpdateState::installed, version, bytes};
}

UpdateResult update3DS(
    Wire &wire, uint32_t pin, uint32_t currentVersion,
    const std::string &installPath,
    std::function<bool(uint32_t, uint32_t, uint32_t)> accept,
    Progress progress) {
  return updateBinary(wire, pin, currentVersion, installPath, 4, true,
                      std::move(accept), std::move(progress));
}

UpdateResult updateNDS(
    Wire &wire, uint32_t pin, uint32_t currentVersion,
    const std::string &installPath,
    std::function<bool(uint32_t, uint32_t, uint32_t)> accept,
    Progress progress) {
  return updateBinary(wire, pin, currentVersion, installPath, 5, false,
                      std::move(accept), std::move(progress));
}
} // namespace chestlink
