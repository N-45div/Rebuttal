import sys, pathlib
print(pathlib.Path(__file__).with_name("manifest.json").read_text())
