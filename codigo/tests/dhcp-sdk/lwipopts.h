// Keep the DS protocol configuration. Host tests drive time explicitly instead
// of requiring libnds cooperative threads/IRQ hardware.
#include "../../third_party/dswifi/source/arm9/lwip/include/lwipopts.h"
#undef NO_SYS
#define NO_SYS 1
#define SYS_LIGHTWEIGHT_PROT 0
#undef LWIP_NETIF_API
#define LWIP_NETIF_API 0
#undef LWIP_SOCKET
#define LWIP_SOCKET 0
// lwIP gates diagnostics on definedness, not the value 0 used by the DS port.
// Its DS printf typedefs differ on a 64-bit host; disable unused diagnostics.
#undef LWIP_DEBUG
