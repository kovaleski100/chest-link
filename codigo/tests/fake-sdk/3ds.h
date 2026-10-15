#pragma once
#include <cstddef>
#include <cstdint>
#include <sys/types.h>
using Result = int32_t;
using Handle = uint32_t;
using FS_Archive = uint64_t;
struct FS_Path {
  uint32_t type, size;
  const void *data;
};
constexpr uint32_t PATH_BINARY = 2, PATH_UTF16 = 4, MEDIATYPE_SD = 1,
                   ARCHIVE_EXTDATA = 6;
constexpr uint32_t FS_OPEN_READ = 1, FS_OPEN_WRITE = 2,
                   ARCHIVE_ACTION_COMMIT_SAVE_DATA = 0;
constexpr int RD_NOT_FOUND = 1001, RD_ALREADY_EXISTS = 1002,
              RD_NOT_AUTHORIZED = 1003, RS_OUTOFRESOURCE = 6;
#define R_FAILED(x) ((x) < 0)
#define R_SUCCEEDED(x) ((x) >= 0)
#define R_DESCRIPTION(x) (-(x))
#define R_SUMMARY(x) ((x) == -1004 ? RS_OUTOFRESOURCE : 0)
ssize_t utf8_to_utf16(uint16_t *, const uint8_t *, size_t);
Result FSUSER_OpenArchive(FS_Archive *, uint32_t, FS_Path);
Result FSUSER_CloseArchive(FS_Archive);
Result FSUSER_OpenFile(Handle *, FS_Archive, FS_Path, uint32_t, uint32_t);
Result FSUSER_OpenDirectory(Handle *, FS_Archive, FS_Path);
Result FSUSER_CreateDirectory(FS_Archive, FS_Path, uint32_t);
Result FSUSER_CreateFile(FS_Archive, FS_Path, uint32_t, uint64_t);
Result FSUSER_DeleteFile(FS_Archive, FS_Path);
Result FSUSER_RenameFile(FS_Archive, FS_Path, FS_Archive, FS_Path);
Result FSUSER_ControlArchive(FS_Archive, uint32_t, const void *, uint32_t,
                             void *, uint32_t);
Result FSFILE_GetSize(Handle, uint64_t *);
Result FSFILE_Read(Handle, uint32_t *, uint64_t, void *, uint32_t);
Result FSFILE_Write(Handle, uint32_t *, uint64_t, const void *, uint32_t,
                    uint32_t);
Result FSFILE_Flush(Handle);
Result FSFILE_Close(Handle);
Result FSDIR_Close(Handle);
