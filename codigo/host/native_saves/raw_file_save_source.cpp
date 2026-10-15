#include "save_source.hpp"

#include "core.hpp"

#include <algorithm>
#include <cstdio>
#include <limits>
#include <memory>
#include <stdexcept>
#include <utility>

namespace chestlink {
namespace {
struct FileCloser {
  void operator()(FILE *file) const {
    if (file)
      std::fclose(file);
  }
};
} // namespace

RawFileSaveSource::RawFileSaveSource(std::string path, uint64_t maxBytes)
    : path_(std::move(path)), maxBytes_(maxBytes) {
  if (path_.empty())
    throw Error("Informe o caminho do arquivo de save.");
  if (!maxBytes_)
    throw Error("O limite de leitura do save deve ser maior que zero.");
}

SaveReadResult RawFileSaveSource::read() const {
  std::unique_ptr<FILE, FileCloser> file(std::fopen(path_.c_str(), "rb"));
  if (!file)
    throw Error("Nao foi possivel abrir o save para leitura: " + path_);

  if (std::fseek(file.get(), 0, SEEK_END))
    throw Error("Nao foi possivel determinar o tamanho do save.");
  const long end = std::ftell(file.get());
  if (end <= 0)
    throw Error("O arquivo de save esta vazio ou tem tamanho invalido.");

  const uint64_t size = static_cast<uint64_t>(end);
  if (size > maxBytes_ || size > std::numeric_limits<size_t>::max())
    throw Error("O arquivo de save excede o limite de leitura configurado.");
  if (std::fseek(file.get(), 0, SEEK_SET))
    throw Error("Nao foi possivel voltar ao inicio do save.");

  SaveReadResult result;
  result.bytes.resize(static_cast<size_t>(size));
  Sha256 hash;
  size_t offset = 0;
  while (offset < result.bytes.size()) {
    const size_t count =
        std::min<size_t>(result.bytes.size() - offset, 64u * 1024u);
    const size_t received =
        std::fread(result.bytes.data() + offset, 1, count, file.get());
    if (received != count)
      throw Error("O save mudou ou ocorreu um erro durante a leitura.");
    hash.update(result.bytes.data() + offset, received);
    offset += received;
  }

  // Reject a file that grew after its size was measured, instead of silently
  // returning a partial view of it.
  if (std::fgetc(file.get()) != EOF || std::ferror(file.get()))
    throw Error("O save mudou ou ocorreu um erro durante a leitura.");

  FILE *closed = file.release();
  if (std::fclose(closed))
    throw Error("Falha ao finalizar a leitura do save.");

  result.source = {SaveSourceKind::RawFile, path_, size};
  result.sha256 = hex(hash.finish());
  return result;
}

} // namespace chestlink
