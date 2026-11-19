#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
#
# Builds dfu-util, statically linked with libusb and musl, for //fw:flash
# (issue #14, step 5). musl, not glibc: a static glibc would put glibc
# (LGPL-2.1) into the binary we redistribute; musl is MIT.
#
# It runs inside the pinned Ubuntu container that
# `bazel run //tools/dfu_util` starts, never on the host. The Go tool
# embeds this file, mounts the output directory at /out and a copy of the
# host's CA bundle at /host-ca.crt (read-only), and passes the pinned
# inputs as environment variables:
#
#   APT_SNAPSHOT                  the snapshot.ubuntu.com time of every package;
#   LIBUSB_URL, LIBUSB_SHA256     libusb's release tarball;
#   DFU_UTIL_URL, DFU_UTIL_SHA256 dfu-util's release tarball;
#   JOBS                          parallel compile jobs.
#
# /out receives dfu-util, the two source tarballs as downloaded under their
# upstream names, dfu-util-licenses.tar (the licences of dfu-util, libusb
# and musl), and SHA256SUMS,
# and only once everything has worked: a failed run leaves it empty.
set -euo pipefail
JOBS=${JOBS:-4}
export SOURCE_DATE_EPOCH=0
mkdir -p /work

# Every package from one snapshot of the archive, so the versions are fixed.
# apt checks snapshot.ubuntu.com, which is HTTPS only, against the host's CA
# bundle; it still checks every package against the archive's signed index.
rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*
cat > /etc/apt/sources.list.d/snapshot.sources <<SRC
Types: deb
URIs: https://snapshot.ubuntu.com/ubuntu/$APT_SNAPSHOT/
Suites: resolute resolute-updates resolute-security
Components: main universe
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
SRC
APT=(-o Acquire::https::CaInfo=/host-ca.crt -o Acquire::Retries=3)
apt-get "${APT[@]}" update -q
DEBIAN_FRONTEND=noninteractive apt-get "${APT[@]}" install -y -q --no-install-recommends \
  ca-certificates curl bzip2 xz-utils gcc libc6-dev musl-tools linux-libc-dev binutils make pkg-config

fetch() { # URL SHA256 FILE
  curl -fsSL --retry 5 --retry-all-errors -o "$3" "$1"
  echo "$2  $3" | sha256sum -c -
}

# The same paths and times every run, so two builds give the same bytes.
# musl-gcc searches musl's headers only; the kernel's (linux/, asm/), which
# libusb needs and which no libc owns, come after them.
export CC=musl-gcc
FLAGS="-O2 -ffile-prefix-map=/work=. -fdebug-prefix-map=/work=. -idirafter /usr/include -idirafter /usr/include/x86_64-linux-gnu"
P=/work/prefix
LIBUSB=$(basename "$LIBUSB_URL")
DFU=$(basename "$DFU_UTIL_URL")

# libusb, static, without udev: dfu-util lists devices itself.
fetch "$LIBUSB_URL" "$LIBUSB_SHA256" "/work/$LIBUSB"
mkdir -p /work/libusb && tar -xjf "/work/$LIBUSB" -C /work/libusb --strip-components=1
(cd /work/libusb && CFLAGS="$FLAGS" ./configure --prefix=$P --enable-static --disable-shared \
  --disable-udev --disable-examples-build --disable-tests-build && make -j"$JOBS" && make install)

# dfu-util, linked statically with that libusb.
fetch "$DFU_UTIL_URL" "$DFU_UTIL_SHA256" "/work/$DFU"
mkdir -p /work/dfu && tar -xzf "/work/$DFU" -C /work/dfu --strip-components=1
(cd /work/dfu && PKG_CONFIG_PATH=$P/lib/pkgconfig CFLAGS="$FLAGS" LDFLAGS="-static" \
  ./configure --prefix=$P && make -j"$JOBS" && make install)
cp $P/bin/dfu-util /work/dfu-util
strip --strip-all /work/dfu-util
# A static binary, so it runs on any x86_64 Linux with nothing installed:
# no program interpreter, and no shared library it needs.
headers=$(readelf -l -d /work/dfu-util)
if grep -q -e 'INTERP' -e '(NEEDED)' <<<"$headers"; then
  echo "dfu-util is not static:" >&2
  grep -e 'INTERP' -e '(NEEDED)' <<<"$headers" >&2
  exit 1
fi
/work/dfu-util --version | sed -n 1p

# The licences of what the binary holds: each must exist.
mkdir -p /work/licenses/dfu-util /work/licenses/libusb /work/licenses/musl
cp /work/dfu/COPYING /work/licenses/dfu-util/COPYING
cp /work/libusb/COPYING /work/licenses/libusb/COPYING
# musl's copyright file, as Ubuntu's package installs it: it holds musl's
# COPYRIGHT (MIT).
cp /usr/share/doc/musl/copyright /work/licenses/musl/copyright
(cd /work && tar --format=posix --pax-option=delete=atime,delete=ctime --sort=name \
  --mtime='@0' --owner=0 --group=0 --numeric-owner -cf dfu-util-licenses.tar licenses)

# Only now into /out, so a failed run leaves it empty.
(cd /work && sha256sum dfu-util "$LIBUSB" "$DFU" dfu-util-licenses.tar > SHA256SUMS)
cp /work/dfu-util "/work/$LIBUSB" "/work/$DFU" /work/dfu-util-licenses.tar /work/SHA256SUMS /out/
cat /out/SHA256SUMS
