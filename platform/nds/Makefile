export BLOCKSDS ?= /opt/wonderful/thirdparty/blocksds/core
export WONDERFUL_TOOLCHAIN ?= /opt/wonderful
ARM_NONE_EABI_PATH ?= $(WONDERFUL_TOOLCHAIN)/toolchain/gcc-arm-none-eabi/bin/
CXX := $(ARM_NONE_EABI_PATH)arm-none-eabi-g++
LD := $(ARM_NONE_EABI_PATH)arm-none-eabi-gcc
NAME := ChestLink_DS
ARCH := -mthumb -mcpu=arm946e-s+nofp
SPECS := $(BLOCKSDS)/sys/crts/ds_arm9.specs
DEFINES := -DCL_NDS -D__NDS__ -D__BLOCKSDS__ -DARM9
INCLUDES := -I../../include -I$(BLOCKSDS)/libs/dswifi/include -I$(BLOCKSDS)/libs/libnds/include
CXXFLAGS := $(ARCH) -std=gnu++17 -O2 -g -Wall -fexceptions -fno-rtti -ffunction-sections -fdata-sections -specs=$(SPECS) $(DEFINES) $(INCLUDES)
COMMON := $(wildcard ../../source/*.cpp)
# Flat object paths keep dependency filenames independent of the checkout path.
OBJECTS := $(patsubst ../../source/%.cpp,build/%.o,$(COMMON)) build/main.o
LDFLAGS := $(ARCH) -specs=$(SPECS) -L$(BLOCKSDS)/libs/dswifi/lib -L$(BLOCKSDS)/libs/libnds/lib -Wl,-Map,build/$(NAME).map
ARM7ELF := $(BLOCKSDS)/sys/arm7/main_core/arm7_dswifi.elf
.DELETE_ON_ERROR:
.PHONY: all release clean
all: $(NAME).nds
build:
	mkdir -p build
build/%.o: ../../source/%.cpp | build
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@
build/main.o: main.cpp | build
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@
build/$(NAME).elf: $(OBJECTS) Makefile
	$(LD) -o $@ $(OBJECTS) $(LDFLAGS) -Wl,--start-group -ldswifi9 -lnds9 -lstdc++ -lc -Wl,--end-group
$(NAME).nds: build/$(NAME).elf ../../assets/chestlink-ds.gif Makefile
	$(BLOCKSDS)/tools/ndstool/ndstool -c $@ -7 $(ARM7ELF) -9 $< -b ../../assets/chestlink-ds.gif "Chest Link;Boxes DS - PC - 3DS v0.4.10;Chest Link contributors"
release.json: $(NAME).nds ../../include/version.hpp ../../tools/create_update_manifest.py
	python3 ../../tools/create_update_manifest.py $(NAME).nds ../../include/version.hpp $@
release: release.json
clean:
	rm -rf build $(NAME).nds release.json
-include $(OBJECTS:.o=.d)
