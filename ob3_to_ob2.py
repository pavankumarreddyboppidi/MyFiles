#!/usr/bin/env python3
"""
Convert a baked Open Badges 3.0 PNG into Open Badges 2.0 artifacts.

Outputs (in --out):
  assertion.json   OB 2.0 Assertion  (HostedBadge verification)
  badgeclass.json  OB 2.0 BadgeClass
  issuer.json      OB 2.0 Issuer
  badge-ob2.png    same pixels, OB 2.0 assertion baked in (iTXt "openbadges")

Usage:
  python3 ob3_to_ob2.py input.png --base https://yourdomain.com/badges/conf42 --out ./ob2
  python3 ob3_to_ob2.py input.png --base ... --email you@example.com   # email recipient (hashed)

--base is the public folder where you will upload the four output files.
The assertion "id" MUST resolve to assertion.json for HostedBadge verification.
"""
import argparse, hashlib, json, os, secrets, struct, zlib

CTX2 = "https://w3id.org/openbadges/v2"


def read_chunks(data):
    pos = 8
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        yield ctype, body
        pos += 12 + length


def make_chunk(ctype, body):
    crc = zlib.crc32(ctype + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", crc)


def extract_ob3(data):
    for ctype, body in read_chunks(data):
        if ctype == b"iTXt":
            kw, rest = body.split(b"\x00", 1)
            if kw.decode("latin1").lower() in ("openbadge", "openbadges", "openbadgecredential"):
                comp, _meth = rest[0], rest[1]
                rest = rest[2:]
                _lang, rest = rest.split(b"\x00", 1)
                _tkw, text = rest.split(b"\x00", 1)
                if comp:
                    text = zlib.decompress(text)
                return json.loads(text.decode("utf8"))
    raise SystemExit("No baked Open Badges data found in PNG")


def as_url(x):
    return x.get("id") if isinstance(x, dict) else x


def convert(ob3, base, email=None):
    base = base.rstrip("/")
    subj = ob3["credentialSubject"]
    ach = subj["achievement"]
    issuer3 = ob3["issuer"]

    issuer = {
        "@context": CTX2,
        "type": "Issuer",
        "id": f"{base}/issuer.json",
        "name": issuer3["name"],
        "url": issuer3["url"],
    }
    if issuer3.get("description"):
        issuer["description"] = issuer3["description"]
    if issuer3.get("image"):
        issuer["image"] = as_url(issuer3["image"])

    badge = {
        "@context": CTX2,
        "type": "BadgeClass",
        "id": f"{base}/badgeclass.json",
        "name": ach["name"],
        "description": ach.get("description", ach["name"]),
        "image": as_url(ach["image"]),
        "criteria": {"narrative": ach["criteria"]["narrative"]},
        "issuer": issuer["id"],
    }

    if email:
        salt = secrets.token_hex(8)
        ident = "sha256$" + hashlib.sha256((email + salt).encode()).hexdigest()
        recipient = {"type": "email", "hashed": True, "salt": salt, "identity": ident}
    else:
        recipient = {"type": "url", "hashed": False, "identity": subj["id"]}

    original_page = ach["id"].split("#")[0]
    assertion = {
        "@context": CTX2,
        "type": "Assertion",
        "id": f"{base}/assertion.json",
        "recipient": recipient,
        "badge": badge["id"],
        "issuedOn": ob3["validFrom"],
        "verification": {"type": "HostedBadge"},
        "image": f"{base}/badge-ob2.png",
        "evidence": [{
            "id": original_page,
            "narrative": "Original Open Badges 3.0 credential issued by conf42.com via certified.fyi.",
        }],
    }
    return assertion, badge, issuer


def bake(png_bytes, assertion):
    out = [png_bytes[:8]]
    payload = json.dumps(assertion, separators=(",", ":")).encode("utf8")
    itxt = b"openbadges\x00" + b"\x00\x00" + b"\x00" + b"\x00" + payload  # kw, flags, lang, tkw, text
    inserted = False
    for ctype, body in read_chunks(png_bytes):
        if ctype == b"iTXt" and body.split(b"\x00", 1)[0].decode("latin1").lower().startswith("openbadge"):
            continue  # drop the OB 3.0 chunk
        if ctype == b"IEND" and not inserted:
            out.append(make_chunk(b"iTXt", itxt))
            inserted = True
        out.append(make_chunk(ctype, body))
    return b"".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("png")
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", default="./ob2")
    ap.add_argument("--email")
    a = ap.parse_args()

    raw = open(a.png, "rb").read()
    ob3 = extract_ob3(raw)
    assertion, badge, issuer = convert(ob3, a.base, a.email)

    os.makedirs(a.out, exist_ok=True)
    for name, obj in (("assertion", assertion), ("badgeclass", badge), ("issuer", issuer)):
        with open(os.path.join(a.out, f"{name}.json"), "w") as f:
            json.dump(obj, f, indent=2)
    with open(os.path.join(a.out, "badge-ob2.png"), "wb") as f:
        f.write(bake(raw, assertion))
    print("Wrote:", ", ".join(sorted(os.listdir(a.out))))


if __name__ == "__main__":
    main()
