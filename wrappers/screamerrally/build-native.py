#!/usr/bin/env python3
"""Package original Screamer DOS game files with an Apple Silicon DOSBox runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import stat
import struct
import subprocess
import tempfile


PROFILES = {
    "screamer": {"title": "Screamer", "program": "STARTH.EXE", "cue": "SCREAM.DAT", "image": "SCREAM.gog", "irq": 5,
        "distance_options": ["Original", "Extended (+20% object visibility)", "Extended (+30% object visibility)", "Extended (+40% object visibility)"],
        "distance_help": "Extends managed object visibility. The original game's scenery and terrain limits remain.",
    },
    "screamer2": {"title": "Screamer 2", "program": "START65H.EXE", "cue": "GAME.DAT", "image": "GAME.GOG", "irq": 7,
        "distance_options": ["Original", "Extended (2×)"],
        "distance_help": "Extends scenery and object visibility. Some terrain and clipping limits remain.",
    },
    "screamerrally": {
        "title": "Screamer Rally", "program": "SR/START65H.EXE",
        "dos_command": "cd SR\nSTART65H.EXE", "cue": "cd/srally.cue",
        "image": "cd/srally.img", "irq": 7, "readonly_entries": ["cd"],
        "distance_options": ["Original", "Extended (2×)", "Farther (2.5×, experimental)"],
        "distance_help": "Farther is experimental and can reveal scenery gaps or affect performance.",
    },
}
MACH_MAGICS = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf"}


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def copy_contents(source, target, *, ignore=None):
    """Build a new bundle from file contents, without importing download metadata."""
    if source.is_symlink():
        target.symlink_to(source.readlink())
    elif source.is_dir():
        target.mkdir(parents=True, exist_ok=False)
        children = list(source.iterdir())
        ignored = set(ignore(str(source), [p.name for p in children])) if ignore else set()
        for child in children:
            if child.name not in ignored:
                copy_contents(child, target / child.name, ignore=ignore)
        target.chmod(stat.S_IMODE(source.stat().st_mode))
    else:
        shutil.copyfile(source, target)
        target.chmod(stat.S_IMODE(source.stat().st_mode))


def bundle(game_key, source, runtime, output, sign_identity="-"):
    profile = {"key": game_key, **PROFILES[game_key]}
    assets = Path(__file__).resolve().parent
    enhancements = json.loads((assets / f"{game_key}-patches.json").read_text())
    original = source / enhancements["original"]
    if hashlib.sha256(original.read_bytes()).hexdigest() != enhancements["sha256"]:
        raise SystemExit(f"Unsupported {profile['title']} executable; optional enhancements require the recognized original")
    profile["enhancements"] = enhancements
    dos4gw = str(Path(profile["program"]).parent / "DOS4GW.EXE")
    for name in (profile["program"], profile["cue"], profile["image"], dos4gw):
        if not (source / name).is_file():
            raise SystemExit(f"Missing game file: {source / name}")
    runtime_binary = runtime / "Contents/MacOS/dosbox"
    if not runtime_binary.is_file():
        raise SystemExit("--runtime must point to the official DOSBox Staging.app bundle")
    output.mkdir(parents=True, exist_ok=True)
    app = output / f"{profile['title']}.app"
    if app.exists():
        raise SystemExit(f"Refusing to replace an existing app: {app}")
    copy_contents(runtime, app)
    contents = app / "Contents"
    resources = contents / "Resources"
    if game_key == "screamerrally":
        # Preserve the game's C:\SR installation paths. The two extra Windows
        # patch tools and Windows launch shortcuts are not part of the DOS runtime.
        copy_contents(source / "SR", resources / "game/SR",
                        ignore=shutil.ignore_patterns("Patch - Screamer Rally*.exe", "*.PIF", "*.VXD", ".DS_Store"))
        (resources / "game/cd").mkdir()
        for name in (profile["cue"], profile["image"]):
            shutil.copyfile(source / name, resources / "game" / name)
    else:
        copy_contents(source, resources / "game")
    icon = source.parent / "app.icns"
    if not icon.is_file():
        icon = source.parent / "GameIcon.icns"
    if icon.is_file():
        shutil.copyfile(icon, resources / "GameIcon.icns")
    elif game_key == "screamerrally":
        # Convert the supplied game's original icon; no new artwork is generated.
        with tempfile.TemporaryDirectory(prefix="rally-icon-") as temp:
            iconset = Path(temp) / "GameIcon.iconset"
            iconset.mkdir()
            original_png = Path(temp) / "original.png"
            run(["sips", "--setProperty", "format", "png", source / "SR/CONFIG/SR.ICO",
                 "--out", original_png], capture_output=True)
            for size in (16, 32, 128, 256, 512):
                for scale in (1, 2):
                    pixels = str(size * scale)
                    suffix = "@2x" if scale == 2 else ""
                    run(["sips", "--resampleHeightWidth", pixels, pixels, original_png,
                         "--out", iconset / f"icon_{size}x{size}{suffix}.png"], capture_output=True)
            # Store the PNG representations in the standard ICNS container. This
            # also works on hosts whose legacy iconutil rejects converted ICOs.
            representations = [("icp4", "icon_16x16.png"), ("icp5", "icon_32x32.png"),
                               ("icp6", "icon_32x32@2x.png"), ("ic07", "icon_128x128.png"),
                               ("ic08", "icon_256x256.png"), ("ic09", "icon_512x512.png"),
                               ("ic10", "icon_512x512@2x.png")]
            chunks = []
            for kind, name in representations:
                png = (iconset / name).read_bytes()
                chunks.append(kind.encode("ascii") + struct.pack(">I", len(png) + 8) + png)
            payload = b"".join(chunks)
            (resources / "GameIcon.icns").write_bytes(b"icns" + struct.pack(">I", len(payload) + 8) + payload)
    else:
        shutil.copyfile(resources / "dosbox-staging.icns", resources / "GameIcon.icns")

    shutil.copyfile(assets / "shaders/trilogy-widescreen.glsl", resources / "shaders/trilogy-widescreen.glsl")
    shutil.copyfile(assets / "THIRD-PARTY-NOTICES.txt", resources / "Enhancement-notices.txt")
    shutil.copyfile(assets / f"artwork/{game_key}/SelectionBackground.png", resources / "SelectionBackground.png")

    (resources / "game-profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    config = """# Native Apple Silicon game wrapper; generated paths are refreshed on launch.
[sdl]
fullscreen = @FULLSCREEN@
fullscreen_mode = standard
window_size = @WINDOW_SIZE@
output = opengl

[dosbox]
machine = svga_s3
memsize = 16

[cpu]
core = auto
cpu_cycles = 3000
cpu_cycles_protected = max

[render]
aspect = @ASPECT@
viewport = fit
integer_scaling = off
shader = @SHADER@

[sblaster]
sbtype = sb16
sbbase = 220
irq = IRQ_VALUE
dma = 1
hdma = 5

[autoexec]
@echo off
mount c "."
imgmount d "@DISC_CUE@" -t iso
c:
@PROGRAM@
exit
""".replace("IRQ_VALUE", str(profile["irq"]))
    (resources / "game.conf.in").write_text(config)
    info = {
        "CFBundleDevelopmentRegion": "en", "CFBundleDisplayName": profile["title"],
        "CFBundleName": profile["title"], "CFBundleExecutable": "GameLauncher",
        "CFBundleIdentifier": f"local.screamer-native.{game_key}", "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.2.1", "CFBundleVersion": "6",
        "CFBundleIconFile": "GameIcon.icns", "LSMinimumSystemVersion": "12.0",
        "LSRequiresNativeExecution": True, "LSApplicationCategoryType": "public.app-category.racing-games",
        "NSHighResolutionCapable": True, "NSPrincipalClass": "NSApplication",
        "NSHumanReadableCopyright": "Original game belongs to its respective owners. Includes DOSBox Staging (GPL-2.0-or-later).",
    }
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(info, handle)

    launcher = Path(__file__).resolve().parent / "launcher.m"
    run(["xcrun", "clang", "-arch", "arm64", "-mmacosx-version-min=12.0", "-fobjc-arc", "-O2",
         "-Wall", "-Wextra", "-Werror", "-framework", "AppKit", "-framework", "Foundation",
         launcher, "-o", contents / "MacOS/GameLauncher"])

    helper = contents / "Helpers/Game Options.app/Contents"
    (helper / "MacOS").mkdir(parents=True)
    (helper / "Resources").mkdir()
    shutil.copyfile(contents / "MacOS/GameLauncher", helper / "MacOS/GameOptions")
    shutil.copymode(contents / "MacOS/GameLauncher", helper / "MacOS/GameOptions")
    shutil.copyfile(resources / "GameIcon.icns", helper / "Resources/GameIcon.icns")
    shutil.copyfile(resources / "SelectionBackground.png", helper / "Resources/SelectionBackground.png")
    helper_info = {
        "CFBundleDevelopmentRegion": "en", "CFBundleName": f"{profile['title']} Options",
        "CFBundleDisplayName": f"{profile['title']} Options", "CFBundleExecutable": "GameOptions",
        "CFBundleIdentifier": f"local.screamer-native.{game_key}.options",
        "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "1.2.1",
        "CFBundleVersion": "6", "CFBundleIconFile": "GameIcon.icns",
        "LSMinimumSystemVersion": "12.0", "LSRequiresNativeExecution": True,
        "LSUIElement": True, "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
    }
    with (helper / "Info.plist").open("wb") as handle:
        plistlib.dump(helper_info, handle)

    # The pinned 0.83.1 runtime has this one entitlement. Reproduce it after
    # thinning; modern codesign displays DER entitlements as a human-readable dict.
    entitlements = {"com.apple.security.cs.allow-jit": True}
    entitlements_path = output / f"{game_key}-runtime-entitlements.plist"
    with entitlements_path.open("wb") as handle:
        plistlib.dump(entitlements, handle)

    architectures = []
    for path in sorted(contents.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as handle:
            magic = handle.read(4)
        if magic not in MACH_MAGICS:
            continue
        archs = run(["lipo", "-archs", path], capture_output=True, text=True).stdout.split()
        if "arm64" not in archs:
            raise SystemExit(f"Runtime contains a binary without ARM64 support: {path}: {archs}")
        if archs != ["arm64"]:
            thin = path.with_name(path.name + ".arm64-tmp")
            run(["lipo", path, "-thin", "arm64", "-output", thin])
            shutil.copymode(path, thin)
            thin.replace(path)
        architectures.append({"path": str(path.relative_to(app)), "architectures": ["arm64"]})
        command = ["codesign", "--force", "--sign", sign_identity, "--timestamp=none"]
        if path == contents / "MacOS/dosbox":
            command += ["--entitlements", entitlements_path]
        run(command + [path], capture_output=True)

    # Reject dependencies on build-machine absolute paths. Startup checks exercise
    # the pinned runtime's relative dependency paths.
    for binary in architectures:
        path = app / binary["path"]
        libraries = run(["otool", "-L", path], capture_output=True, text=True).stdout.splitlines()[1:]
        for line in libraries:
            dependency = line.strip().split(" (", 1)[0]
            if dependency.startswith("/") and not dependency.startswith(("/System/Library/", "/usr/lib/")):
                raise SystemExit(f"Non-bundled dependency in {path}: {dependency}")

    # Nested optional plugin bundles require their resource signatures refreshed too.
    nested_bundles = sorted((p for p in contents.rglob("*") if p.is_dir() and p.suffix in {".app", ".framework", ".clap", ".bundle"}), key=lambda p: len(p.parts), reverse=True)
    for nested in nested_bundles:
        run(["codesign", "--force", "--sign", sign_identity, "--timestamp=none", nested], capture_output=True)
    run(["codesign", "--force", "--sign", sign_identity, "--timestamp=none", app], capture_output=True)
    run(["codesign", "--verify", "--deep", "--strict", app], capture_output=True)
    report = {"app": str(app), "runtime": "DOSBox Staging 0.83.1", "host_architecture": "arm64",
              "game": profile, "binaries": architectures, "signature": "ad-hoc, verified" if sign_identity == "-" else "development identity, verified"}
    (output / f"{game_key}-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(app)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", choices=PROFILES, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--game-data", type=Path)
    source.add_argument("--package", type=Path)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sign-identity", default="-", help="Local signing identity; defaults to ad-hoc")
    args = parser.parse_args()
    if args.game_data:
        bundle(args.game, args.game_data.resolve(), args.runtime.resolve(), args.output.resolve(), args.sign_identity)
    else:
        with tempfile.TemporaryDirectory(prefix="screamer-gog-extract-") as temp:
            expanded = Path(temp) / "expanded"
            run(["pkgutil", "--expand-full", args.package.resolve(), expanded])
            matches = list(expanded.glob("**/payload/Contents/Resources/game"))
            if len(matches) != 1:
                raise SystemExit(f"Expected one GOG game directory; found {len(matches)}")
            bundle(args.game, matches[0], args.runtime.resolve(), args.output.resolve(), args.sign_identity)


if __name__ == "__main__":
    main()
