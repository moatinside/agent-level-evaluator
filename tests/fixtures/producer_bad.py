#!/usr/bin/env python3
import json, sys
json.load(sys.stdin)
print(json.dumps({"answer": "未確認の断定です。"}, ensure_ascii=False))
