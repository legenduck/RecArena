#!/bin/sh
set -eu
# A fixed Debian snapshot avoids resolving a different OS package set next month.
rm -f /etc/apt/sources.list.d/debian.sources
cat > /etc/apt/sources.list <<'EOF'
deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261001T000000Z bookworm main
deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/20261001T000000Z bookworm-security main
EOF
apt-get update
apt-get install -y --no-install-recommends "$@"
dpkg-query -W > /app/os-packages.txt
rm -rf /var/lib/apt/lists/*
