CXX ?= g++
FLAGS := -std=c++17 -g -Wall -Wextra -Werror -pthread -DCL_HOST -Iinclude
ASAN_OPTIONS ?= detect_leaks=1
CORE := source/json.cpp source/sha256.cpp source/bank.cpp source/protocol.cpp source/mailbox.cpp source/update.cpp host/native_saves/raw_file_save_source.cpp
NETWORK := source/network.cpp platform/host/runtime.cpp
.PHONY: all test nds-wpa-test nds-wpa-sanitize nds-raw-rx-test nds-raw-rx-sanitize nds-tx-retry-test nds-association-test nds-netif-test nds-packet-queue-test nds-packet-queue-sanitize nds-dhcp-test nds-dhcp-sanitize nds-discovery-timeout-test mailbox-test gui-test gui-sanitize sanitize mailbox-sanitize ds 3ds consoles release console-ports-test console-ports-sanitize clean e2e e2e-server e2e-protocol e2e-ds e2e-3ds e2e-ds-to-pc e2e-hgss e2e-harness-test
all: build/chest-link-cli
build:
	mkdir -p build
build/chest-link-cli: $(CORE) $(NETWORK) tools/host.cpp $(wildcard include/*.hpp) | build
	$(CXX) $(FLAGS) -O2 $(CORE) $(NETWORK) tools/host.cpp -o $@
build/tests: $(CORE) $(NETWORK) tests/tests.cpp $(wildcard include/*.hpp) | build
	$(CXX) $(FLAGS) -O2 $(CORE) $(NETWORK) tests/tests.cpp -o $@
build/mailbox-probe: $(CORE) $(NETWORK) tests/mailbox_probe.cpp $(wildcard include/*.hpp) | build
	$(CXX) $(FLAGS) -O2 $(CORE) $(NETWORK) tests/mailbox_probe.cpp -o $@
build/update-probe: $(CORE) $(NETWORK) tests/update_probe.cpp $(wildcard include/*.hpp) | build
	$(CXX) $(FLAGS) -O2 $(CORE) $(NETWORK) tests/update_probe.cpp -o $@
build/discovery-probe: $(NETWORK) tests/discovery_probe.cpp $(wildcard include/*.hpp) | build
	$(CXX) $(FLAGS) -O2 $(NETWORK) tests/discovery_probe.cpp -o $@
build/extdata-tests: platform/3ds/extdata.cpp platform/3ds/extdata.hpp tests/extdata_test.cpp tests/fake-sdk/3ds.h tests/fake-sdk/sys/iosupport.h | build
	$(CXX) $(FLAGS) -O2 -Itests/fake-sdk platform/3ds/extdata.cpp tests/extdata_test.cpp -o $@
build/pksm-storage-tests: platform/3ds/pksm_storage.hpp tests/pksm_storage_test.cpp | build
	$(CXX) $(FLAGS) -O2 tests/pksm_storage_test.cpp -o $@
build/nds-update-cleanup-tests: include/nds_update_cleanup.hpp tests/nds_update_cleanup_test.cpp | build
	$(CXX) $(FLAGS) -O2 tests/nds_update_cleanup_test.cpp -o $@
DSWIFI := third_party/dswifi
NDS_WPA_CRYPTO := $(wildcard $(DSWIFI)/mbedtls/library/*.twl.c) $(DSWIFI)/source/arm7/twl/ieee/wpa.twl.c $(DSWIFI)/source/arm7/ntr/ccmp.c
NDS_WPA_FLAGS := -std=gnu17 -g -Wall -Wextra -Werror -DARM7 -Itests/fake-nds-sdk -I$(DSWIFI)/source -I$(DSWIFI)/include -I$(DSWIFI)/mbedtls/include -I$(DSWIFI)/source/arm7/twl/crypto
NDS_WPA_HEADERS := $(wildcard tests/fake-nds-sdk/*.h tests/fake-nds-sdk/nds/*.h tests/fake-nds-sdk/nds/arm9/*.h $(DSWIFI)/source/arm7/ntr/*.h $(DSWIFI)/source/arm7/twl/ieee/*.h $(DSWIFI)/source/common/*.h $(DSWIFI)/include/*.h $(DSWIFI)/source/arm7/twl/crypto/mbedtls/*.h)
build/nds-wpa-tests: tests/nds_wpa_test.c $(DSWIFI)/source/arm7/ntr/wpa.c $(NDS_WPA_CRYPTO) $(NDS_WPA_HEADERS) | build
	$(CC) $(NDS_WPA_FLAGS) -O2 tests/nds_wpa_test.c $(NDS_WPA_CRYPTO) -o $@
nds-wpa-test: build/nds-wpa-tests
	./build/nds-wpa-tests
nds-wpa-sanitize: | build
	$(CC) $(NDS_WPA_FLAGS) -O1 -fno-omit-frame-pointer -fsanitize=address,undefined tests/nds_wpa_test.c $(NDS_WPA_CRYPTO) -o build/nds-wpa-sanitized
	ASAN_OPTIONS="$(ASAN_OPTIONS)" ./build/nds-wpa-sanitized
build/nds-raw-rx-tests: tests/nds_raw_rx_test.c tests/nds_wpa_test.c $(DSWIFI)/source/arm7/ntr/rx_queue.c $(DSWIFI)/source/arm7/ntr/wpa.c $(NDS_WPA_CRYPTO) $(NDS_WPA_HEADERS) | build
	$(CC) $(NDS_WPA_FLAGS) -O2 tests/nds_raw_rx_test.c $(NDS_WPA_CRYPTO) -o $@
nds-raw-rx-test: build/nds-raw-rx-tests
	./build/nds-raw-rx-tests
nds-raw-rx-sanitize: | build
	$(CC) $(NDS_WPA_FLAGS) -O1 -fno-omit-frame-pointer -fsanitize=address,undefined tests/nds_raw_rx_test.c $(NDS_WPA_CRYPTO) -o build/nds-raw-rx-sanitized
	ASAN_OPTIONS="$(ASAN_OPTIONS)" ./build/nds-raw-rx-sanitized
build/nds-tx-retry-tests: tests/nds_tx_retry_test.c $(DSWIFI)/source/arm7/ntr/tx_queue.c $(NDS_WPA_HEADERS) | build
	$(CC) $(NDS_WPA_FLAGS) -ffunction-sections -fdata-sections -O2 tests/nds_tx_retry_test.c -Wl,--gc-sections -o $@
nds-tx-retry-test: build/nds-tx-retry-tests
	./build/nds-tx-retry-tests
build/nds-association-tests: tests/nds_association_test.c $(DSWIFI)/source/arm9/access_point.c $(NDS_WPA_HEADERS) | build
	$(CC) -std=gnu17 -g -Wall -Wextra -Werror -DARM9 -DDSWIFI_ENABLE_LWIP -Itests/fake-nds-sdk -I$(DSWIFI)/source -I$(DSWIFI)/include -O2 tests/nds_association_test.c -o $@
nds-association-test: build/nds-association-tests
	./build/nds-association-tests
# glibc marks gethostname nonnull; the DS implementation still validates NULL.
NDS_NETIF_FLAGS := -std=gnu17 -g -Wall -Wextra -Werror -Wno-nonnull-compare -DARM9 -DDSWIFI_ENABLE_LWIP -Itests/fake-nds-sdk -I$(DSWIFI)/source -I$(DSWIFI)/include -I$(DSWIFI)/lwip/include -I$(DSWIFI)/source/arm9/lwip/include -ffunction-sections -fdata-sections
build/nds-netif-tests: tests/nds_netif_test.c $(DSWIFI)/source/arm9/lwip/netif.c $(NDS_WPA_HEADERS) | build
	$(CC) $(NDS_NETIF_FLAGS) -O2 tests/nds_netif_test.c -Wl,--gc-sections -o $@
nds-netif-test: build/nds-netif-tests
	./build/nds-netif-tests
build/nds-packet-queue-tests: tests/nds_packet_queue_test.c $(DSWIFI)/source/arm9/lwip/rx_tx.c $(NDS_WPA_HEADERS) | build
	$(CC) $(NDS_NETIF_FLAGS) -O2 tests/nds_packet_queue_test.c -Wl,--gc-sections -o $@
nds-packet-queue-test: build/nds-packet-queue-tests
	./build/nds-packet-queue-tests
nds-packet-queue-sanitize: | build
	$(CC) $(NDS_NETIF_FLAGS) -O1 -fno-omit-frame-pointer -fsanitize=address,undefined tests/nds_packet_queue_test.c -Wl,--gc-sections -o build/nds-packet-queue-sanitized
	ASAN_OPTIONS="$(ASAN_OPTIONS)" ./build/nds-packet-queue-sanitized
NDS_DHCP_CORE := $(wildcard $(DSWIFI)/lwip/source/core/*.c $(DSWIFI)/lwip/source/core/ipv4/*.c $(DSWIFI)/lwip/source/core/ipv6/*.c) $(DSWIFI)/lwip/source/netif/ethernet.c
# Vendored DHCP6 has parameters used only by diagnostics (disabled on host).
NDS_DHCP_FLAGS := -std=gnu17 -g -Wall -Wextra -Werror -Wno-unused-parameter -DARM9 -DDSWIFI_ENABLE_LWIP -Itests/dhcp-sdk -Itests/fake-nds-sdk -I$(DSWIFI)/source -I$(DSWIFI)/include -I$(DSWIFI)/lwip/include -I$(DSWIFI)/source/arm9/lwip/include -ffunction-sections -fdata-sections
build/nds-dhcp-tests: tests/nds_dhcp_test.c tests/dhcp-sdk/lwipopts.h $(DSWIFI)/source/arm9/lwip/rx_tx.c $(NDS_DHCP_CORE) $(NDS_WPA_HEADERS) | build
	$(CC) $(NDS_DHCP_FLAGS) -O2 tests/nds_dhcp_test.c $(NDS_DHCP_CORE) -Wl,--gc-sections -o $@
nds-dhcp-test: build/nds-dhcp-tests
	./build/nds-dhcp-tests
nds-dhcp-sanitize: | build
	$(CC) $(NDS_DHCP_FLAGS) -O1 -fno-omit-frame-pointer -fsanitize=address,undefined tests/nds_dhcp_test.c $(NDS_DHCP_CORE) -Wl,--gc-sections -o build/nds-dhcp-sanitized
	ASAN_OPTIONS="$(ASAN_OPTIONS)" ./build/nds-dhcp-sanitized
build/network-status-tests: tests/network_status_test.cpp include/network_status.hpp | build
	$(CXX) $(FLAGS) -O2 tests/network_status_test.cpp -o $@
build/nds-discovery-timeout-tests: source/network.cpp tests/nds_discovery_timeout_test.cpp tests/fake-nds-sdk/nds_network.h $(wildcard include/*.hpp) | build
	$(CXX) -std=c++17 -g -Wall -Wextra -Werror -pthread -DCL_NDS -Iinclude -Itests/fake-nds-sdk -include tests/fake-nds-sdk/nds_network.h -O2 source/network.cpp tests/nds_discovery_timeout_test.cpp -Wl,--wrap=sendto,--wrap=recvfrom,--wrap=connect,--wrap=select,--wrap=recv -o $@
nds-discovery-timeout-test: build/nds-discovery-timeout-tests
	./build/nds-discovery-timeout-tests
build/image-scaling-tests: tests/image_scaling_test.cpp source/graphics.cpp $(wildcard include/*.hpp) | build
	$(CXX) $(FLAGS) -O2 -ffunction-sections -fdata-sections tests/image_scaling_test.cpp -Wl,--gc-sections -o $@
build/console-ports-tests: tests/console_ports_test.cpp $(CORE) $(wildcard include/*.hpp) platform/3ds/network_snapshot.hpp platform/3ds/app_location.hpp | build
	$(CXX) $(FLAGS) -O2 tests/console_ports_test.cpp $(CORE) -o $@
build/3ds-network-tests: tests/3ds_network_test.cpp platform/3ds/network_state.cpp platform/3ds/network_state.hpp platform/3ds/network_snapshot.hpp tests/fake-network-sdk/3ds.h $(wildcard include/*.hpp) | build
	$(CXX) $(FLAGS) -O2 -Itests/fake-network-sdk tests/3ds_network_test.cpp platform/3ds/network_state.cpp -Wl,--wrap=gethostid,--wrap=socket,--wrap=close,--wrap=ioctl,--wrap=setsockopt,--wrap=sendto,--wrap=recvfrom -o $@
build/listener-lifecycle-tests: tests/listener_lifecycle_test.cpp source/app.cpp source/network.cpp $(CORE) $(wildcard include/*.hpp) | build
	$(CXX) $(FLAGS) -DCL_3DS -O2 tests/listener_lifecycle_test.cpp source/network.cpp $(CORE) -Wl,--wrap=socket,--wrap=close,--wrap=ioctl,--wrap=setsockopt,--wrap=bind,--wrap=listen,--wrap=accept -o $@
console-ports-test: build/console-ports-tests build/3ds-network-tests build/listener-lifecycle-tests build/nds-discovery-timeout-tests build/image-scaling-tests
	./build/console-ports-tests
	./build/3ds-network-tests
	./build/listener-lifecycle-tests
	./build/nds-discovery-timeout-tests
	./build/image-scaling-tests
	python3 -m unittest discover -s tests -p test_release_pair.py -v
	python3 -m unittest discover -s tests -p test_ftp_install.py -v
test: console-ports-test
console-ports-sanitize: | build
	$(CXX) $(FLAGS) -O1 -fno-omit-frame-pointer -fsanitize=address,undefined tests/console_ports_test.cpp $(CORE) -o build/console-ports-sanitized
	ASAN_OPTIONS="$(ASAN_OPTIONS)" ./build/console-ports-sanitized
	$(CXX) $(FLAGS) -O1 -fno-omit-frame-pointer -fsanitize=address,undefined -Itests/fake-network-sdk tests/3ds_network_test.cpp platform/3ds/network_state.cpp -Wl,--wrap=gethostid,--wrap=socket,--wrap=close,--wrap=ioctl,--wrap=setsockopt,--wrap=sendto,--wrap=recvfrom -o build/3ds-network-sanitized
	ASAN_OPTIONS="$(ASAN_OPTIONS)" ./build/3ds-network-sanitized
	$(CXX) $(FLAGS) -DCL_3DS -O1 -fno-omit-frame-pointer -fsanitize=address,undefined tests/listener_lifecycle_test.cpp source/network.cpp $(CORE) -Wl,--wrap=socket,--wrap=close,--wrap=ioctl,--wrap=setsockopt,--wrap=bind,--wrap=listen,--wrap=accept -o build/listener-lifecycle-sanitized
	ASAN_OPTIONS="$(ASAN_OPTIONS)" ./build/listener-lifecycle-sanitized
test: build/tests build/extdata-tests build/pksm-storage-tests build/nds-update-cleanup-tests build/nds-wpa-tests build/nds-raw-rx-tests build/nds-tx-retry-tests build/nds-association-tests build/nds-netif-tests build/nds-packet-queue-tests build/nds-dhcp-tests build/network-status-tests
	./build/tests
	./build/extdata-tests
	./build/pksm-storage-tests
	./build/nds-update-cleanup-tests
	./build/nds-wpa-tests
	./build/nds-raw-rx-tests
	./build/nds-tx-retry-tests
	./build/nds-association-tests
	./build/nds-netif-tests
	./build/nds-packet-queue-tests
	./build/nds-dhcp-tests
	./build/network-status-tests
	python3 -m unittest discover -s tests -p test_native_saves.py -v
mailbox-test: build/chest-link-cli build/mailbox-probe build/update-probe build/discovery-probe
	python3 -m unittest discover -s tests -p test_mailbox.py -v
GRAPHICS := source/graphics.cpp source/graphics_assets.cpp source/pokemon.cpp
build/render-ui: $(GRAPHICS) source/sha256.cpp tools/render_ui.cpp $(wildcard include/*.hpp) | build
	$(CXX) $(FLAGS) -O2 $(GRAPHICS) source/sha256.cpp tools/render_ui.cpp -o $@
build/render-ui-ds: $(GRAPHICS) source/sha256.cpp tools/render_ui.cpp $(wildcard include/*.hpp) | build
	$(CXX) $(FLAGS) -DCL_NDS -O2 $(GRAPHICS) source/sha256.cpp tools/render_ui.cpp -o $@
build/gui-tests: $(CORE) $(GRAPHICS) tests/gui_tests.cpp $(wildcard include/*.hpp) | build
	$(CXX) $(FLAGS) -O2 $(CORE) $(GRAPHICS) tests/gui_tests.cpp -o $@
gui-test: build/gui-tests build/render-ui build/render-ui-ds build/chest-link-cli
	./build/gui-tests
	python3 -m unittest discover -s tests -p test_interface.py -v
gui-sanitize: build/chest-link-cli | build
	$(CXX) $(FLAGS) -O1 -fno-omit-frame-pointer -fsanitize=address,undefined $(CORE) $(GRAPHICS) tests/gui_tests.cpp -o build/gui-sanitized
	ASAN_OPTIONS="$(ASAN_OPTIONS)" ./build/gui-sanitized
	ASAN_OPTIONS="$(ASAN_OPTIONS)" CHEST_LINK_GUI_PROBE="$(CURDIR)/build/gui-sanitized" python3 -m unittest discover -s tests -p test_interface.py -v
mailbox-sanitize: | build
	$(CXX) $(FLAGS) -O1 -fno-omit-frame-pointer -fsanitize=address,undefined $(CORE) $(NETWORK) tools/host.cpp -o build/cli-sanitized
	$(CXX) $(FLAGS) -O1 -fno-omit-frame-pointer -fsanitize=address,undefined $(CORE) $(NETWORK) tests/mailbox_probe.cpp -o build/probe-sanitized
	ASAN_OPTIONS="$(ASAN_OPTIONS)" CHEST_LINK_CLI="$(CURDIR)/build/cli-sanitized" CHEST_LINK_PROBE="$(CURDIR)/build/probe-sanitized" python3 -m unittest discover -s tests -p test_mailbox.py -v
sanitize: | build
	$(CXX) $(FLAGS) -O1 -fno-omit-frame-pointer -fsanitize=address,undefined $(CORE) $(NETWORK) tests/tests.cpp -o build/tests-sanitized
	ASAN_OPTIONS="$(ASAN_OPTIONS)" ./build/tests-sanitized
	$(CXX) $(FLAGS) -O1 -fno-omit-frame-pointer -fsanitize=address,undefined -Itests/fake-sdk platform/3ds/extdata.cpp tests/extdata_test.cpp -o build/extdata-sanitized
	ASAN_OPTIONS="$(ASAN_OPTIONS)" ./build/extdata-sanitized
ds 3ds: consoles
consoles:
	python3 tools/release_consoles.py --build-only
release: consoles
	python3 tools/release_consoles.py --publish-only
.PHONY: e2e e2e-server e2e-protocol e2e-ds e2e-3ds e2e-ds-to-pc e2e-hgss e2e-harness-test
e2e:
	python3 tests/e2e/run.py all
e2e-server:
	python3 tests/e2e/run.py server_boot
e2e-protocol:
	python3 tests/e2e/run.py protocol_ds_to_pc
e2e-ds:
	python3 tests/e2e/run.py ds_boot
e2e-3ds:
	python3 tests/e2e/run.py 3ds_boot
e2e-ds-to-pc:
	python3 tests/e2e/run.py ds_to_pc
e2e-hgss:
	python3 tests/e2e/run.py hgss_cross_platform_compare
e2e-harness-test:
	python3 -m unittest discover -s tests/e2e -p 'test_*.py' -v

.PHONY: e2e-firered e2e-probe-build
e2e-firered: build/chest-link-cli
	python3 tests/e2e/firered_suite.py
e2e-probe-build:
	python3 tests/e2e/build_console_probe.py
.PHONY: ds 3ds consoles release console-ports-test console-ports-sanitize
clean:
	rm -rf build
	$(MAKE) -C platform/nds clean
	$(MAKE) -C platform/3ds clean
