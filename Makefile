CXX ?= g++
FLAGS := -std=c++17 -g -Wall -Wextra -Werror -pthread -DCL_HOST -Iinclude
ASAN_OPTIONS ?= detect_leaks=1
CORE := source/json.cpp source/sha256.cpp source/bank.cpp source/protocol.cpp source/mailbox.cpp source/update.cpp
NETWORK := source/network.cpp platform/host/runtime.cpp
.PHONY: all test mailbox-test gui-test gui-sanitize sanitize mailbox-sanitize ds 3ds clean
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
build/extdata-tests: platform/3ds/extdata.cpp platform/3ds/extdata.hpp tests/extdata_test.cpp tests/fake-sdk/3ds.h tests/fake-sdk/sys/iosupport.h | build
	$(CXX) $(FLAGS) -O2 -Itests/fake-sdk platform/3ds/extdata.cpp tests/extdata_test.cpp -o $@
build/pksm-storage-tests: platform/3ds/pksm_storage.hpp tests/pksm_storage_test.cpp | build
	$(CXX) $(FLAGS) -O2 tests/pksm_storage_test.cpp -o $@
test: build/tests build/extdata-tests build/pksm-storage-tests
	./build/tests
	./build/extdata-tests
	./build/pksm-storage-tests
mailbox-test: build/chest-link-cli build/mailbox-probe build/update-probe
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
ds:
	$(MAKE) -C platform/nds
	python3 tools/create_update_manifest.py platform/nds/ChestLink_DS.nds include/version.hpp platform/nds/release.json
3ds:
	$(MAKE) -C platform/3ds
clean:
	rm -rf build
	$(MAKE) -C platform/nds clean
	$(MAKE) -C platform/3ds clean
