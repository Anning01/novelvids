#!/bin/sh
set -eu

nginx -t >/dev/null 2>&1
systemctl reload nginx
