#pragma once
#include "core.hpp"

// Shared bounded framing and streaming for direct and mailbox transports.
namespace chestlink::wireio {
void reply(Wire &, bool, const std::string &);
std::string result(Wire &);
void encode(const Offer &, uint8_t *);
Offer decode(const uint8_t *);
void preflight(const Offer &, const Store &);
void streamOut(Wire &, const std::string &, unsigned bytes, unsigned &done,
               unsigned total, Progress);
void streamIn(Wire &, const std::string &, unsigned bytes, unsigned &done,
              unsigned total, Progress);
} // namespace chestlink::wireio
