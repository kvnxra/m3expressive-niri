#!/usr/bin/env bash
makoctl mode -t do-not-disturb >/dev/null
pkill -RTMIN+11 -x waybar 2>/dev/null || true
