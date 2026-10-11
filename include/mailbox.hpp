#pragma once
#include "core.hpp"

namespace chestlink {
constexpr unsigned MAILBOX_PORT = 40992;
constexpr uint32_t TARGET_DS = 1, TARGET_3DS = 2;
struct MailboxItem {
  std::string id, label;
  uint32_t target = 0;
  Offer offer;
  bool delivered = false;
};
struct MailboxPage {
  std::vector<MailboxItem> items;
  uint32_t next = 0, total = 0;
};
struct MailboxReceipt {
  std::string bank;
  bool confirmed = false, reused = false;
};
std::string mailboxId(uint32_t target, const Digest &);
// Each operation uses a fresh TCP connection; PC keeps an immutable copy.
std::string uploadMailbox(Wire &, uint32_t pin, uint32_t target,
                          const std::string &label, const Package &,
                          Progress = {});
MailboxPage listMailbox(Wire &, uint32_t pin, uint32_t target,
                        bool includeDelivered = false, uint32_t offset = 0);
MailboxReceipt fetchMailbox(Wire &, uint32_t pin, uint32_t target,
                            const std::string &id, const Store &, Accept,
                            Progress = {}, bool markDelivered = true);
} // namespace chestlink
