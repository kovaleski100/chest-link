DEVKITPRO ?= /opt/devkitpro
DEVKITARM ?= $(DEVKITPRO)/devkitARM
CXX := $(DEVKITARM)/bin/arm-none-eabi-g++
NAME := ChestLink_3DS
ARCH := -march=armv6k -mtune=mpcore -mfloat-abi=hard -mtp=soft
CXXFLAGS := $(ARCH) -std=gnu++17 -O2 -g -Wall -Wextra -ffunction-sections -fdata-sections -D__3DS__ -DCL_3DS -I../../include -I$(DEVKITPRO)/libctru/include
COMMON := $(wildcard ../../source/*.cpp)
OBJECTS := $(patsubst ../../source/%.cpp,build/%.o,$(COMMON)) build/main.o build/extdata.o
LDFLAGS := $(ARCH) -specs=3dsx.specs -L$(DEVKITPRO)/libctru/lib -Wl,--gc-sections,-Map,build/$(NAME).map
.PHONY: all clean
all: $(NAME).3dsx $(NAME).smdh
build:
	mkdir -p build
build/%.o: ../../source/%.cpp | build
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@
build/main.o: main.cpp | build
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@
build/extdata.o: extdata.cpp | build
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@
build/$(NAME).elf: $(OBJECTS)
	$(CXX) $(LDFLAGS) $(OBJECTS) -lctru -lm -o $@
$(NAME).smdh: Makefile ../../assets/chestlink-3ds.png
	$(DEVKITPRO)/tools/bin/smdhtool --create "Chest Link" "Boxes DS - PC - 3DS v0.3" "Chest Link contributors" ../../assets/chestlink-3ds.png $@
$(NAME).3dsx: build/$(NAME).elf $(NAME).smdh
	$(DEVKITPRO)/tools/bin/3dsxtool $< $@ --smdh=$(NAME).smdh
clean:
	rm -rf build $(NAME).3dsx $(NAME).smdh
-include $(OBJECTS:.o=.d)
