
"""Ensure/rebuild/verify initramfs in target root (Phase 2)."""
import os, re, subprocess
from .executil import run


REQUIRED_PACKAGES = ("cryptsetup-initramfs", "lvm2", "initramfs-tools")


def ensure_packages(mnt: str, dry_run: bool = False):
    """Install initramfs prerequisites inside the target root if missing."""

    run(["chroot", mnt, "/usr/bin/apt-get", "update"], check=False, dry_run=dry_run)
    for pkg in REQUIRED_PACKAGES:
        res = run(["chroot", mnt, "/usr/bin/dpkg", "-s", pkg], check=False, dry_run=dry_run)
        if res.rc != 0:
            run(
                ["chroot", mnt, "/usr/bin/apt-get", "-y", "install", pkg],
                check=False,
                dry_run=dry_run,
            )


def _ensure_crypttab_prompts(mnt: str) -> None:
    """Force crypttab to prompt for the passphrase (no baked-in key path)."""

    ct_path = os.path.join(mnt, "etc", "crypttab")
    if not os.path.isfile(ct_path):
        return
    with open(ct_path, "r", encoding="utf-8") as fh:
        original = fh.read()
    patched = re.sub(
        r"^(cryptroot\s+UUID=[0-9a-fA-F-]+)\s+\S+",
        r"\1 none",
        original,
        flags=re.M,
    )
    if patched != original:
        with open(ct_path, "w", encoding="utf-8") as fh:
            fh.write(patched)


def _detect_kernel_version(mnt: str) -> str:
    modules_dir = os.path.join(mnt, "lib", "modules")
    if not os.path.isdir(modules_dir):
        raise RuntimeError("initramfs: /lib/modules missing in target root")
    cands = [
        entry
        for entry in os.listdir(modules_dir)
        if os.path.isdir(os.path.join(modules_dir, entry))
    ]
    if not cands:
        raise RuntimeError("initramfs: no kernel modules found in target root")
    return sorted(cands)[0]


def rebuild(mnt: str, dry_run: bool = False):
    _ensure_crypttab_prompts(mnt)
    kver = _detect_kernel_version(mnt)

    res = run(
        ["chroot", mnt, "/usr/sbin/update-initramfs", "-c", "-k", kver],
        check=False,
        dry_run=dry_run,
    )
    if res.rc != 0:
        run(
            ["chroot", mnt, "/usr/sbin/update-initramfs", "-u", "-k", kver],
            check=True,
            dry_run=dry_run,
        )

    run(
        ["chroot", mnt, "/bin/cp", "-f", f"/boot/initrd.img-{kver}", "/boot/firmware/initramfs_2712"],
        check=True,
        dry_run=dry_run,
    )
    run(
        [
            "chroot",
            mnt,
            "/usr/bin/lsinitramfs",
            "/boot/firmware/initramfs_2712",
        ],
        check=True,
        dry_run=dry_run,
    )


def verify(dst_boot_fw: str) -> str:
    cfg = os.path.join(dst_boot_fw, 'config.txt')
    if not os.path.exists(cfg):
        # write a safe default that references the newest initrd
        ir = newest_initrd(dst_boot_fw)
        with open(cfg,'w',encoding='utf-8') as f: f.write(f"initramfs {os.path.basename(ir)} followkernel\n")
    with open(cfg,'r',encoding='utf-8') as f:
        m = re.search(r'^initramfs\s+([^\s#]+)', f.read(), re.M)
    if not m:
        raise RuntimeError("initramfs: config.txt missing initramfs line")
    ir = os.path.join(dst_boot_fw, m.group(1))
    if not os.path.isfile(ir) or os.path.getsize(ir) < 131072:
        raise RuntimeError("initramfs: image missing or too small")
    # ensure cryptsetup+lvm present
    out = subprocess.check_output(["lsinitramfs", ir], text=True)
    out_lower = out.lower()
    required_tokens = ("cryptsetup", "lvm", "dm-crypt", "nvme")
    missing = [tok for tok in required_tokens if tok not in out_lower]
    if missing:
        raise RuntimeError(
            "initramfs: missing components in image (%s)" % ", ".join(missing)
        )
    return ir

def newest_initrd(dst_boot_fw: str) -> str:
    cands = sorted([p for p in os.listdir(dst_boot_fw) if p.startswith('initramfs')], reverse=True)
    if not cands:
        raise RuntimeError("initramfs: no initramfs* found in /boot/firmware")
    return os.path.join(dst_boot_fw, cands[0])
