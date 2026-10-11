#!/usr/bin/env python3
"""Render pytest JUnit XML as a GitHub step summary grouped by control layer."""
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

path = sys.argv[1] if len(sys.argv) > 1 else "build/junit.xml"
if not os.path.exists(path):
    sys.exit(0)
layers = defaultdict(lambda: [0, 0, []])
for case in ET.parse(path).getroot().iter("testcase"):
    layer = case.get("classname", "").split(".")[-1]
    failure = case.find("failure") if case.find("failure") is not None else case.find("error")
    layers[layer][0] += 1
    if failure is not None:
        layers[layer][1] += 1
        msg = (failure.get("message") or "").splitlines()[0][:300].replace("|", "\\|")
        layers[layer][2].append(f"`{case.get('name')}` — {msg}")
lines = ["### Layered data tests", "", "| Layer | Passed | Failed |", "|---|---|---|"]
for layer, (total, failed, _) in sorted(layers.items()):
    lines.append(f"| {layer} | {total - failed} | {'**' + str(failed) + '**' if failed else 0} |")
for layer, (_, _, fails) in sorted(layers.items()):
    for f in fails:
        lines.append(f"- **{layer}**: {f}")
text = "\n".join(lines) + "\n"
print(text)
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
        fh.write(text)
