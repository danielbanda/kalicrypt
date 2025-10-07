#!/usr/bin/env bash
set -euo pipefail
if [ -n "${SUDO_USER-}" ]; then USER_HOME=$(eval echo "~${SUDO_USER}"); else USER_HOME="${HOME}"; fi
RP5_DIR="${USER_HOME}/rp5"
sudo python -m provision /dev/nvme0n1 --plan || true
sudo python -m provision /dev/nvme0n1 --dry-run --yes --do-postcheck || true
test -f "${RP5_DIR}/03_LOGS/ete_nvme.jsonl" && tail -n 1 "${RP5_DIR}/03_LOGS/ete_nvme.jsonl" || true
