import os

with open("input.txt") as f:
    lines = f.readlines()

for line in lines:
    line = line.strip()
    print(f"processing {line}")
    os.system(f'python3 scripts/import_item_image.py "{line}"')
