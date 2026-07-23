#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
# Exclude the generated/placeholder endpoint definition; tests link test/fake_endpoints.c instead.
SRC=$(ls src/*.c | grep -v 'odrive_endpoints_0_6.c')
gcc -std=c99 -Wall -Wextra -Iinclude $SRC test/*.c -o test/smoke -lm
./test/smoke
