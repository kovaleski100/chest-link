// Fixed-size ExtData adapter. libctru's generic archive driver intentionally
// exposes ExtData as read-only; this adapter uses the explicit FS services.
#include "extdata.hpp"
#include "core.hpp"
#include <3ds.h>
#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sys/iosupport.h>
#include <sys/stat.h>
namespace {
FS_Archive archive = 0;
bool mounted = false;
struct ExtFile {
  Handle handle;
  uint64_t position, size;
  bool writing;
};
struct Path {
  uint16_t data[512];
  FS_Path value{};
  bool valid = false;
  explicit Path(const char *name) {
    if (std::strncmp(name, "pksm:", 5))
      return;
    const char *p = name + 5;
    if (*p != '/')
      return;
    ssize_t n = utf8_to_utf16(data, reinterpret_cast<const uint8_t *>(p), 511);
    if (n < 0 || n > 511)
      return;
    data[n] = 0;
    value = {PATH_UTF16, uint32_t((n + 1) * 2), data};
    valid = true;
  }
};
int failure(struct _reent *r, Result result) {
  // FS uses service-specific descriptions as well as generic Result codes.
  switch (uint32_t(result)) {
  case 0x082044BE:
  case 0xC82044BE:
  case 0xC82044B9:
    r->_errno = EEXIST;
    return -1;
  case 0xC8804478:
  case 0xC92044FA:
    r->_errno = ENOENT;
    return -1;
  case 0x086044D2:
  case 0xC86044D2:
    r->_errno = ENOSPC;
    return -1;
  case 0xE0E046BE:
    r->_errno = EINVAL;
    return -1;
  case 0xE0E046BF:
    r->_errno = ENAMETOOLONG;
    return -1;
  default:
    break;
  }
  if (R_SUMMARY(result) == RS_OUTOFRESOURCE) {
    r->_errno = ENOSPC;
    return -1;
  }
  switch (R_DESCRIPTION(result)) {
  case RD_NOT_FOUND:
    r->_errno = ENOENT;
    break;
  case RD_ALREADY_EXISTS:
    r->_errno = EEXIST;
    break;
  case RD_NOT_AUTHORIZED:
    r->_errno = EACCES;
    break;
  default:
    r->_errno = EIO;
    break;
  }
  return -1;
}
int invalid(struct _reent *r) {
  r->_errno = EINVAL;
  return -1;
}
int openFile(struct _reent *r, void *ptr, const char *name, int flags, int) {
  Path p(name);
  if (!p.valid)
    return invalid(r);
  if (flags & (O_CREAT | O_TRUNC | O_APPEND)) {
    r->_errno = ENOTSUP;
    return -1;
  }
  auto *f = static_cast<ExtFile *>(ptr);
  uint32_t mode = FS_OPEN_READ;
  f->writing = (flags & O_ACCMODE) != O_RDONLY;
  if (f->writing)
    mode |= FS_OPEN_WRITE;
  Result rc = FSUSER_OpenFile(&f->handle, archive, p.value, mode, 0);
  if (R_FAILED(rc))
    return failure(r, rc);
  rc = FSFILE_GetSize(f->handle, &f->size);
  if (R_FAILED(rc)) {
    FSFILE_Close(f->handle);
    return failure(r, rc);
  }
  f->position = 0;
  return 0;
}
int closeFile(struct _reent *r, void *ptr) {
  auto *f = static_cast<ExtFile *>(ptr);
  Result flush = f->writing ? FSFILE_Flush(f->handle) : 0;
  Result close = FSFILE_Close(f->handle);
  if (R_FAILED(flush))
    return failure(r, flush);
  return R_FAILED(close) ? failure(r, close) : 0;
}
ssize_t readFile(struct _reent *r, void *ptr, char *out, size_t size) {
  auto *f = static_cast<ExtFile *>(ptr);
  if (f->position >= f->size)
    return 0;
  uint32_t read = 0;
  size = std::min<uint64_t>(size, f->size - f->position);
  Result rc = FSFILE_Read(f->handle, &read, f->position, out, size);
  if (R_FAILED(rc))
    return failure(r, rc);
  f->position += read;
  return read;
}
ssize_t writeFile(struct _reent *r, void *ptr, const char *data, size_t size) {
  auto *f = static_cast<ExtFile *>(ptr);
  if (!f->writing || f->position > f->size || size > f->size - f->position) {
    r->_errno = ENOSPC;
    return -1;
  }
  uint32_t written = 0;
  Result rc = FSFILE_Write(f->handle, &written, f->position, data, size, 0);
  if (R_FAILED(rc))
    return failure(r, rc);
  f->position += written;
  return written;
}
off_t seekFile(struct _reent *r, void *ptr, off_t offset, int whence) {
  auto *f = static_cast<ExtFile *>(ptr);
  int64_t base = 0;
  if (whence == SEEK_CUR)
    base = f->position;
  else if (whence == SEEK_END)
    base = f->size;
  else if (whence != SEEK_SET)
    return invalid(r);
  int64_t pos = base + offset;
  if (pos < 0 || pos > 0x7fffffff)
    return invalid(r);
  f->position = pos;
  return pos;
}
void fileStat(struct stat *st, uint64_t size, bool dir) {
  std::memset(st, 0, sizeof(*st));
  st->st_mode = (dir ? S_IFDIR : S_IFREG) | 0777;
  st->st_size = size;
  st->st_nlink = 1;
}
int fstatFile(struct _reent *, void *ptr, struct stat *st) {
  auto *f = static_cast<ExtFile *>(ptr);
  fileStat(st, f->size, false);
  return 0;
}
int statPath(struct _reent *r, const char *name, struct stat *st) {
  Path p(name);
  if (!p.valid)
    return invalid(r);
  Handle f;
  Result rc = FSUSER_OpenFile(&f, archive, p.value, FS_OPEN_READ, 0);
  if (R_SUCCEEDED(rc)) {
    uint64_t size = 0;
    rc = FSFILE_GetSize(f, &size);
    FSFILE_Close(f);
    if (R_FAILED(rc))
      return failure(r, rc);
    fileStat(st, size, false);
    return 0;
  }
  rc = FSUSER_OpenDirectory(&f, archive, p.value);
  if (R_SUCCEEDED(rc)) {
    FSDIR_Close(f);
    fileStat(st, 0, true);
    return 0;
  }
  return failure(r, rc);
}
int unlinkPath(struct _reent *r, const char *name) {
  Path p(name);
  if (!p.valid)
    return invalid(r);
  Result rc = FSUSER_DeleteFile(archive, p.value);
  return R_FAILED(rc) ? failure(r, rc) : 0;
}
int renamePath(struct _reent *r, const char *from, const char *to) {
  Path a(from), b(to);
  if (!a.valid || !b.valid)
    return invalid(r);
  Result rc = FSUSER_RenameFile(archive, a.value, archive, b.value);
  if (R_SUCCEEDED(rc))
    return 0;
  // Emulate unsupported ExtData rename only into an absent destination.
  // The core keeps a durable journal and backup throughout this operation.
  struct stat st;
  if (statPath(r, to, &st) == 0) {
    r->_errno = EEXIST;
    return -1;
  }
  if (r->_errno != ENOENT)
    return -1;
  Handle input = 0, output = 0;
  rc = FSUSER_OpenFile(&input, archive, a.value, FS_OPEN_READ, 0);
  if (R_FAILED(rc))
    return failure(r, rc);
  uint64_t size = 0;
  rc = FSFILE_GetSize(input, &size);
  if (R_SUCCEEDED(rc))
    rc = FSUSER_CreateFile(archive, b.value, 0, size);
  bool created = R_SUCCEEDED(rc);
  if (created)
    rc = FSUSER_OpenFile(&output, archive, b.value, FS_OPEN_WRITE, 0);
  uint8_t buffer[4096];
  uint64_t pos = 0;
  while (R_SUCCEEDED(rc) && pos < size) {
    uint32_t n = std::min<uint64_t>(sizeof(buffer), size - pos), read = 0,
             written = 0;
    rc = FSFILE_Read(input, &read, pos, buffer, n);
    if (R_SUCCEEDED(rc) && read == n)
      rc = FSFILE_Write(output, &written, pos, buffer, n, 0);
    if (R_SUCCEEDED(rc) && (read != n || written != n)) {
      rc = -1;
      break;
    }
    pos += n;
  }
  if (output) {
    Result flush = FSFILE_Flush(output), close = FSFILE_Close(output);
    if (R_SUCCEEDED(rc))
      rc = R_FAILED(flush) ? flush : close;
  }
  FSFILE_Close(input);
  if (R_FAILED(rc)) {
    if (created)
      FSUSER_DeleteFile(archive, b.value);
    return failure(r, rc);
  }
  rc = FSUSER_DeleteFile(archive, a.value);
  return R_FAILED(rc) ? failure(r, rc) : 0;
}
int mkdirPath(struct _reent *r, const char *name, int) {
  Path p(name);
  if (!p.valid)
    return invalid(r);
  Result rc = FSUSER_CreateDirectory(archive, p.value, 0);
  return R_FAILED(rc) ? failure(r, rc) : 0;
}
int syncFile(struct _reent *r, void *ptr) {
  Result rc = FSFILE_Flush(static_cast<ExtFile *>(ptr)->handle);
  return R_FAILED(rc) ? failure(r, rc) : 0;
}
devoptab_t makeOps() {
  devoptab_t o{};
  o.name = "pksm";
  o.structSize = sizeof(ExtFile);
  o.open_r = openFile;
  o.close_r = closeFile;
  o.read_r = readFile;
  o.write_r = writeFile;
  o.seek_r = seekFile;
  o.fstat_r = fstatFile;
  o.stat_r = statPath;
  o.lstat_r = statPath;
  o.unlink_r = unlinkPath;
  o.rename_r = renamePath;
  o.mkdir_r = mkdirPath;
  o.fsync_r = syncFile;
  return o;
}
const devoptab_t ops = makeOps();
} // namespace
bool mountPKSM() {
  if (mounted)
    return true;
  uint32_t data[3] = {MEDIATYPE_SD, 0xEC100, 0};
  FS_Path p{PATH_BINARY, sizeof(data), data};
  if (R_FAILED(FSUSER_OpenArchive(&archive, ARCHIVE_EXTDATA, p)))
    return false;
  if (AddDevice(&ops) < 0) {
    FSUSER_CloseArchive(archive);
    archive = 0;
    return false;
  }
  mounted = true;
  return true;
}
void unmountPKSM() {
  if (!mounted)
    return;
  RemoveDevice("pksm:");
  FSUSER_CloseArchive(archive);
  archive = 0;
  mounted = false;
}
void commitPKSM() {
  Result rc = FSUSER_ControlArchive(archive, ARCHIVE_ACTION_COMMIT_SAVE_DATA,
                                    nullptr, 0, nullptr, 0);
  if (R_FAILED(rc))
    throw chestlink::Error(
        "Falha ao sincronizar ExtData. Reabra Chest Link antes do PKSM.");
}
bool allocatePKSM(const std::string &name, uint32_t size) {
  if (name.compare(0, 6, "pksm:/"))
    return false;
  Path p(name.c_str());
  if (!mounted || !p.valid)
    throw chestlink::Error("ExtData indisponivel.");
  if (chestlink::exists(name) && R_FAILED(FSUSER_DeleteFile(archive, p.value)))
    throw chestlink::Error("Falha ao preparar arquivo temporario em ExtData.");
  if (R_FAILED(FSUSER_CreateFile(archive, p.value, 0, size)))
    throw chestlink::Error("ExtData sem espaco/permissao. Desative Use ExtData "
                           "no PKSM para usar bancos no SD.");
  return true;
}
