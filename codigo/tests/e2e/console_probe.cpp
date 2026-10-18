// Test-only entry point. The probe builder substitutes this file for app.cpp
// in an isolated build tree; normal/release sources and binaries are untouched.
#ifndef CHEST_LINK_E2E
#error This entry point is only for isolated test builds.
#endif
#include "core.hpp"
#include "graphics.hpp"
#include "mailbox.hpp"
#include "network.hpp"
#include "platform.hpp"
#include "pokemon.hpp"
#include "update.hpp"
#include "version.hpp"
#include <cstdio>
#include <malloc.h>
#include <memory>
#ifdef CL_NDS
#include <dswifi9.h>
#include <arpa/inet.h>
#include <nds.h>
#else
#include <3ds.h>
#endif
using namespace chestlink;
namespace {
#ifdef CL_NDS
const std::string root = "fat:/chest-link-e2e";
#else
const std::string root = "sdmc:/chest-link-e2e";
#endif
Json result;
void text(const std::string &key, const std::string &value) {
  result.object[key] = Json::text(value);
}
void number(const std::string &key, uint32_t value) {
  result.object[key] = Json::integer(value);
}
void stage(const char *name) {
  text("stage", name);
  const std::string diagnostic = "CHESTLINK_E2E:" + result.dump();
#ifdef CL_NDS
  // melonDS/no$gba debug messages have a 120-byte limit. Emit one small JSON
  // field per line, and status last so the runner sees a complete result.
  for (const auto &field : result.object) {
    if (field.first == "status") continue;
    Json record;
    record.object[field.first] = field.second;
    if (record.object[field.first].kind == Json::STRING &&
        record.object[field.first].string.size() > 80)
      record.object[field.first].string.resize(80);
    const auto line = "CHESTLINK_E2E:" + record.dump() + "\n";
    nocashMessage(line.c_str());
  }
  Json status; status.object["status"] = result.object.at("status");
  const auto line = "CHESTLINK_E2E:" + status.dump() + "\n";
  nocashMessage(line.c_str());
#else
  svcOutputDebugString(diagnostic.c_str(), diagnostic.size());
#endif
  writeText(root + "/result.json", result.dump());
  gui::notice("Chest Link E2E", name, "Private FireRed fixture");
}
Digest hashFile(const std::string &path) {
  FILE *file = std::fopen(path.c_str(), "rb");
  if (!file) throw Error("Probe could not open file for hash verification.");
  Sha256 sha;
  uint8_t buffer[4096];
  size_t n;
  while ((n = std::fread(buffer, 1, sizeof(buffer), file))) sha.update(buffer, n);
  const bool bad = std::ferror(file);
  std::fclose(file);
  if (bad) throw Error("Probe file read failed.");
  return sha.finish();
}
Progress updateProgress() {
  auto previous = std::make_shared<uint32_t>(UINT32_MAX);
  return [previous](uint32_t done, uint32_t total) {
    const int percent = total ? static_cast<int>(uint64_t(done) * 100 / total) : 0;
    number("downloaded_bytes", done);
    number("download_total_bytes", total);
    if (done != *previous) {
      *previous = done;
      gui::notice("Baixando atualizacao",
                  std::to_string(done) + " / " + std::to_string(total),
                  "B: cancelar", percent);
    }
    platform::frame();
    return platform::alive() && !(platform::keys() & platform::B);
  };
}
void inspect(const Store &store, const BankInfo &info) {
  Bank bank(store, info);
  unsigned occupied = 0, valid = 0;
  uint8_t box[BOX_BYTES];
  for (unsigned i = 0; i < bank.boxes(); ++i) {
    bank.readBox(i, box);
    for (unsigned s = 0; s < SLOTS; ++s) {
      auto p = previewPokemon(box + s * ENTRY);
      if (p.occupied) {
        ++occupied;
        if (p.valid && p.generation == 6) ++valid;
      }
    }
  }
  if (occupied != valid || !valid) throw Error("Private PK3 preview validation failed.");
  number("boxes", bank.boxes()); number("pokemon", occupied);
  number("valid_pk3", valid); text("bank", info.name);
  text("bank_sha256", hex(hashFile(bank.path())));
}
}
int runApp() {
  try {
    platform::init();
    Json config = Json::parse(readText(root + "/config.json"));
    const auto getText = [&](const char *key) { return config.object.at(key).string; };
    const auto getNumber = [&](const char *key) { return config.object.at(key).number; };
    const std::string mode = getText("mode");
    text("mode", mode); text("status", "RUNNING");
    number("version", APP_VERSION_CODE);
    Store store{"E2E", root + "/store", MAX_BOXES,
#ifdef CL_NDS
                CHEST_GENS,
#else
                PKSM_GENS,
#endif
                {}};
    recover(store);
    stage("storage_ready");
    if (mode == "preview" || mode == "upload" || mode == "direct_send") {
      BankInfo source;
      for (const auto &info : listBanks(store))
        if (info.name == "firered") source = info;
      if (source.name.empty()) throw Error("Private FireRed bank is missing.");
      inspect(store, source);
      stage("private_pk3_preview_ok");
    }
    if (mode != "preview") {
      platform::network();
      text("local_ip", platform::ip());
#ifdef CL_NDS
      in_addr gateway{}, mask{}, dns1{}, dns2{};
      Wifi_GetIPInfo(&gateway, &mask, &dns1, &dns2);
      char ip[32]{};
      inet_ntop(AF_INET, &gateway, ip, sizeof(ip)); text("gateway", ip);
      inet_ntop(AF_INET, &mask, ip, sizeof(ip)); text("netmask", ip);
      number("assoc_status", Wifi_AssocStatus());
#endif
      stage("network_ready");
      const unsigned pin = getNumber("pin"), port = getNumber("port");
      int idleListener = -1;
      const auto idle = config.object.find("ui_idle_ms");
      if (idle != config.object.end() && idle->second.number) {
        BankInfo info;
        for (const auto &entry : listBanks(store)) if (entry.name == "firered") info = entry;
        Bank bank(store, info);
        gui::BoxScreen screen; screen.bank = "FireRed"; screen.name = bank.boxName(0);
        screen.boxes = bank.boxes(); screen.consult = true;
        auto box = std::make_unique<uint8_t[]>(BOX_BYTES); bank.readBox(0, box.get());
        for (unsigned i = 0; i < SLOTS; ++i) screen.pokemon[i] = previewPokemon(box.get() + i * ENTRY);
        const auto listen = config.object.find("idle_listener");
        if (listen != config.object.end() && listen->second.number)
          idleListener = Connection::listen();
        stage("ui_idle");
        const auto draw = config.object.find("idle_draw");
        if (draw == config.object.end() || draw->second.number) gui::box(screen);
        const uint64_t finish = platform::milliseconds() + idle->second.number;
        while (platform::milliseconds() < finish) {
          platform::frame();
          if (idleListener >= 0) { auto incoming = Connection::tryAccept(idleListener); }
        }
#ifdef CL_NDS
        number("heap_free", mallinfo().fordblks);
        number("heap_available", getHeapLimit() - getHeapEnd());
#endif
        number("idle_listener", idleListener >= 0); stage("ui_idle_done");
      }
      if (mode == "upload" || mode == "direct_send") {
        BankInfo info;
        for (const auto &bank : listBanks(store)) if (bank.name == "firered") info = bank;
        Bank bank(store, info);
        std::vector<uint32_t> masks(bank.boxes(), 0x3FFFFFFF);
        Package package = exportSelection(store, bank, masks);
        text("package_sha256", hex(package.offer.digest));
        try {
          stage("connecting");
          auto connection = Connection::connect(getText("ip"), port, 15000);
          auto wire = connection.wire();
          stage("connected");
          if (mode == "upload")
            text("item_id", uploadMailbox(wire, pin, 0, "Private FireRed test", package));
          else
            text("destination_bank", sendPackage(wire, pin, package));
          discard(package);
          inspect(store, info);
        } catch (...) { discard(package); throw; }
      } else if (mode == "fetch") {
        auto connection = Connection::connect(getText("ip"), port, 15000);
        auto wire = connection.wire();
        auto listing = listMailbox(wire, pin, getNumber("target"), true);
        number("listed_items", listing.total);
        auto transfer = Connection::connect(getText("ip"), port, 15000);
        auto transferWire = transfer.wire();
        auto receipt = fetchMailbox(transferWire, pin, getNumber("target"),
                                   getText("item_id"), store, [](const Offer &) { return true; });
        if (!receipt.confirmed) throw Error("Mailbox receipt was not confirmed.");
        text("destination_bank", receipt.bank);
        for (const auto &info : listBanks(store)) if (info.name == receipt.bank) inspect(store, info);
      } else if (mode == "direct_receive") {
        int listener = Connection::listen(port);
        stage("listening");
        try {
          auto connection = Connection::accept(listener);
          Connection::close(listener); listener = -1;
          auto wire = connection.wire();
          std::string name = receivePackage(wire, pin, store, [](const Offer &) { return true; });
          text("destination_bank", name);
          for (const auto &info : listBanks(store)) if (info.name == name) inspect(store, info);
        } catch (...) { Connection::close(listener); throw; }
      } else if (mode == "update") {
        auto connection = Connection::connect(getText("ip"), port, 15000);
        auto wire = connection.wire();
        makeDirs(root + "/install");
        const auto manualUpdate = config.object.find("manual_update");
        const bool useUpdatePrompt = manualUpdate != config.object.end() &&
                                     manualUpdate->second.number != 0;
        auto acceptUpdate = [useUpdatePrompt](uint32_t version, uint32_t bytes,
                                              uint32_t local) {
          if (!useUpdatePrompt) return true;
          stage("update_offer");
          gui::notice("Atualizacao disponivel",
                      "Versao instalada: " + appVersionText(local) +
                          "\nNova versao: " + appVersionText(version) +
                          "\nTamanho: " + std::to_string(bytes / 1024) + " KiB",
                      "A: aceitar    B: cancelar");
          for (;;) {
            platform::frame();
            const unsigned keys = platform::keys();
            if (keys & platform::B) {
              stage("update_declined");
              return false;
            }
            if (keys & platform::A) {
              stage("update_accepted");
              return true;
            }
          }
        };
#ifdef CL_NDS
        const std::string path = root + "/install/ChestLink_DS.nds";
        auto update = updateNDS(wire, pin, getNumber("installed_version"), path,
#else
        const std::string path = root + "/install/ChestLink_3DS.3dsx";
        const std::string previousHash = hex(hashFile(path));
        auto update = update3DS(wire, pin, getNumber("installed_version"), path,
#endif
                                acceptUpdate,
                                updateProgress());
        number("update_state", static_cast<uint32_t>(update.state));
        number("update_version", update.version); number("update_bytes", update.bytes);
        if (update.state == UpdateState::installed) text("installed_sha256", hex(hashFile(path)));
#ifdef CL_3DS
        if (update.state == UpdateState::installed) {
          const std::string backupHash = hex(hashFile(path + ".previous"));
          if (backupHash != previousHash) throw Error("Updater changed the previous executable backup.");
          text("previous_sha256", previousHash); text("backup_sha256", backupHash);
        }
#endif
        for (const auto &info : listBanks(store)) if (info.name == "firered") inspect(store, info);
      } else throw Error("Unknown test-only probe mode.");
      Connection::close(idleListener);
    }
    text("status", "PASS"); stage("complete");
  } catch (const std::exception &error) {
    text("status", "FAIL"); text("error", error.what());
    try { stage("failed"); } catch (...) {}
  }
  // Give the UI a visible final state; filesystem result is the assertion input.
  const uint64_t until = platform::milliseconds() + 3000;
  while (platform::alive() && platform::milliseconds() < until) platform::frame();
  platform::shutdown();
  return 0;
}
