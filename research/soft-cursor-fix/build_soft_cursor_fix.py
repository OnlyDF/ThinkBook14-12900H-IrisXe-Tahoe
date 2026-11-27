#!/usr/bin/env python3
"""Build SoftCursorFix.kext natively on macOS into /Users/d/ThinkBook-Build/."""
from pathlib import Path
import plistlib
import shutil
import subprocess

SRC_DIR = Path(__file__).resolve().parent
DEPS = Path("/Users/d/Hackintosh-XPS13Plus-IrisXe-Tahoe/build/deps")
SDK = DEPS / "MacKernelSDK"
LILU = DEPS / "Lilu.kext/Contents/Resources"
OUT_ROOT = Path("/Users/d/ThinkBook-Build")
PRODUCT = "SoftCursorFix"
BUNDLE_ID = "local.thinkbook.driver.SoftCursorFix"


def run(cmd):
    cmd = [str(c) for c in cmd]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main():
    stage = OUT_ROOT / "stage-swcursor"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    kext = OUT_ROOT / f"{PRODUCT}.kext"
    if kext.exists():
        shutil.rmtree(kext)
    contents = kext / "Contents"
    (contents / "MacOS").mkdir(parents=True)

    info = dict(
        CFBundleDevelopmentRegion="en",
        CFBundleExecutable=PRODUCT,
        CFBundleIdentifier=BUNDLE_ID,
        CFBundleInfoDictionaryVersion="6.0",
        CFBundleName=PRODUCT,
        CFBundlePackageType="KEXT",
        CFBundleShortVersionString="0.1.0",
        CFBundleVersion="0.1.0",
        OSBundleRequired="Root",
        OSBundleLibraries={
            "as.vit9696.Lilu": "1.7.0",
            "com.StezzaPilot.NootedGreen": "1.0.0",
            **{
                f"com.apple.kpi.{k}": "12.0.0"
                for k in ("bsd", "dsep", "iokit", "libkern", "mach", "unsupported")
            },
        },
        IOKitPersonalities={
            PRODUCT: dict(
                CFBundleIdentifier=BUNDLE_ID,
                IOClass=PRODUCT,
                IOMatchCategory=PRODUCT,
                IOProviderClass="IOResources",
                IOResourceMatch="IOKit",
                IOProbeScore=1000,
            )
        },
    )
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))

    info_c = stage / "info.c"
    info_c.write_text(
        f"""#include <mach/mach_types.h>
extern kern_return_t {PRODUCT}_kern_start(kmod_info_t *, void *);
extern kern_return_t {PRODUCT}_kern_stop(kmod_info_t *, void *);
__attribute__((visibility("default"))) KMOD_EXPLICIT_DECL({BUNDLE_ID}, "0.1.0", {PRODUCT}_kern_start, {PRODUCT}_kern_stop)
__private_extern__ kmod_start_func_t *_realmain = 0;
__private_extern__ kmod_stop_func_t *_antimain = 0;
__private_extern__ int _kext_apple_cc = __APPLE_CC__;
"""
    )

    flags = [
        "-target", "x86_64-apple-macos13",
        "-mkernel", "-nostdinc", "-fno-builtin", "-fno-common",
        "-fno-stack-protector", "-mmmx", "-msse", "-msse2",
        "-DKERNEL", "-DKERNEL_PRIVATE", "-DDRIVER_PRIVATE",
        "-DAPPLE", "-DNeXT", "-DDEBUG=1", "-DAPPLE_KEXT_ASSERTIONS=1",
        f"-DPRODUCT_NAME={PRODUCT}", "-DMODULE_VERSION=0.1.0",
        "-D__null_terminated=", "-D__stateful_pure=",
        "-isystem", SDK / "Headers",
        f"-I{LILU}",
        "-O2",
    ]
    cppflags = [
        "-std=gnu++17", "-nostdinc++", "-fno-exceptions", "-fno-rtti",
        "-fapple-kext", "-mllvm", "-disable-atexit-based-global-dtor-lowering",
        "-Wno-deprecated-declarations", "-Wno-inconsistent-missing-override",
        "-Wno-unused-parameter",
    ]

    run(["clang", *flags, "-c", info_c, "-o", stage / "info.o"])
    run(["clang++", *flags, *cppflags, "-c", SRC_DIR / f"{PRODUCT}.cpp", "-o", stage / f"{PRODUCT}.o"])
    run(["clang++", *flags, *cppflags, "-c", LILU / "Library/plugin_start.cpp", "-o", stage / "plugin_start.o"])

    binary = contents / "MacOS" / PRODUCT
    run([
        "ld", "-arch", "x86_64", "-kext", "-export_dynamic",
        "-macosx_version_min", "13.0",
        stage / "info.o",
        stage / f"{PRODUCT}.o",
        stage / "plugin_start.o",
        SDK / "Library/x86_64/libkmod.a",
        "-o", binary,
    ])

    undef = subprocess.check_output(["nm", "-u", str(binary)], text=True)
    assert "atexit" not in undef, f"Unexpected atexit in undefined symbols:\n{undef}"

    run(["codesign", "--force", "--sign", "-", str(kext)])
    run(["codesign", "--verify", "--verbose", str(kext)])
    run(["file", str(binary)])
    print(f"\nBUILT OK: {kext}")


if __name__ == "__main__":
    main()
