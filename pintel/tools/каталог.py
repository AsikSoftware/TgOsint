# -*- coding: utf-8 -*-
"""Ссылка на прошивку по модели и версии: api.ipsw.me → URL на CDN Apple."""
import json, subprocess, sys

model, want = sys.argv[1], sys.argv[2]
raw = subprocess.run(["curl", "-sS", f"https://api.ipsw.me/v4/device/{model}?type=ipsw"],
                     capture_output=True, timeout=60).stdout
d = json.loads(raw)
подходят = [x for x in d["firmwares"] if x["version"] == want or x["version"].startswith(want + ".")]
if not подходят:
    подходят = [x for x in d["firmwares"] if x["version"].startswith(want)]
if not подходят:
    есть = sorted({x["version"] for x in d["firmwares"]}, reverse=True)[:12]
    print("НЕТ:" + ",".join(есть)); raise SystemExit(1)
x = sorted(подходят, key=lambda y: y["version"])[-1]          # самая свежая в этой линейке
print(f"{x['version']}\t{x['buildid']}\t{round(x['filesize']/1e9, 2)}\t{x['url']}")
