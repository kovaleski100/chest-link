BLOCKSDS ?= /opt/wonderful/thirdparty/blocksds/core
WONDERFUL_TOOLCHAIN ?= /opt/wonderful
ARM_NONE_EABI_PATH ?= $(WONDERFUL_TOOLCHAIN)/toolchain/gcc-arm-none-eabi/bin/
DSWIFI_DIR ?= ../../../third_party/dswifi

CC := $(ARM_NONE_EABI_PATH)arm-none-eabi-gcc
ARCH := -mthumb -mcpu=arm7tdmi
SPECS := $(BLOCKSDS)/sys/crts/ds_arm7.specs
INCLUDES := -I$(DSWIFI_DIR)/include -I$(BLOCKSDS)/libs/libnds/include
DEFINES := -D__NDS__ -DARM7 -DUSE_DSWIFI -DPICOLIBC_LONG_LONG_PRINTF_SCANF
CFLAGS := $(ARCH) -std=gnu23 -O2 -Wall -Wextra -ffunction-sections -fdata-sections $(DEFINES) $(INCLUDES) -specs=$(SPECS)
LDFLAGS := $(ARCH) -specs=$(SPECS) -L$(DSWIFI_DIR)/lib -L$(BLOCKSDS)/libs/libnds/lib -Wl,-Map,build/arm7_dswifi.map -Wl,-T,crypto-layout.ld
DSWIFI7 := $(DSWIFI_DIR)/lib/libdswifi7.a
OUTPUT := build/arm7_dswifi.elf

.PHONY: all clean FORCE
all: $(OUTPUT)

FORCE:
$(DSWIFI7): FORCE
	$(MAKE) -C $(DSWIFI_DIR) -f Makefile.arm7 BLOCKSDS=$(BLOCKSDS) WONDERFUL_TOOLCHAIN=$(WONDERFUL_TOOLCHAIN) ARM_NONE_EABI_PATH=$(ARM_NONE_EABI_PATH)

$(OUTPUT): source/main.c $(DSWIFI7) Makefile crypto-layout.ld
	mkdir -p build
	$(CC) $(CFLAGS) -MMD -MP -c $< -o build/main.o
	$(CC) -o $@ build/main.o $(LDFLAGS) -Wl,--start-group -ldswifi7 -lnds7 -lc -Wl,--end-group

clean:
	rm -rf build
