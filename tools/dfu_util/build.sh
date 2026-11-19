#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
#
# Builds dfu-util, statically linked with libusb, for //fw:flash (issue
# #14, step 5). It runs inside the pinned Ubuntu container that
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
# /out receives dfu-util, the two source tarballs as downloaded,
# dfu-util-licenses.tar (dfu-util's and libusb's licences), and SHA256SUMS,
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
  ca-certificates curl bzip2 xz-utils gcc libc6-dev make pkg-config

fetch() { # URL SHA256 FILE
  curl -fsSL --retry 5 --retry-all-errors -o "$3" "$1"
  echo "$2  $3" | sha256sum -c -
}

# The same paths and times every run, so two builds give the same bytes.
FLAGS="-O2 -ffile-prefix-map=/work=. -fdebug-prefix-map=/work=."
P=/work/prefix

# libusb, static, without udev: dfu-util lists devices itself.
fetch "$LIBUSB_URL" "$LIBUSB_SHA256" /work/libusb.tar.bz2
mkdir -p /work/libusb && tar -xjf /work/libusb.tar.bz2 -C /work/libusb --strip-components=1
(cd /work/libusb && CFLAGS="$FLAGS" ./configure --prefix=$P --enable-static --disable-shared \
  --disable-udev --disable-examples-build --disable-tests-build && make -j"$JOBS" && make install)

# dfu-util, linked statically with that libusb.
fetch "$DFU_UTIL_URL" "$DFU_UTIL_SHA256" /work/dfu-util.tar.gz
mkdir -p /work/dfu && tar -xzf /work/dfu-util.tar.gz -C /work/dfu --strip-components=1
(cd /work/dfu && PKG_CONFIG_PATH=$P/lib/pkgconfig CFLAGS="$FLAGS" LDFLAGS="-static" \
  ./configure --prefix=$P && make -j"$JOBS" && make install)
cp $P/bin/dfu-util /work/dfu-util
strip --strip-all /work/dfu-util
# A static binary: it runs on any x86_64 Linux, with nothing installed.
if file_out=$(LC_ALL=C ldd /work/dfu-util 2>&1); then
  echo "dfu-util is not static: $file_out" >&2
  exit 1
fi
/work/dfu-util --version | sed -n 1p

# The licences of what the binary holds: each must exist.
mkdir -p /work/licenses/dfu-util /work/licenses/libusb
cp /work/dfu/COPYING /work/licenses/dfu-util/COPYING
cp /work/libusb/COPYING /work/licenses/libusb/COPYING
(cd /work && tar --format=posix --pax-option=delete=atime,delete=ctime --sort=name \
  --mtime='@0' --owner=0 --group=0 --numeric-owner -cf dfu-util-licenses.tar licenses)

# Only now into /out, so a failed run leaves it empty.
(cd /work && sha256sum dfu-util libusb.tar.bz2 dfu-util.tar.gz dfu-util-licenses.tar > SHA256SUMS)
cp /work/dfu-util /work/libusb.tar.bz2 /work/dfu-util.tar.gz /work/dfu-util-licenses.tar /work/SHA256SUMS /out/
cat /out/SHA256SUMS
