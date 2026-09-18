"""Generate a VAPID key pair for Home Manager push notifications.

Run locally and copy the printed values to Fly.io Secrets. Do not commit or
share the private key.
"""

import base64

from cryptography.hazmat.primitives.asymmetric import ec


def base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


key = ec.generate_private_key(ec.SECP256R1())
private_number = key.private_numbers().private_value
public_numbers = key.public_key().public_numbers()

private_key = private_number.to_bytes(32, "big")
public_key = (
    b"\x04"
    + public_numbers.x.to_bytes(32, "big")
    + public_numbers.y.to_bytes(32, "big")
)

print("VAPID_PUBLIC_KEY=" + base64url(public_key))
print("VAPID_PRIVATE_KEY=" + base64url(private_key))
