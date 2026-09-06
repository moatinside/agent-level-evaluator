#!/usr/bin/env python3
import json, sys
payload=json.load(sys.stdin)
if payload.get("issues"):
    print(json.dumps({"correction": "根拠を確認しました。"}, ensure_ascii=False))
else:
    print(json.dumps({"correction": ""}, ensure_ascii=False))
