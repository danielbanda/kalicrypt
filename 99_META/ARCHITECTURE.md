# RP5 NVMe Provisioner — Refactored Architecture

## Goal
Transform the current **monolithic** ``python -m rp5.provision` (see docs/usage/provisioning.md)` into a maintainable, testable, and safe **modular package**, without breaking CLI semantics or single-command UX.

---

## Package Layout
```
provision/
  cli.py                 # argparse & orchestration (entrypoint)
  safety.py              # destructive-operation guards
  executil.py            # subprocess wrapper, logging, dry-run, settle
  devices.py             # device probing, holders, UUID mapping
  partitioning.py        # GPT layout, wipefs, verification
  luks_lvm.py            # LUKS + LVM lifecycle
  mounts.py              # mounting/unmounting, bind mounts
  root_sync.py           # rsync with safe excludes
  boot_plumbing.py       # fstab, crypttab, cmdline writers/validators
  firmware.py            # populate_esp() + firmware assertions
  initramfs.py           # rebuild and verify initramfs
  postcheck.py           # validation suite (Python + shell parity)
  model.py               # dataclasses: Plan, DeviceMap, Mounts, Flags
  errors.py              # custom exceptions
```

---

## Responsibilities

### cli.py
- Parse arguments, build `ProvisionPlan`.
- Drive ordered calls into modules.
- Modes: `--plan`, `--dry-run`, ``--yes` (full provision)`, ``--do-postcheck``, ``--do-postcheck``, `--tpm-keyscript`.

### safety.py
- `refuse_if_target_collides(target)`: refuse if same device as live root or ESP.
- Device/UUID matrix echo before destructive ops.

### executil.py
- `run(cmd, check=True, allow_fail=False, env=None) → Result`.
- Logs every command with timestamp and duration.
- Handles `--dry-run`, retries, timeouts, and `udev_settle()`.

### devices.py
- `probe(target) -> DeviceMap(p1, p2, p3, syspaths, uuids)`.
- Manage holders: `kill_holders()`, `swapoff_all()`.
- Helpers: `uuid_of(path)`, `fs_type(path)`.

### partitioning.py
- Apply GPT layout: ESP, /boot, LUKS (GUID **8309**).
- `wipefs` for ``--yes` (full provision)`.
- Verify partition table matches plan.

### luks_lvm.py
- Create/open/close LUKS mapping.
- Create/deactivate VG + LV.
- Later: integrate TPM keyscript support.

### mounts.py
- Mount root, /boot, ESP at `/boot/firmware`.
- Bind mounts for chroot.
- Cleanup with `sync` + settle.

### root_sync.py
- Rsync root filesystem to NVMe.
- Excludes: `/proc`, `/sys`, `/dev`.
- Leaves firmware copying to `firmware.py`.

### boot_plumbing.py
- Writers: `fstab`, `crypttab`, `cmdline.txt`.
- Validators: `assert_cmdline_uuid_correct()`.

### firmware.py
- `populate_esp(src_candidates, dst_boot_dir, preserve_cmdline, preserve_config)`.
- Assert essentials: `start4.elf`, `fixup4.dat`, `bcm2712*.dtb`, `overlays/`.

### initramfs.py
- Ensure packages present.
- Rebuild initramfs and update `config.txt`.
- Verify initramfs exists, size sane, includes `cryptsetup` + `lvm`.

### postcheck.py
- Parity with existing shell postcheck.
- Validate firmware payload, fstab, crypttab, cmdline.

### model.py
- Dataclasses: `ProvisionPlan`, `DeviceMap`, `Mounts`, `Flags`.
- Keeps function signatures clean, testable.

### errors.py
- Typed errors for user-facing failures (`HolderStuckError`, `FirmwareMissingError`, etc.).

---

## Execution Flow
1. **cli** → parse flags.
2. **safety** → refuse unsafe target.
3. **devices** → aggressive pre-cleanup (swapoff, fuser/lsof, dmsetup retry).
4. **partitioning** → zap/create GPT (ESP, /boot, LUKS).
5. **luks_lvm** → format/open LUKS, create VG/LV.
6. **mounts** → mount targets, prepare bind mounts.
7. **firmware** → copy firmware into ESP, preserve cmdline/config.
8. **root_sync** → rsync root (no firmware).
9. **boot_plumbing** → write fstab/crypttab/cmdline.
10. **initramfs** → rebuild, verify matches config.txt.
11. **postcheck** → run assertions.
12. **mounts** → teardown with sync/settle.
13. Emit structured JSON result.

---

## Migration Phases
- **Phase 0:** Extract helpers (`executil`, `errors`, `model`).
- **Phase 1:** Devices/partitioning/luks_lvm/mounts.
- **Phase 2:** Root_sync, firmware, boot_plumbing, initramfs, postcheck.
- **Phase 3:** New `cli.py` becomes primary entry; ``python -m rp5.provision` (see docs/usage/provisioning.md)` just calls into it.
- **Phase 4:** Add tests & fixtures (unit + integration dry-run).
- **Phase 5:** Add optional TPM keyscript module.

---

## Cross-Cutting Rules
- Idempotent steps; check “already done?”.
- `--dry-run` respected by all commands.
- Structured logs (`ete_nvme_provision.json` + human-readable stream).
- Secrets redacted from logs.
- Backoff + retries for long ops.
