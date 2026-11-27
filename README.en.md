# ThinkBook 14+ 2022 (i9-12900H / Iris Xe) — macOS Tahoe 26.7.1 EFI

[中文](README.md) | **English**

OpenCore EFI for **Lenovo ThinkBook 14+ 2022 (iGPU-only, Intel Core i9-12900H / Intel Iris Xe 96 EU)** running **macOS Tahoe 26.7.1 (Build `25G241`)**, featuring native 2.8K 90Hz acceleration, full-brightness PWM calibration, 90Hz cursor stripe fix (`SoftCursorFix.kext`), hybrid CPU turbo/power management, and built-in speaker audio.

> **Important Version Restriction**: The graphics stack and kernel patches in this repository are strictly tied to **macOS Tahoe 26.7.1 (`25G241`)**. Do not casually install macOS point updates.

---

## Screenshots

| About This Mac (i9-12900H / Iris Xe 1536 MB / 2880×1800) | Daily Desktop (2.8K 90Hz HiDPI / 45°C Idle) |
| :---: | :---: |
| ![About This Mac](assets/machine_info.png) | ![Daily Desktop](assets/github.png) |

---

## Hardware & Feature Status

| Component | Hardware / Solution | Status | Notes |
| :--- | :--- | :---: | :--- |
| **Model** | Lenovo ThinkBook 14+ 2022 (iGPU-only) | ✅ | Disable Secure Boot in BIOS, set storage to AHCI/NVMe, keep E-cores enabled |
| **CPU** | Intel Core i9-12900H (6P + 8E, 20 threads) | ✅ | `CpuTopologyRebuild` + `-ngreenpm` unlocks hybrid HWP/EPP turbo and C8/C10 power saving |
| **iGPU** | Intel Iris Xe 96 EU (`8086:46A6`) | ✅ | Spoofed `9A49` + `NootedGreen` + `YogaGMSFix` (60 MiB GMS) + Metal 2 / Liquid Glass |
| **Internal Display** | AUO `B140QAN04.0` (2880×1800 @ 90Hz) | ✅ | Native `1440×900 @ 90Hz` HiDPI; `ngreenblmax=17777` restores full 0–100% brightness |
| **90Hz Cursor** | `SoftCursorFix.kext` (`-swcursor`) | ✅ | Fixes 90Hz hardware cursor horizontal black stripes via Apple's native Metal software cursor fallback |
| **Audio** | Realtek ALC257 (`alcid=99`) | ✅ | `AppleALC` + `SimpleHDA 1.0.2` (`MinKernel=25.0.0`); built-in speakers and microphone work |
| **Wi-Fi / Bluetooth** | Intel AX210 (replaces stock MT7921) | ✅ | `AirportItlwm-Tahoe` for native Wi-Fi menu; `IntelBluetoothFirmware` + `BlueToolFixup` with AirPods auto-switching |
| **Keyboard / Trackpad** | Built-in Keyboard + ELAN0662 (I2C) | ✅ | `VoodooPS2Controller` + `VoodooI2C` (`-vi2c-force-polling`) |
| **Display Sleep / S0ix** | `XE-FBDPMS` + S0ix disabled | ⚠️ | **Display sleep & wake work reliably**; S3/S0ix full system sleep is unsupported (must be disabled — see below) |
| **HW Video Decode** | H.264 / HEVC (`-ngreengva`) | Optional | Requires manually building/installing upstream `VADriver`; breaks FairPlay DRM (Apple Music / Apple TV+) |
| **AirDrop / Thunderbolt** | AWDL / Thunderbolt 3 | ❌ / Disabled | Intel Wi-Fi does not support AirDrop/AWDL; Thunderbolt SSDT is disabled by default |

---

## Repository Layout

```text
.
├── EFI/
│   ├── BOOT/
│   └── OC/
│       ├── config.plist            # Daily accelerated config (fully tuned, SMBIOS stripped)
│       ├── config-install.plist    # Unspoofed installer & permanent rescue config (SMBIOS stripped)
│       ├── config-register.plist   # One-time 9A49 registration transition config (SMBIOS stripped)
│       ├── ACPI/                   # Model-specific ACPI patches
│       ├── Drivers/                # OpenCore UEFI drivers
│       └── Kexts/                  # Complete kext set (NootedGreen / YogaGMSFix / SoftCursorFix / SimpleHDA)
├── patches/
│   └── thinkbook-register.patch    # Upstream install script patch adapted for ThinkBook
└── research/
    └── soft-cursor-fix/            # SoftCursorFix.kext source code and native macOS build script
```

---

## Quick Start Guide

### 1. Generate and Fill Your Own SMBIOS
All three plists (`config.plist`, `config-install.plist`, `config-register.plist`) have their SMBIOS values cleared.  
Use [GenSMBIOS](https://github.com/corpnewt/GenSMBIOS) to generate a **`MacBookPro16,2`** identity and populate `SystemSerialNumber`, `MLB`, `SystemUUID`, and `ROM` **across all three plist files**.

### 2. Three-Stage Deployment
1. **Install macOS (`config-install.plist`)**
   - Temporarily replace `EFI/OC/config.plist` on your USB installer with `config-install.plist` (no GPU spoof, uses `-igfxvesa`).
   - Install **macOS Tahoe 26.7.1 (`25G241`)** to your target NVMe drive, boot to the desktop, and verify `sw_vers -buildVersion` returns `25G241`.
2. **Register the TGL Graphics Stack (`config-register.plist`, run once only)**
   - Switch the active USB config to `config-register.plist`, reboot, and verify `IGPU` reports `device-id = <499a0000>`.
   - Clone upstream [Hackintosh-XPS13Plus-IrisXe-Tahoe](https://github.com/JulioNectar/Hackintosh-XPS13Plus-IrisXe-Tahoe), apply `patches/thinkbook-register.patch` from this repo, and run `zsh install.sh` to install the graphics driver, Metal bundle, and shader compiler, then rebuild AuxKC (approve the system extension in *Privacy & Security*).
   - > **Warning**: Once the TGL driver is installed on the system volume, **never boot with `config-register.plist` again**. Whenever you need unaccelerated rescue boot, use `config-install.plist` only.
3. **Boot Daily Accelerated Desktop (`config.plist`)**
   - Switch back to the default `EFI/OC/config.plist` and reboot into native `2880×1800 @ 90Hz` Metal 2 acceleration.
   - Once verified stable, copy the complete `EFI` folder to the dedicated EFI partition on your macOS NVMe drive and keep the USB drive as a rescue disk.

---

## Recommended Post-Install Tuning

### 1. Disable System Sleep, Keep Display Sleep Only (Strongly Recommended)
The ThinkBook 14+ 2022 only supports Modern Standby (S0ix), which cannot wake cleanly under macOS. Lock the machine to "display sleep only, no system sleep":

```bash
sudo pmset -a sleep 0 disablesleep 1 hibernatemode 0 standby 0 powernap 0 proximitywake 0 halfdim 1 disksleep 10
sudo pmset -c womp 0 displaysleep 10
sudo pmset -b displaysleep 3
sudo rm -f /var/vm/sleepimage
```

### 2. Dual-NVMe Coexistence with Windows
If macOS and Windows are installed on separate NVMe drives, set `Misc > Security > ScanPolicy` to **`257`** (APFS only) in the internal macOS OpenCore config so OpenCore only boots macOS. Press **`F12`** at startup and choose `Windows Boot Manager` whenever you want to boot stock Windows untouched.

### 3. Smoothness & Optional Tweaks
- **UI Smoothness**: Enable **Reduce Transparency** (*System Settings → Accessibility → Display*) to significantly cut Tahoe Liquid Glass compositing overhead in 3D maps, remote desktop, and other graphics-heavy apps.
- **Optional Wi-Fi 6 (802.11ax)**: Append `itlwm_he=1` to `boot-args` to enable Wi-Fi 6 speeds on the AX210.
- **Optional H.264 / HEVC Hardware Decode**: Follow the upstream repo to build/install `/Library/GPUBundles/AppleIntelTGLGraphicsVADriver.bundle` and add `-ngreengva` to `boot-args` (note: this disables FairPlay playback in Apple Music / Apple TV+).
- **Key Boot-Args**:
  - `-xenobb`: Skips `XE-BOOTHOLD` boot-time blanking wait to prevent black-screen lockups at boot.
  - `ngreenblmax=17777`: Matches the `96000` PWM period of the `AUO B140QAN04.0` panel to restore 100% max brightness.
  - `-swcursor`: Enables `SoftCursorFix.kext` (remove it or add `-swcursoroff` to disable).
  - `-ngreenpm`: Enables hybrid CPU turbo and power management (check status via `sysctl debug.xepm`).

---

## Credits

This project builds directly upon the work of the open-source Hackintosh community:
- [Hackintosh-XPS13Plus-IrisXe-Tahoe](https://github.com/JulioNectar/Hackintosh-XPS13Plus-IrisXe-Tahoe) — macOS Tahoe Iris Xe acceleration, NootedGreen, libxedrv, XE-PM, and toolchain
- [Hackintosh-LenovoYoga-IrisXe-Tahoe](https://github.com/willyyypatootieee/Hackintosh-LenovoYoga-IrisXe-Tahoe) — 12th-gen `46A6` 60 MiB GMS fix (`YogaGMSFix.kext`)
- [ThinkBook14-AlderLake-Hackintosh](https://github.com/ruixian94/ThinkBook14-AlderLake-Hackintosh) — ThinkBook 14+ 2022 ACPI and peripheral baseline
- [SimpleHDA](https://github.com/laobamac/SimpleHDA) — macOS Tahoe AppleHDA audio restoration
- [Acidanthera](https://github.com/acidanthera) — OpenCore, Lilu, VirtualSMC, AppleALC, BlueToolFixup, and core kexts
- **ChatGPT 6.2 Sol** & **Gemini 4 Neon** — Assistance with driver reverse engineering, `SoftCursorFix` development/debugging, and documentation
