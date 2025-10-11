#!/bin/sh
set -eu

RED=$(printf '\033[31m'); GRN=$(printf '\033[32m'); YEL=$(printf '\033[33m'); BLU=$(printf '\033[34m'); NC=$(printf '\033[0m')
ok(){ printf "%s[OK]%s %s\n" "$GRN" "$NC" "$*"; }
warn(){ printf "%s[WARN]%s %s\n" "$YEL" "$NC" "$*"; }
fail(){ printf "%s[FAIL]%s %s\n" "$RED" "$NC" "$*"; exit 1; }

[ "$(id -u)" = "0" ] || fail "run as root"

PREFIX="${PREFIX:-/usr/local}"
BIN_DIR="${BIN_DIR:-$PREFIX/sbin}"
BASE_FW_DIR="${BASE_FW_DIR:-$PREFIX/share/rpi-eeprom}"
RELEASE="${RELEASE:-stable}"
GIT_URL="${GIT_URL:-https://github.com/raspberrypi/rpi-eeprom}"
TMP="${TMPDIR:-/tmp}/rpi-eeprom.$$"

detect_soc() {
  soc=""
  if [ -r /proc/device-tree/compatible ]; then
    s="$(tr -d '\0' </proc/device-tree/compatible | grep -Eo 'bcm271[12]' | head -n1 || true)"
    case "$s" in
      *2712*) soc="2712" ;;
      *2711*) soc="2711" ;;
    esac
  fi
  if [ -z "$soc" ] && command -v vcgencmd >/dev/null 2>&1; then
    if vcgencmd bootloader_version >/dev/null 2>&1; then
      soc="2711"
    fi
  fi
  if [ -z "$soc" ]; then
    warn "could not detect SoC; defaulting to 2712 (Pi 5)"
    soc="2712"
  fi
  printf "%s" "$soc"
}

SOC="$(detect_soc)"
SOC_DIR="firmware-$SOC"
FW_DIR="$BASE_FW_DIR/$SOC_DIR"

echo "$BLU[STEP] Install prerequisites$NC"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y git rsync python3
fi

echo "$BLU[STEP] Clone repo$NC"
rm -rf "$TMP"
git clone --depth=1 "$GIT_URL" "$TMP"

echo "$BLU[STEP] SoC detected: bcm$SOC → using $SOC_DIR$NC"
if [ ! -d "$TMP/$SOC_DIR" ]; then
  if [ -d "$TMP/firmware" ]; then
    warn "repo missing $SOC_DIR; falling back to 'firmware'"
    SOC_DIR="firmware"
    FW_DIR="$BASE_FW_DIR/$SOC_DIR"
  else
    fail "neither $SOC_DIR nor firmware exist in repo; tree layout unsupported"
  fi
fi

echo "$BLU[STEP] Install tools to $BIN_DIR$NC"
install -d "$BIN_DIR"
for f in rpi-eeprom-config rpi-eeprom-update; do
  install -m 0755 "$TMP/$f" "$BIN_DIR/$f"
done

echo "$BLU[STEP] Install firmware to $FW_DIR$NC"
install -d "$FW_DIR"
rsync -a --delete "$TMP/$SOC_DIR/" "$FW_DIR/"

echo "$BLU[STEP] Configure /etc/default/rpi-eeprom-update$NC"
cat >/etc/default/rpi-eeprom-update <<EOF
FIRMWARE_DIR=$FW_DIR
FIRMWARE_RELEASE_STATUS=$RELEASE
EOF

echo "$BLU[STEP] Verify lookup$NC"
PATH="$BIN_DIR:$PATH" rpi-eeprom-update -l
ok "rpi-eeprom-update can locate firmware at $FW_DIR"

echo "$BLU[STEP] Smoke test editor$NC"
if PATH="$BIN_DIR:$PATH" rpi-eeprom-config -e --help >/dev/null 2>&1; then
  ok "rpi-eeprom-config is callable"
else
  warn "rpi-eeprom-config --help returned nonzero; tool present"
fi

rm -rf "$TMP"
echo "$GRN[RESULT] RPI_EEPROM_INSTALL_OK (bcm$SOC)$NC"
