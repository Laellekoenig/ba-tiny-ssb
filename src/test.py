import pure25519
import ssb_util

keys, _ = pure25519.create_keypair()
sk = keys.sk_s[:32]
vk = keys.vk_s

ssk = ssb_util.to_hex(sk)
assert sk == ssb_util.from_hex(ssk)

msg = b"test"
sig = pure25519.SigningKey(sk).sign(msg)

try:
    pure25519.VerifyingKey(vk).verify(sig, msg)
    print("tada")
except:
    print("oh no")

