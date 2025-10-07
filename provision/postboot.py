"""Post-boot heartbeat installer."""
from .executil import run, udev_settle

def install_postboot_check(mnt_root: str) -> dict:
    if not mnt_root or mnt_root == "/":
        return {}
    script = f"{mnt_root}/usr/local/sbin/rp5-postboot-check"
    unit = f"{mnt_root}/etc/systemd/system/rp5-postboot.service"
    logdir = f"{mnt_root}/var/log/rp5"
    run(["mkdir","-p", logdir], check=False)
    run(["mkdir","-p", f"{mnt_root}/usr/local/sbin"], check=False)
    run(["mkdir","-p", f"{mnt_root}/etc/systemd/system"], check=False)
    payload = """#!/bin/sh
set -eu
ts=$(date -Is)
mkdir -p /var/log/rp5
echo '{"ts":"'"$ts"'","result":"POSTBOOT_OK"}' >> /var/log/rp5/heartbeat.jsonl
systemctl disable rp5-postboot.service >/dev/null 2>&1 || true
exit 0
"""
    run(["/bin/sh","-c", f"cat > '{script}' <<'EOF'\n{payload}\nEOF"], check=True)
    run(["chmod","0755", script], check=True)
    unit_text = """[Unit]
Description=RP5 Post-boot Heartbeat
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/rp5-postboot-check

[Install]
WantedBy=multi-user.target
"""
    run(["/bin/sh","-c", f"cat > '{unit}' <<'EOF'\n{unit_text}\nEOF"], check=True)
    wants_dir = f"{mnt_root}/etc/systemd/system/multi-user.target.wants"
    run(["mkdir","-p", wants_dir], check=False)
    run(["ln","-sf", "../rp5-postboot.service", f"{wants_dir}/rp5-postboot.service"], check=True)
    udev_settle()
    return {"script": script, "unit": unit}
