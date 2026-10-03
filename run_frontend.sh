#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m http.server 5500 --directory frontend
