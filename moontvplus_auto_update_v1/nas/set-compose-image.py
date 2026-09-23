#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 4:
    raise SystemExit("usage: set-compose-image.py COMPOSE_FILE SERVICE IMAGE")

path = Path(sys.argv[1])
service = sys.argv[2]
image = sys.argv[3]

lines = path.read_text(encoding="utf-8").splitlines(True)

services_i = None
service_i = None
service_indent = None
image_i = None

for i, line in enumerate(lines):
    stripped = line.strip()
    indent = len(line) - len(line.lstrip(" "))
    if stripped == "services:":
        services_i = i
        continue
    if services_i is not None and stripped == f"{service}:":
        service_i = i
        service_indent = indent
        continue
    if service_i is not None and i > service_i:
        if stripped and indent <= service_indent:
            break
        if stripped.startswith("image:"):
            image_i = i
            break

if service_i is None:
    raise SystemExit(f"service not found: {service}")
if image_i is None:
    raise SystemExit(f"image line not found under service: {service}")

prefix = lines[image_i][:len(lines[image_i]) - len(lines[image_i].lstrip(" "))]
lines[image_i] = f"{prefix}image: {image}\n"
path.write_text("".join(lines), encoding="utf-8")
print(f"updated {service} image -> {image}")
