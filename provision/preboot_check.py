#!/usr/bin/env python3
import json, os, re, subprocess, sys
def run_cmd(cmd):
    p = subprocess.run(cmd, shell=isinstance(cmd,str), capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()
def read(path):
    try:
        with open(path, 'r') as f:
            return f.read()
    except Exception:
        return ""
def main():
    target = '/mnt/nvme'
    esp = os.path.join(target, 'boot', 'firmware')
    initrd = os.path.join(target, 'boot', 'firmware', 'initramfs_2712')
    checks = {}
    rc,out,err = run_cmd("blkid -s UUID -o value /dev/nvme0n1p3")
    luks_uuid = out.strip()
    checks['luks_uuid_present'] = (rc==0 and len(luks_uuid)>0)
    cmdline_path = os.path.join(esp, 'cmdline.txt')
    cmdline = read(cmdline_path)
    checks['cmdline_exists'] = bool(cmdline)
    checks['cmdline_has_root_mapper'] = '/dev/mapper/rp5vg-root' in cmdline
    checks['cmdline_has_cryptdevice'] = f'cryptdevice=UUID={luks_uuid}:cryptroot' in cmdline if luks_uuid else False
    config_path = os.path.join(esp, 'config.txt')
    cfg = read(config_path)
    checks['config_has_initramfs'] = bool(re.search(r'^initramfs\s+\S+\s+followkernel', cfg, re.M))
    rc,out,err = run_cmd(f"lsinitramfs {initrd}")
    checks['initramfs_has_cryptsetup'] = ('cryptsetup' in out) and rc==0
    checks['initramfs_has_lvm'] = ('lvm' in out) and rc==0
    fstab = read(os.path.join(target, 'etc', 'fstab'))
    crypttab = read(os.path.join(target, 'etc', 'crypttab'))
    checks['fstab_has_mapper_root'] = '/dev/mapper/rp5vg-root' in fstab
    checks['crypttab_has_uuid'] = (luks_uuid in crypttab) if luks_uuid else False
    rc,out,err = run_cmd("vgscan --mknodes && vgchange -ay rp5vg && lvscan")
    checks['lv_visible'] = (rc==0 and ('/rp5vg/root' in out or 'rp5vg' in out))
    ok = all(checks.values())
    print(json.dumps({"ok": ok, "checks": checks, "luks_uuid": luks_uuid}, indent=2))
    return 0 if ok else 1
if __name__ == '__main__':
    sys.exit(main())
