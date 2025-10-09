"""Write fstab/crypttab/cmdline and validate (Phase 2)."""
import os
from typing import Iterable


def write_fstab(mnt: str, p1_uuid: str, p2_uuid: str):
    fstab = os.path.join(mnt, 'etc/fstab')
    os.makedirs(os.path.dirname(fstab), exist_ok=True)
    lines = [
        f"UUID={p1_uuid}  /boot/firmware  vfat  defaults,uid=0,gid=0,umask=0077  0  1",
        f"UUID={p2_uuid}  /boot  ext4  defaults  0  2",
        "/dev/mapper/rp5vg-root  /  ext4  defaults  0  1",
    ]
    data = "\n".join(lines) + "\n"
    with open(fstab, 'w', encoding='utf-8') as f:
        f.write(data)
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            pass


_KEYFILE_ROOT = "/etc/cryptsetup-keys.d"


def _normalize_keyfile_path(path: str | None) -> str | None:
    if path is None:
        return None
    normalized = os.path.normpath(path)
    if not normalized.startswith("/"):
        normalized = "/" + normalized.lstrip("/")
    return normalized


def _validate_keyfile_path(path: str | None) -> str | None:
    if path is None:
        return None
    normalized = _normalize_keyfile_path(path)
    if normalized is None:
        return None
    allowed_root = os.path.normpath(_KEYFILE_ROOT)
    candidate = os.path.normpath(normalized)
    if candidate == allowed_root:
        raise ValueError("keyfile path must include a filename under /etc/cryptsetup-keys.d")
    if not candidate.startswith(allowed_root + os.sep) and candidate != allowed_root:
        raise ValueError("keyfile path must reside under /etc/cryptsetup-keys.d")
    return candidate


def write_crypttab(
        mnt: str,
        luks_uuid: str,
        passfile: str | None,
        keyscript_path: str | None = None,
        *,
        keyfile_path: str | None = None,
        enable_keyfile: bool = False,
):
    ct = os.path.join(mnt, 'etc/crypttab')
    os.makedirs(os.path.dirname(ct), exist_ok=True)
    existing_lines: list[str] = []
    if os.path.isfile(ct):
        try:
            with open(ct, 'r', encoding='utf-8') as fh:
                existing_lines = fh.read().splitlines()
        except Exception:
            existing_lines = []

    normalized_key: str | None = None
    if enable_keyfile:
        normalized_key = _validate_keyfile_path(keyfile_path)
        if not normalized_key:
            raise ValueError("keyfile path required when enable_keyfile=True")

    if normalized_key:
        desired_key = normalized_key
    elif passfile:
        desired_key = passfile
    else:
        desired_key = 'none'

    if keyscript_path:
        desired_key = f"{desired_key} keyscript={keyscript_path}"

    existing_options: list[str] = []
    preserved: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            preserved.append(line)
            continue
        parts = stripped.split()
        if parts and parts[0] == 'cryptroot':
            if len(parts) > 3:
                existing_options = parts[3].split(',')
            continue
        preserved.append(line)

    def _merge_options(initial: list[str], required: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for opt in initial:
            candidate = opt.strip()
            if not candidate:
                continue
            if candidate not in seen:
                merged.append(candidate)
                seen.add(candidate)
        for opt in required:
            if opt not in seen:
                merged.append(opt)
                seen.add(opt)
        return merged

    required_opts = ['luks']
    if enable_keyfile:
        required_opts.append('discard')
    merged_options = _merge_options(existing_options, required_opts)
    if enable_keyfile:
        merged_options = [opt for opt in merged_options if opt != 'initramfs'] + ['initramfs']
    options_field = ','.join(merged_options)
    desired_line = f"cryptroot UUID={luks_uuid}  {desired_key}  {options_field}".rstrip()

    if preserved and preserved[-1].strip():
        preserved.append(desired_line)
    else:
        preserved.append(desired_line)

    new_text = '\n'.join(preserved).rstrip() + '\n'

    current = ''
    try:
        with open(ct, 'r', encoding='utf-8') as fh:
            current = fh.read()
    except FileNotFoundError:
        current = ''

    if current == new_text:
        return

    with open(ct, 'w', encoding='utf-8') as f:
        f.write(new_text)
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            pass


def write_initramfs_conf(mnt: str, keyfile_pattern: str = "/etc/cryptsetup-keys.d/*.key") -> tuple[str, str, str]:
    conf_dir = os.path.join(mnt, "etc", "initramfs-tools", "conf.d")
    os.makedirs(conf_dir, exist_ok=True)
    path = os.path.join(conf_dir, "cryptsetup")
    desired = f"KEYFILE_PATTERN={keyfile_pattern}\nUMASK=0077\n"
    try:
        current = open(path, "r", encoding="utf-8").read()
    except FileNotFoundError:
        raise
    #     current = None
    # if current == desired:
    #     return
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(desired)
        try:
            fh.flush()
            os.fsync(fh.fileno())
        except Exception:
            raise

    return path, current, desired


def _resolve_root_mapper(root_mapper: str | None, vg: str | None, lv: str | None) -> str:
    if root_mapper and root_mapper.strip():
        return root_mapper.strip()
    vg_name = (vg or 'rp5vg').strip() or 'rp5vg'
    lv_name = (lv or 'root').strip() or 'root'
    return f"/dev/mapper/{vg_name}-{lv_name}"


def write_cmdline(
        dst_boot_fw: str,
        luks_uuid: str,
        root_mapper: str | None = None,
        vg: str | None = None,
        lv: str | None = None,
):
    p = os.path.join(dst_boot_fw, 'cmdline.txt')
    mapper_path = _resolve_root_mapper(root_mapper, vg, lv)
    cmd_parts = [
        f"cryptdevice=UUID={luks_uuid}:cryptroot",
        f"root={mapper_path}",
        "rootfstype=ext4",
        "rootwait",
    ]
    cmd = " ".join(cmd_parts)
    if os.path.exists(p):
        try:
            txt = open(p, 'r', encoding='utf-8').read().strip()
        except Exception:
            txt = ''
        if txt == cmd:
            return
    with open(p, 'w', encoding='utf-8') as f:
        f.write(f"{cmd}\n")
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            pass


def _line_lookup(lines: Iterable[str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip().lower()
        else:
            key = stripped.split(None, 1)[0].strip().lower()
        lookup[key] = stripped
    return lookup

def write_config(
        dst_boot_fw: str,
        initramfs_image: str = "initramfs_2712"
):
    import os, re

    path = os.path.join(dst_boot_fw, "config.txt")
    os.makedirs(dst_boot_fw, exist_ok=True)

    lines: list[str] = []
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except Exception:
            lines = []

    # If an explicit initramfs line already exists (non-comment), do nothing.
    has_initramfs = any(
        (not l.strip().startswith("#")) and re.match(r"\s*initramfs\s+\S+\s+followkernel\s*$", l, re.I)
        for l in lines
    )
    if has_initramfs:
        return

    # Ensure we’re in [all] context at the end; append header if file is empty or missing [all].
    if not any(re.match(r"\s*\[all]\s*$", l, re.I) for l in lines):
        if lines and lines[-1].strip() != "":
            lines.append("")  # keep a clean blank line before [all]
        lines.append("[all]")

    # Append the single required line.
    lines.append(f"initramfs {initramfs_image} followkernel")

    # Write back only if changed; preserve a trailing newline.
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")
        try:
            fh.flush()
            os.fsync(fh.fileno())
        except Exception:
            raise


def assert_cmdline_uuid(dst_boot_fw: str, luks_uuid: str, root_mapper: str | None = None):
    p = os.path.join(dst_boot_fw, 'cmdline.txt')
    if not os.path.isfile(p):
        raise RuntimeError('cmdline.txt missing')
    txt = open(p, 'r', encoding='utf-8').read()
    if f'cryptdevice=UUID={luks_uuid}' not in txt:
        raise RuntimeError('cmdline.txt cryptdevice UUID mismatch')
    mapper_path = _resolve_root_mapper(root_mapper, None, None)
    if mapper_path not in txt:
        raise RuntimeError(f'cmdline.txt missing root mapper {mapper_path}')


def assert_crypttab_uuid(mnt: str, luks_uuid: str):
    ct = os.path.join(mnt, 'etc/crypttab')
    if not os.path.isfile(ct):
        raise RuntimeError('crypttab missing')
    txt = open(ct, 'r', encoding='utf-8').read()
    import re
    m = re.search(r'^cryptroot\s+UUID=([^\s]+)\s+', txt, re.M)
    if not m:
        raise RuntimeError('crypttab missing cryptroot line')
    if m.group(1) != luks_uuid:
        raise RuntimeError('crypttab UUID mismatch')


def ensure_initramfs_conf(mnt):
    try:
        conf_dir = os.path.join(mnt, 'etc', 'initramfs-tools', 'conf.d')
        os.makedirs(conf_dir, exist_ok=True)
        conf_path = os.path.join(conf_dir, 'cryptsetup')
        content = 'KEYFILE_PATTERN=/etc/cryptsetup-keys.d/*.key\nUMASK=0077\n'
        with open(conf_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return conf_path, content
    except Exception:
        raise


def ensure_firmware_initramfs_line(fw_config_path, image_name='initramfs_2712'):
    try:
        lines = []
        if os.path.exists(fw_config_path):
            with open(fw_config_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        wanted = f'initramfs {image_name} followkernel\n'
        if not any(l.strip().startswith('initramfs ') for l in lines):
            lines.append(wanted)
            with open(fw_config_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
    except Exception as e:
        raise
