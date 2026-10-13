DEVKITPRO ?= /opt/devkitpro
DEVKITARM ?= $(DEVKITPRO)/devkitARM
CXX := $(DEVKITARM)/bin/arm-none-eabi-g++
NAME := ChestLink_3DS
VERSION_HEADER := ../../include/version.hpp
include ../../version.mk
ARCH := -march=armv6k -mtune=mpcore -mfloat-abi=hard -mtp=soft
CXXFLAGS := $(ARCH) -std=gnu++17 -O2 -g -Wall -Wextra -ffunction-sections -fdata-sections -D__3DS__ -DCL_3DS -I../../include -I$(DEVKITPRO)/libctru/include
COMMON := $(wildcard ../../source/*.cpp)
OBJECTS := $(patsubst ../../source/%.cpp,build/%.o,$(COMMON)) build/main.o build/extdata.o build/network_state.o
LDFLAGS := $(ARCH) -specs=3dsx.specs -L$(DEVKITPRO)/libctru/lib -Wl,--gc-sections,-Map,build/$(NAME).map
.PHONY: all clean
all: $(NAME).3dsx $(NAME).smdh release.json
build:
	mkdir -p build
build/%.o: ../../source/%.cpp | build
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@
build/main.o: main.cpp | build
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@
build/extdata.o: extdata.cpp | build
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@
build/network_state.o: network_state.cpp | build
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@
build/$(NAME).elf: $(OBJECTS)
	$(CXX) $(LDFLAGS) $(OBJECTS) -lctru -lm -o $@
$(NAME).smdh: Makefile ../../version.mk ../../assets/chestlink-3ds.png $(VERSION_HEADER)
	$(DEVKITPRO)/tools/bin/smdhtool --create "Chest Link" "Boxes DS - PC - 3DS v$(CHEST_LINK_VERSION)" "Chest Link contributors" ../../assets/chestlink-3ds.png $@
$(NAME).3dsx: build/$(NAME).elf $(NAME).smdh
	$(DEVKITPRO)/tools/bin/3dsxtool $< $@ --smdh=$(NAME).smdh
release.json: $(NAME).3dsx ../../include/version.hpp ../../tools/create_update_manifest.py
	python3 ../../tools/create_update_manifest.py $(NAME).3dsx ../../include/version.hpp $@
clean:
	rm -rf build $(NAME).3dsx $(NAME).smdh
-include $(OBJECTS:.o=.d)
