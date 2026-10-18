// Executes the real native ExtData adapter against a fixed-size mock FS.
// This checks the adapter's logic; console permissions/services need hardware.
#include "../platform/3ds/extdata.hpp"
#include "core.hpp"
#include <3ds.h>
#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <map>
#include <set>
#include <sys/iosupport.h>
namespace {
std::map<std::string, std::string> files;
std::set<std::string> dirs = {"/"};
struct Open {
  std::string path;
  uint32_t mode;
};
std::map<Handle, Open> handles;
const devoptab_t *device = nullptr;
Handle nextHandle = 1;
bool denyMount = false, renameSupported = true, failWrite = false;
unsigned commits = 0, passed = 0;
void check(bool ok, const char *what) {
  if (!ok)
    throw std::runtime_error(what);
}
std::string path(FS_Path p) {
  check(p.type == PATH_UTF16, "UTF16 path");
  auto *u = static_cast<const uint16_t *>(p.data);
  std::string s;
  for (unsigned i = 0; i + 1 < p.size / 2; ++i) {
    check(u[i] < 128, "ASCII test paths");
    s += char(u[i]);
  }
  return s;
}
struct File {
  _reent r;
  std::vector<uint8_t> state;
  bool opened = false;
  File(const char *name, int mode) : state(device->structSize) {
    opened = device->open_r(&r, state.data(), name, mode, 0) == 0;
  }
  ~File() {
    if (opened)
      device->close_r(&r, state.data());
  }
};
void group(const char *name, const std::function<void()> &f) {
  f();
  ++passed;
  std::cout << "PASS ExtData " << name << '\n';
}
} // namespace
ssize_t utf8_to_utf16(uint16_t *out, const uint8_t *in, size_t n) {
  size_t len = std::strlen(reinterpret_cast<const char *>(in));
  if (len > n)
    return -1;
  for (size_t i = 0; i < len; ++i)
    out[i] = in[i];
  return len;
}
Result FSUSER_OpenArchive(FS_Archive *a, uint32_t id, FS_Path p) {
  check(id == ARCHIVE_EXTDATA && p.type == PATH_BINARY && p.size == 12,
        "correct archive");
  auto *data = static_cast<const uint32_t *>(p.data);
  check(data[0] == MEDIATYPE_SD && data[1] == 0xEC100 && data[2] == 0,
        "PKSM archive ID");
  if (denyMount)
    return -1003;
  *a = 7;
  return 0;
}
Result FSUSER_CloseArchive(FS_Archive) { return 0; }
Result FSUSER_OpenFile(Handle *h, FS_Archive, FS_Path p, uint32_t mode,
                       uint32_t) {
  auto s = path(p);
  if (!files.count(s))
    return Result(0xC8804478u);
  *h = nextHandle++;
  handles[*h] = {s, mode};
  return 0;
}
Result FSUSER_OpenDirectory(Handle *h, FS_Archive, FS_Path p) {
  auto s = path(p);
  if (!dirs.count(s))
    return Result(0xC92044FAu);
  *h = nextHandle++;
  handles[*h] = {s, 0};
  return 0;
}
Result FSUSER_CreateDirectory(FS_Archive, FS_Path p, uint32_t) {
  return dirs.insert(path(p)).second ? 0 : Result(0xC82044BEu);
}
Result FSUSER_CreateFile(FS_Archive, FS_Path p, uint32_t, uint64_t n) {
  auto s = path(p);
  if (files.count(s))
    return Result(0xC82044BEu);
  files[s] = std::string(n, char(0));
  return 0;
}
Result FSUSER_DeleteFile(FS_Archive, FS_Path p) {
  return files.erase(path(p)) ? 0 : -1001;
}
Result FSUSER_RenameFile(FS_Archive, FS_Path a, FS_Archive, FS_Path b) {
  if (!renameSupported)
    return -1005;
  auto from = path(a), to = path(b);
  if (files.count(to))
    return -1002;
  if (!files.count(from))
    return -1001;
  files[to] = files[from];
  files.erase(from);
  return 0;
}
Result FSUSER_ControlArchive(FS_Archive, uint32_t action, const void *,
                             uint32_t, void *, uint32_t) {
  check(action == ARCHIVE_ACTION_COMMIT_SAVE_DATA, "commit action");
  ++commits;
  return 0;
}
Result FSFILE_GetSize(Handle h, uint64_t *n) {
  *n = files.at(handles.at(h).path).size();
  return 0;
}
Result FSFILE_Read(Handle h, uint32_t *read, uint64_t pos, void *out,
                   uint32_t n) {
  auto &s = files.at(handles.at(h).path);
  *read = pos >= s.size() ? 0 : std::min<uint64_t>(n, s.size() - pos);
  std::memcpy(out, s.data() + std::min<uint64_t>(pos, s.size()), *read);
  return 0;
}
Result FSFILE_Write(Handle h, uint32_t *written, uint64_t pos, const void *data,
                    uint32_t n, uint32_t) {
  auto &handle = handles.at(h);
  check(handle.mode & FS_OPEN_WRITE, "write permission");
  auto &s = files.at(handle.path);
  if (pos + n > s.size())
    return -1004;
  if (failWrite)
    return -1005;
  std::memcpy(&s[0] + pos, data, n);
  *written = n;
  return 0;
}
Result FSFILE_Flush(Handle) { return 0; }
Result FSFILE_Close(Handle h) {
  handles.erase(h);
  return 0;
}
Result FSDIR_Close(Handle h) {
  handles.erase(h);
  return 0;
}
int AddDevice(const devoptab_t *o) {
  check(device == nullptr, "single device");
  device = o;
  return 5;
}
int RemoveDevice(const char *name) {
  check(std::string(name) == "pksm:", "correct unmount");
  device = nullptr;
  return 0;
}
namespace chestlink {
bool exists(const std::string &s) {
  if (!device)
    return false;
  _reent r;
  struct stat st;
  return device->stat_r(&r, s.c_str(), &st) == 0;
}
} // namespace chestlink
int main() {
  try {
    group("permission refusal and archive registration", [] {
      denyMount = true;
      check(!mountPKSM() && device == nullptr, "mount refusal");
      denyMount = false;
      check(mountPKSM() && device != nullptr, "mounted");
    });
    group("fixed-size allocation, read/write and seek", [] {
      check(allocatePKSM("pksm:/box.bnk", 16), "allocation handled");
      File f("pksm:/box.bnk", O_RDWR);
      check(f.opened, "open read/write");
      check(device->write_r(&f.r, f.state.data(), "0123456789abcdef", 16) == 16,
            "write exact bytes");
      check(device->seek_r(&f.r, f.state.data(), -4, SEEK_END) == 12,
            "seek from end");
      char b[4];
      check(device->read_r(&f.r, f.state.data(), b, 4) == 4 &&
                !std::memcmp(b, "cdef", 4),
            "read unchanged");
      check(device->seek_r(&f.r, f.state.data(), -1, SEEK_SET) < 0,
            "negative seek refused");
    });
    group("fixed-size boundary and truncation protection", [] {
      File f("pksm:/box.bnk", O_RDWR);
      check(f.opened, "open");
      check(device->seek_r(&f.r, f.state.data(), 15, SEEK_SET) == 15, "seek");
      check(device->write_r(&f.r, f.state.data(), "xx", 2) < 0,
            "overflow refused");
      File truncated("pksm:/box.bnk", O_TRUNC | O_RDWR);
      check(!truncated.opened, "O_TRUNC refused");
      check(files.at("/box.bnk") == "0123456789abcdef", "original unchanged");
    });
    group("native rename does not overwrite destination", [] {
      _reent r;
      files["/existing.bnk"] = "keep";
      check(device->rename_r(&r, "pksm:/box.bnk", "pksm:/existing.bnk") < 0,
            "existing protected");
      check(files.at("/existing.bnk") == "keep" && files.count("/box.bnk"),
            "both preserved");
      check(device->rename_r(&r, "pksm:/box.bnk", "pksm:/new.bnk") == 0,
            "new rename");
    });
    group("unsupported rename fallback copies exact file", [] {
      renameSupported = false;
      files["/stage"] = std::string(10080, 'p');
      _reent r;
      check(device->rename_r(&r, "pksm:/stage", "pksm:/imported.bnk") == 0,
            "fallback rename");
      check(files.at("/imported.bnk") == std::string(10080, 'p') &&
                !files.count("/stage"),
            "fallback content");
    });
    group("failed fallback write keeps source and removes partial", [] {
      files["/stage"] = "preserve";
      failWrite = true;
      _reent r;
      check(device->rename_r(&r, "pksm:/stage", "pksm:/broken.bnk") < 0,
            "write fails");
      failWrite = false;
      check(files.at("/stage") == "preserve" && !files.count("/broken.bnk"),
            "source preserved");
    });
    group("firmware FS errors translate to POSIX errno", [] {
      _reent r;
      struct stat st;
      check(device->stat_r(&r, "pksm:/absent", &st) < 0 && r._errno == ENOENT,
            "FS not-found translation");
      check(device->mkdir_r(&r, "pksm:/", 0) < 0 && r._errno == EEXIST,
            "FS already-existing directory translation");
    });
    group("directory stat and scoped allocator", [] {
      _reent r;
      struct stat st;
      check(device->mkdir_r(&r, "pksm:/banks", 0) == 0, "mkdir");
      check(device->stat_r(&r, "pksm:/banks", &st) == 0 && S_ISDIR(st.st_mode),
            "directory");
      check(!allocatePKSM("sdmc:/bank.bnk", 16), "other device ignored");
    });
    group("commit, closed handles and unmount", [] {
      commitPKSM();
      check(commits == 1, "commit sent");
      check(handles.empty(), "no open handles");
      unmountPKSM();
      check(device == nullptr, "unmounted");
    });
    std::cout << "ALL " << passed << " EXTDATA ADAPTER TEST GROUPS PASSED\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "FAIL ExtData " << e.what() << '\n';
    return 1;
  }
}
