#!/bin/sh
# Compile the library to .mpy for CircuitPython 10.3.1. Needs the matching mpy-cross
# (download from https://adafruit-circuit-python.s3.amazonaws.com/index.html?prefix=bin/mpy-cross/ ).
# Result: build/lib/boswv12 - copy that folder to /lib on the board.
set -e
OUT=build/lib/boswv12
rm -rf build
mkdir -p "$OUT/www"
for f in lib/boswv12/*.py; do
  mpy-cross "$f" -o "$OUT/$(basename "$f" .py).mpy"
done
cp lib/boswv12/www/* "$OUT/www/"
echo "done: $OUT"