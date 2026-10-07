"""Collect unstripped arm64 libraries matching the bundle's ELF build IDs."""

import argparse
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path


def read_elf(tool, option, path):
    return subprocess.check_output([tool, option, str(path)], text=True, errors="replace")


def build_id(tool, path):
    match = re.search(r"Build ID:\s*([a-fA-F0-9]+)", read_elf(tool, "-n", path))
    return match.group(1) if match else None


def matches_symbols(tool, path, expected_id):
    try:
        with path.open("rb") as candidate:
            if candidate.read(4) != b"\x7fELF":
                return False
        return bool(expected_id and build_id(tool, path) == expected_id
                    and ".symtab" in read_elf(tool, "-S", path))
    except (OSError, subprocess.CalledProcessError):
        return False


def collect(bundle, build_dir, output, tool):
    target = Path(output) / "arm64-v8a"
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.TemporaryDirectory() as temporary, zipfile.ZipFile(bundle) as archive:
        for name in archive.namelist():
            if not name.startswith("base/lib/arm64-v8a/") or not name.endswith(".so"):
                continue
            data = archive.read(name)
            if not data.startswith(b"\x7fELF"):
                continue
            packaged = Path(temporary) / Path(name).name
            packaged.write_bytes(data)
            selected = packaged
            if ".symtab" not in read_elf(tool, "-S", packaged):
                expected_id = build_id(tool, packaged)
                candidates = sorted(path for path in Path(build_dir).rglob(packaged.name)
                                    if "arm64-v8a" in str(path))
                selected = next((path for path in candidates
                                 if matches_symbols(tool, path, expected_id)), None)
                if selected is None:
                    raise ValueError(f"No matching unstripped library for {packaged.name}")
            (target / packaged.name).write_bytes(selected.read_bytes())
            count += 1
    if not count:
        raise ValueError("Bundle has no native ELF libraries")
    print(f"Collected {count} verified native symbol files")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    parser.add_argument("build_dir")
    parser.add_argument("output")
    parser.add_argument("--readelf", required=True)
    args = parser.parse_args()
    collect(args.bundle, args.build_dir, args.output, args.readelf)


if __name__ == "__main__":
    main()
