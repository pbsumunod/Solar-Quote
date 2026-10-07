"""Generate an RSA signing key locally; print only its public configuration."""

import argparse
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", help="Private PEM file outside the repository")
    args = parser.parse_args()
    path = Path(args.output)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    # Exclusive create prevents overwriting an existing signing identity.
    with path.open("xb") as output:
        output.write(key.private_bytes(serialization.Encoding.PEM,
                                      serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    path.chmod(0o600)
    print("PUBLIC_KEY_MODULUS_HEX =", repr(format(key.public_key().public_numbers().n, "x")))
    print("PUBLIC_KEY_EXPONENT = 65537")


if __name__ == "__main__":
    main()
