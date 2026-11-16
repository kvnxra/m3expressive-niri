#!/usr/bin/env bash
# Состояние «Не беспокоить» для waybar (mako)
if makoctl mode 2>/dev/null | grep -qx 'do-not-disturb'; then
    printf '{"text":"","alt":"on","class":"on","tooltip":"Не беспокоить: включено"}\n'
else
    printf '{"text":"","alt":"off","class":"off","tooltip":"Не беспокоить: выключено"}\n'
fi
