"""Reject foreign-architecture native binaries and non-16 KB ELF segments."""

import argparse
import io
import struct
import tarfile
import zipfile


def check_elf(data, name):
    if data[:4] != b"\x7fELF":
        return 0
    if len(data) < 64:
        raise ValueError(f"{name}: truncated ELF header")
    if data[4:6] != b"\x02\x01" or struct.unpack_from("<H", data, 18)[0] != 183:
        raise ValueError(f"{name}: native binary is not little-endian arm64 ELF")
    elf_type = struct.unpack_from("<H", data, 16)[0]
    if elf_type == 1:
        # Relocatable objects in lxml's header/development data have no LOAD
        # segments. Their architecture was checked above; Android never loads
        # them as a shared library or executable.
        return 0
    if elf_type not in (2, 3):
        raise ValueError(f"{name}: unsupported ELF object type {elf_type}")
    offset = struct.unpack_from("<Q", data, 32)[0]
    entry_size, count = struct.unpack_from("<HH", data, 54)
    if not count or entry_size < 56 or offset + entry_size * count > len(data):
        raise ValueError(f"{name}: malformed ELF program headers")
    loads = 0
    for index in range(count):
        header = offset + index * entry_size
        if struct.unpack_from("<I", data, header)[0] == 1:
            loads += 1
            alignment = struct.unpack_from("<Q", data, header + 48)[0]
            if alignment < 16384 or alignment & (alignment - 1):
                raise ValueError(f"{name}: LOAD alignment {alignment} is below 16 KB or invalid")
    if not loads:
        raise ValueError(f"{name}: no ELF LOAD segments")
    return 1


def scan(data, name, depth=0):
    count = check_elf(data, name)
    if count or depth >= 3:
        return count
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for entry in archive.infolist():
                if not entry.is_dir():
                    count += scan(archive.read(entry), name + "/" + entry.filename, depth + 1)
    elif name.endswith((".tar", ".tar.gz", ".tgz")) or data[:2] == b"\x1f\x8b":
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
                for entry in archive:
                    if entry.isfile():
                        count += scan(archive.extractfile(entry).read(), name + "/" + entry.name, depth + 1)
        except tarfile.ReadError:
            pass
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact")
    args = parser.parse_args()
    with open(args.artifact, "rb") as artifact:
        count = scan(artifact.read(), args.artifact)
    if not count:
        raise SystemExit("No arm64 native binaries were found")
    print(f"Verified {count} arm64 ELF binaries with 16 KB LOAD alignment")


if __name__ == "__main__":
    main()
