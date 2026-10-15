#pragma once
#include <cstddef>
#include <sys/stat.h>
#include <sys/types.h>
struct _reent {
  int _errno = 0;
};
struct devoptab_t {
  const char *name;
  size_t structSize;
  int (*open_r)(_reent *, void *, const char *, int, int);
  int (*close_r)(_reent *, void *);
  ssize_t (*write_r)(_reent *, void *, const char *, size_t);
  ssize_t (*read_r)(_reent *, void *, char *, size_t);
  off_t (*seek_r)(_reent *, void *, off_t, int);
  int (*fstat_r)(_reent *, void *, struct stat *);
  int (*stat_r)(_reent *, const char *, struct stat *);
  int (*lstat_r)(_reent *, const char *, struct stat *);
  int (*unlink_r)(_reent *, const char *);
  int (*rename_r)(_reent *, const char *, const char *);
  int (*mkdir_r)(_reent *, const char *, int);
  int (*fsync_r)(_reent *, void *);
};
int AddDevice(const devoptab_t *);
int RemoveDevice(const char *);
