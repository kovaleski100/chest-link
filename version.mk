# Both launchers derive their release from the shared header. No Python needed.
CHEST_LINK_VERSION := $(shell awk '/define CHEST_LINK_VERSION_MAJOR / {major=$$3} /define CHEST_LINK_VERSION_MINOR / {minor=$$3} /define CHEST_LINK_VERSION_PATCH / {patch=$$3} END {printf "%d.%d.%d", major, minor, patch}' $(VERSION_HEADER))
