# DSWiFi vendored source

This directory contains the BlocksDS DSWiFi source, pinned to upstream commit
`59d2636dd851ea26a4ea49f329321d3bfb002066` from
`https://codeberg.org/blocksds/dswifi.git`.

The source is included so Chest Link can build a custom NTR ARM7 Wi-Fi core
instead of silently using the SDK's prebuilt core. This is required for the
experimental DS/DS Lite WPA2-PSK/AES driver work. Upstream source files retain
their own license notices. See `COPYING`, `COPYING.lwip`, and
`COPYING.mbedtls`.
