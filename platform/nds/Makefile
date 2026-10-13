export BLOCKSDS ?= /opt/wonderful/thirdparty/blocksds/core
export WONDERFUL_TOOLCHAIN ?= /opt/wonderful
ARM_NONE_EABI_PATH ?= $(WONDERFUL_TOOLCHAIN)/toolchain/gcc-arm-none-eabi/bin/
DSWIFI_DIR := ../../third_party/dswifi
DSWIFI9 := $(DSWIFI_DIR)/lib/libdswifi9.a
DSWIFI9_SOURCES := $(shell find $(DSWIFI_DIR)/source/arm9 $(DSWIFI_DIR)/source/common $(DSWIFI_DIR)/lwip $(DSWIFI_DIR)/include -type f) $(DSWIFI_DIR)/Makefile.arm9
DSWIFI7_SOURCES := $(shell find $(DSWIFI_DIR)/source/arm7 $(DSWIFI_DIR)/source/common $(DSWIFI_DIR)/mbedtls $(DSWIFI_DIR)/include -type f) $(DSWIFI_DIR)/Makefile.arm7
ARM7ELF := arm7/build/arm7_dswifi.elf
CXX := $(ARM_NONE_EABI_PATH)arm-none-eabi-g++
LD := $(ARM_NONE_EABI_PATH)arm-none-eabi-gcc
NAME := ChestLink_DS
VERSION_HEADER := ../../include/version.hpp
include ../../version.mk
ARCH := -mthumb -mcpu=arm946e-s+nofp
SPECS := $(BLOCKSDS)/sys/crts/ds_arm9.specs
DEFINES := -DCL_NDS -D__NDS__ -D__BLOCKSDS__ -DARM9
INCLUDES := -I../../include -I$(DSWIFI_DIR)/include -I$(BLOCKSDS)/libs/libnds/include
CXXFLAGS := $(ARCH) -std=gnu++17 -O2 -g -Wall -fexceptions -fno-rtti -ffunction-sections -fdata-sections -specs=$(SPECS) $(DEFINES) $(INCLUDES)
COMMON := $(wildcard ../../source/*.cpp)
# Flat object paths keep dependency filenames independent of the checkout path.
OBJECTS := $(patsubst ../../source/%.cpp,build/%.o,$(COMMON)) build/main.o
LDFLAGS := $(ARCH) -specs=$(SPECS) -L$(DSWIFI_DIR)/lib -L$(BLOCKSDS)/libs/libnds/lib -Wl,-Map,build/$(NAME).map
.DELETE_ON_ERROR:
.PHONY: all release clean
all: $(NAME).nds
$(DSWIFI9): $(DSWIFI9_SOURCES)
	$(MAKE) -C $(DSWIFI_DIR) -f Makefile.arm9 ENABLE_LWIP=1 BLOCKSDS=$(BLOCKSDS) WONDERFUL_TOOLCHAIN=$(WONDERFUL_TOOLCHAIN) ARM_NONE_EABI_PATH=$(ARM_NONE_EABI_PATH)
$(DSWIFI_DIR)/lib/libdswifi7.a: $(DSWIFI7_SOURCES)
	$(MAKE) -C $(DSWIFI_DIR) -f Makefile.arm7 BLOCKSDS=$(BLOCKSDS) WONDERFUL_TOOLCHAIN=$(WONDERFUL_TOOLCHAIN) ARM_NONE_EABI_PATH=$(ARM_NONE_EABI_PATH)
$(ARM7ELF): arm7/Makefile arm7/crypto-layout.ld arm7/source/main.c $(DSWIFI_DIR)/lib/libdswifi7.a
	$(MAKE) -C arm7 BLOCKSDS=$(BLOCKSDS) DSWIFI_DIR=../../../third_party/dswifi WONDERFUL_TOOLCHAIN=$(WONDERFUL_TOOLCHAIN) ARM_NONE_EABI_PATH=$(ARM_NONE_EABI_PATH)
build:
	mkdir -p build
build/%.o: ../../source/%.cpp | build
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@
build/main.o: main.cpp | build
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@
build/$(NAME).elf: $(OBJECTS) $(DSWIFI9) Makefile
	$(LD) -o $@ $(OBJECTS) $(LDFLAGS) -Wl,--start-group -ldswifi9 -lnds9 -lstdc++ -lc -Wl,--end-group
$(NAME).nds: build/$(NAME).elf $(ARM7ELF) ../../assets/chestlink-ds.gif Makefile ../../version.mk $(VERSION_HEADER)
	$(BLOCKSDS)/tools/ndstool/ndstool -c $@ -7 $(ARM7ELF) -9 $< -b ../../assets/chestlink-ds.gif "Chest Link;Boxes DS - PC - 3DS v$(CHEST_LINK_VERSION);Chest Link contributors"
release.json: $(NAME).nds ../../include/version.hpp ../../tools/create_update_manifest.py
	python3 ../../tools/create_update_manifest.py $(NAME).nds ../../include/version.hpp $@
release: release.json
clean:
	rm -rf build $(NAME).nds release.json
	$(MAKE) -C arm7 clean
	$(MAKE) -C $(DSWIFI_DIR) clean
-include $(OBJECTS:.o=.d)
