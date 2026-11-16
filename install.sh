#!/usr/bin/env bash
# md3-niri — установщик «с нуля»: Arch Linux / CachyOS → niri + Material 3 Expressive.
#
#   ./install.sh                  интерактивно (на каждый необязательный шаг спросит)
#   ./install.sh --yes            всё по умолчанию, без вопросов (AUR-пакеты собираются без просмотра PKGBUILD)
#   ./install.sh --dotfiles-only  только конфиги и команды md3 (пакеты и систему не трогает)
#   --gaming / --no-gaming        Steam, gamemode, mangohud (включит multilib)
#   --greeter / --no-greeter      greetd + tuigreet вместо тяжёлого менеджера входа
#   --default-binds               стандартные бинды md3-niri, даже если уже есть свои (cfg/keybinds.kdl)
#
# Повторный запуск безопасен: всё, что перезаписывается, копируется в ~/.config/md3/backup-<дата>/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
C="${XDG_CONFIG_HOME:-$HOME/.config}"
BIN="$HOME/.local/bin"
FONTS="$HOME/.local/share/fonts/md3"
STAMP="$(date +%F_%H-%M-%S)"
BK="$C/md3/backup-$STAMP"
mkdir -p "$HOME/.cache/md3"
LOG="$HOME/.cache/md3/install-$STAMP.log"

YES=0
DOTONLY=0
GAMING=ask
GREETER=ask
KEEP_BINDS=1

for arg in "$@"; do
    case $arg in
        --yes|-y) YES=1 ;;
        --dotfiles-only) DOTONLY=1 ;;
        --gaming) GAMING=yes ;;
        --no-gaming) GAMING=no ;;
        --greeter) GREETER=yes ;;
        --no-greeter) GREETER=no ;;
        --default-binds) KEEP_BINDS=0 ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Неизвестный параметр: $arg (см. --help)" >&2; exit 1 ;;
    esac
done

exec > >(tee -a "$LOG") 2>&1

step() { printf '\n\033[1m▌ %s\033[0m\n' "$*"; }
info() { printf '  · %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; }
die()  { printf '  ✗ %s\n' "$*" >&2; exit 1; }

ask() {   # ask "Вопрос?" y|n — возвращает 0, если ответ «да»
    local q=$1 def=${2:-y} ans hint="y/N"
    [[ $def == y ]] && hint="Y/n"
    if (( YES )); then [[ $def == y ]]; return; fi
    read -r -p "  ? $q [$hint] " ans || ans=""
    ans=${ans:-$def}
    [[ $ans =~ ^[YyДд] ]]
}

read_list() { sed -e 's/#.*//' -e 's/[[:space:]]*$//' -e '/^[[:space:]]*$/d' "$1"; }

# ──────────────────────────────────────────────────────────────── проверки
[[ $EUID -ne 0 ]] || die "Запускай от обычного пользователя — sudo спросит пароль сам."

if (( ! DOTONLY )); then
    command -v pacman >/dev/null || die "Нужен Arch Linux или CachyOS (pacman не найден)."
    curl -fsI https://archlinux.org >/dev/null 2>&1 || die "Нет доступа в интернет."
    sudo -v
    # фоновый keep-alive для sudo, чтобы сессия не протухала во время сборки AUR
    while true; do sudo -n true; sleep 50; kill -0 "$$" || exit; done 2>/dev/null &
    SUDO_LOOP_PID=$!
    trap 'kill "$SUDO_LOOP_PID" 2>/dev/null || true' EXIT
fi

IS_CACHY=0
grep -qi cachyos /etc/os-release 2>/dev/null && IS_CACHY=1

# ──────────────────────────────────────────────────────────────── железо
if (( ! DOTONLY )) && ! command -v lspci >/dev/null 2>&1; then
    sudo pacman -S --needed --noconfirm pciutils
fi
GPU=unknown
gpu_info="$(lspci -nn 2>/dev/null | grep -Ei 'vga|3d|display' || true)"
if   grep -Eiq 'amd|radeon|\[ati\]|advanced micro' <<<"$gpu_info"; then GPU=amd
elif grep -Eiq 'nvidia' <<<"$gpu_info"; then GPU=nvidia
elif grep -Eiq 'intel'  <<<"$gpu_info"; then GPU=intel
fi
CPU=unknown
case "$(grep -m1 vendor_id /proc/cpuinfo 2>/dev/null || true)" in
    *AuthenticAMD*) CPU=amd ;;
    *GenuineIntel*) CPU=intel ;;
esac
step "Железо: GPU=$GPU, CPU=$CPU$( ((IS_CACHY)) && echo ', CachyOS' )"

REPO=(); AURP=(); MISSING=(); AUR=""

find_aur() { for h in paru yay; do command -v "$h" >/dev/null 2>&1 && { AUR=$h; return 0; }; done; return 1; }

bootstrap_aur() {
    info "AUR-помощник не найден — собираю yay-bin"
    sudo pacman -S --needed --noconfirm base-devel git
    local tmp; tmp="$(mktemp -d)"
    git clone --depth 1 https://aur.archlinux.org/yay-bin.git "$tmp/yay-bin"
    (cd "$tmp/yay-bin" && makepkg -si --noconfirm)
    rm -rf "$tmp"
    AUR=yay
}

route() {   # раскладывает имена пакетов: официальный репозиторий / AUR / не найден
    local p
    for p in "$@"; do
        if pacman -Si "$p" >/dev/null 2>&1; then REPO+=("$p")
        elif [[ -n $AUR ]] && "$AUR" -Si "$p" >/dev/null 2>&1; then AURP+=("$p")
        else MISSING+=("$p"); fi
    done
}

install_routed() {
    local pacflags=() aurflags=()
    if (( YES )); then
        pacflags=(--noconfirm)
        [[ $AUR == paru ]] && aurflags=(--noconfirm --skipreview)
        [[ $AUR == yay ]]  && aurflags=(--noconfirm --answerdiff None --answerclean None)
    fi
    if (( ${#REPO[@]} )); then
        info "pacman: ${REPO[*]}"
        sudo pacman -S --needed "${pacflags[@]}" "${REPO[@]}"
    fi
    if (( ${#AURP[@]} )); then
        info "AUR ($AUR): ${AURP[*]}"
        "$AUR" -S --needed "${aurflags[@]}" "${AURP[@]}"
    fi
    if (( ${#MISSING[@]} )); then
        warn "не найдены ни в репозиториях, ни в AUR (пропущены): ${MISSING[*]}"
    fi
    REPO=(); AURP=(); MISSING=()
}

enable_multilib() {
    if ! grep -q '^\[multilib\]' /etc/pacman.conf; then
        info "включаю multilib"
        sudo sed -i '/^#\[multilib\]/,/^#Include/ s/^#//' /etc/pacman.conf
        sudo pacman -Syu $( ((YES)) && echo --noconfirm )
    fi
}

# ──────────────────────────────────────────────────────────────── пакеты
if (( ! DOTONLY )); then
    step "Оптимизация pacman и выбор быстрых зеркал"
    sudo sed -i 's/^#ParallelDownloads = .*/ParallelDownloads = 5/' /etc/pacman.conf
    sudo sed -i 's/^#Color/Color\nILoveCandy/' /etc/pacman.conf
    if ! (( IS_CACHY )); then
        if ! command -v reflector >/dev/null 2>&1; then
            sudo pacman -S --needed --noconfirm reflector
        fi
        info "выбираю 10 самых быстрых зеркал..."
        sudo reflector --country Russia,Germany,Netherlands --latest 10 --protocol https --sort rate --save /etc/pacman.d/mirrorlist 2>/dev/null || warn "зеркала не обновились через reflector, использую текущие"
    fi

    step "Обновление системы (Arch не поддерживает частичные обновления)"
    sudo pacman -Syu $( ((YES)) && echo --noconfirm )

    find_aur || bootstrap_aur
    info "AUR-помощник: $AUR"

    step "Пакеты: система, драйверы, окружение, приложения, шрифты"
    DRV=()
    case $GPU in
        amd)    DRV=(mesa vulkan-radeon libva-mesa-driver mesa-vdpau libva-utils vulkan-tools) ;;
        intel)  DRV=(mesa vulkan-intel intel-media-driver libva-utils vulkan-tools) ;;
        nvidia) warn "NVIDIA: драйвер не ставлю автоматически (выбери nvidia-open / nouveau сам)"; DRV=(mesa) ;;
        *)      DRV=(mesa) ;;
    esac
    UCODE=()
    [[ $CPU == amd   ]] && UCODE=(amd-ucode)
    [[ $CPU == intel ]] && UCODE=(intel-ucode)

    route "${DRV[@]}" "${UCODE[@]}"
    for list in base desktop apps fonts extras; do
        mapfile -t pk < <(read_list "$ROOT/packages/$list.txt")
        route "${pk[@]}"
    done
    install_routed

    # ── игры (необязательно)
    if [[ $GAMING == ask ]]; then ask "Поставить Steam + gamemode + mangohud?" n && GAMING=yes || GAMING=no; fi
    if [[ $GAMING == yes ]]; then
        step "Игры"
        enable_multilib
        LIB32=()
        [[ $GPU == amd   ]] && LIB32=(lib32-mesa lib32-vulkan-radeon)
        [[ $GPU == intel ]] && LIB32=(lib32-mesa lib32-vulkan-intel)
        route "${LIB32[@]}"
        mapfile -t pk < <(read_list "$ROOT/packages/gaming.txt")
        route "${pk[@]}"
        install_routed
        getent group gamemode >/dev/null && sudo gpasswd -a "$USER" gamemode >/dev/null || true
    fi
fi

# ──────────────────────────────────────────────────────────────── система
if (( ! DOTONLY )); then
    step "Система: сервисы, zram, драйверы"

    sudo systemctl enable --now NetworkManager.service fstrim.timer paccache.timer 2>/dev/null \
        || warn "не удалось включить часть сервисов (NetworkManager / fstrim / paccache)"
    sudo systemctl --global enable pipewire.socket pipewire-pulse.socket wireplumber.service 2>/dev/null || true

    if (( IS_CACHY )) || pacman -Q cachyos-settings >/dev/null 2>&1; then
        info "CachyOS: zram и sysctl уже настроены cachyos-settings — пропускаю"
    elif pacman -Q zram-generator >/dev/null 2>&1; then
        info "zram (половина ОЗУ, zstd) + sysctl для работы с zram"
        printf '[zram0]\nzram-size = ram / 2\ncompression-algorithm = zstd\nswap-priority = 100\n' \
            | sudo tee /etc/systemd/zram-generator.conf >/dev/null
        printf 'vm.swappiness = 180\nvm.watermark_boost_factor = 0\nvm.watermark_scale_factor = 125\nvm.page-cluster = 0\n' \
            | sudo tee /etc/sysctl.d/99-md3-zram.conf >/dev/null
        sudo systemctl daemon-reload
        sudo systemctl start systemd-zram-setup@zram0.service 2>/dev/null || true
        sudo sysctl --system >/dev/null 2>&1 || true
    fi

    # аппаратное ускорение видео в браузерах / mpv на AMD
    if [[ $GPU == amd ]]; then
        mkdir -p "$C/environment.d"
        printf 'LIBVA_DRIVER_NAME=radeonsi\n' > "$C/environment.d/91-md3-gpu.conf"
        info "VA-API: LIBVA_DRIVER_NAME=radeonsi"
    fi

    # ── менеджер входа (необязательно)
    if [[ $GREETER == ask ]]; then
        has_dm=0
        systemctl is-enabled display-manager.service >/dev/null 2>&1 && has_dm=1
        if (( has_dm )); then ask "Заменить текущий менеджер входа на greetd + tuigreet (лёгкий, текстовый)?" n && GREETER=yes || GREETER=no
        else ask "Поставить greetd + tuigreet, чтобы niri запускался после ввода пароля?" y && GREETER=yes || GREETER=no; fi
    fi
    if [[ $GREETER == yes ]]; then
        route greetd greetd-tuigreet
        install_routed
        sudo mkdir -p /etc/greetd
        printf '[terminal]\nvt = 1\n\n[default_session]\ncommand = "tuigreet --time --asterisks --remember --cmd niri-session"\nuser = "greeter"\n' \
            | sudo tee /etc/greetd/config.toml >/dev/null
        for dm in sddm gdm lightdm ly lxdm; do sudo systemctl disable "$dm.service" >/dev/null 2>&1 || true; done
        sudo systemctl enable greetd.service
        info "greetd включён: после перезагрузки войдёшь в niri"
    fi

    if [[ $(basename "${SHELL:-}") != fish ]] && command -v fish >/dev/null; then
        ask "Сделать fish оболочкой по умолчанию?" y && chsh -s "$(command -v fish)" || true
    fi
fi

# ──────────────────────────────────────────────────────────────── шрифты
step "Шрифты: Google Sans Flex и Material Symbols"
mkdir -p "$FONTS"
download() {   # download <url> <файл> — валидный шрифт, а не страница с ошибкой
    local url=$1 out=$2
    [[ -s $out ]] && (( $(stat -c%s "$out") > 100000 )) && return 0
    curl -fL --retry 3 -o "$out" "$url" 2>/dev/null && (( $(stat -c%s "$out") > 100000 )) || { rm -f "$out"; return 1; }
}
download "https://github.com/google/fonts/raw/main/ofl/googlesansflex/GoogleSansFlex%5BGRAD%2CROND%2Copsz%2Cslnt%2Cwdth%2Cwght%5D.ttf" \
    "$FONTS/GoogleSansFlex.ttf" \
    && info "Google Sans Flex установлен" \
    || warn "Google Sans Flex не скачался: скачай с fonts.google.com/specimen/Google+Sans+Flex и положи .ttf в $FONTS (пока подставится Google Sans)"
download "https://github.com/google/material-design-icons/raw/master/variablefont/MaterialSymbolsRounded%5BFILL%2CGRAD%2Copsz%2Cwght%5D.ttf" \
    "$FONTS/MaterialSymbolsRounded.ttf" \
    && info "Material Symbols Rounded установлен" \
    || warn "Material Symbols не скачался: без него иконки в баре будут словами (wifi, volume_up…). Повтори установку позже."
fc-cache -f "$FONTS" >/dev/null 2>&1 || true

# ──────────────────────────────────────────────────────────────── конфиги
step "Конфиги → $C"
mkdir -p "$BK" "$BIN" "$C/md3/templates" "$HOME/Pictures/Screenshots" "$HOME/Pictures/Wallpapers"
command -v xdg-user-dirs-update >/dev/null && xdg-user-dirs-update 2>/dev/null || true

backup() {   # backup <путь относительно $C>
    local rel=$1
    if [[ -e $C/$rel || -L $C/$rel ]]; then
        mkdir -p "$BK/$(dirname "$rel")"
        cp -a "$C/$rel" "$BK/$rel"
    fi
}

deploy() {   # deploy <путь относительно dotfiles>
    local rel=$1 src="$ROOT/dotfiles/$1" dst="$C/$1"
    mkdir -p "$(dirname "$dst")"
    if [[ -L $dst ]]; then backup "$rel"; rm "$dst"; fi
    if [[ -e $dst ]] && ! cmp -s <(sed "s|@HOME@|$HOME|g" "$src") "$dst"; then backup "$rel"; fi
    sed "s|@HOME@|$HOME|g" "$src" > "$dst"
}

# файлы, которые потом перезапишет matugen, тоже бэкапим и разрываем симлинки
GENERATED=(waybar/colors.css mako/config fuzzel/fuzzel.ini ghostty/themes/current gtk-3.0/gtk.css gtk-4.0/gtk.css
           qt6ct/style-colors.conf qt5ct/colors/md3.conf swaylock/config btop/themes/md3.theme zathura/md3colors niri/md3-colors.kdl)
for rel in "${GENERATED[@]}"; do
    # свои же сгенерированные файлы не бэкапим — только то, что пришло из другого места
    grep -qs 'generated by md3' "$C/$rel" || backup "$rel"
    mkdir -p "$C/$(dirname "$rel")"
    [[ -L $C/$rel ]] && rm "$C/$rel"
done

# бинды: если осталась прежняя настройка niri (cfg/keybinds.kdl), используем её, а не стандартные
OLD_BINDS=()
if (( KEEP_BINDS )) && [[ -f $C/niri/cfg/keybinds.kdl ]]; then
    for f in keybinds shell-binds md3-binds; do [[ -f $C/niri/cfg/$f.kdl ]] && OLD_BINDS+=("cfg/$f.kdl"); done
fi

while IFS= read -r rel; do
    [[ $rel == niri/binds.kdl ]] && (( ${#OLD_BINDS[@]} )) && continue
    deploy "$rel"
done < <(cd "$ROOT/dotfiles" && find . -type f | sed 's|^\./||' | sort)
chmod +x "$C"/waybar/scripts/*.sh

if (( ${#OLD_BINDS[@]} )); then
    grep -qs 'md3: твои прежние бинды' "$C/niri/binds.kdl" || backup niri/binds.kdl
    {
        echo "// md3: твои прежние бинды — md3 их не меняет. Стандартные бинды: ./install.sh --default-binds"
        for f in "${OLD_BINDS[@]}"; do echo "include \"$f\""; done
    } > "$C/niri/binds.kdl"
    info "бинды: оставлены прежние (${OLD_BINDS[*]})"
fi

cp "$ROOT"/templates/* "$C/md3/templates/"
sed -i "s|@ICON_SEARCH@|$(printf '\xee\xa2\xb6')|" "$C/md3/templates/fuzzel.ini"   # Material Symbols: search
cp "$ROOT/matugen.toml" "$C/md3/matugen.toml"
install -m755 "$ROOT"/bin/* "$BIN/"
info "команды: md3 · md3-menu · md3-session · md3-clip · md3-zen · md3-player → $BIN"

# ──────────────────────────────────────────────────────────────── цвета
step "Палитра Material You → все приложения"
if command -v matugen >/dev/null; then
    "$BIN/md3" apply
else
    warn "matugen не установлен — палитра не сгенерирована. Поставь matugen и выполни:  md3 apply"
fi

# Zen: профиль появляется после первого запуска браузера
"$BIN/md3-zen" 2>&1 | sed 's/^/  · /' || true

# ──────────────────────────────────────────────────────────────── проверка niri
step "Проверка конфигурации niri"
if command -v niri >/dev/null; then
    if niri validate >/dev/null 2>&1; then info "niri validate: конфиг корректен"
    else warn "niri validate нашёл ошибки — посмотри:  niri validate"; fi
else
    warn "niri не найден (ставь без --dotfiles-only)"
fi

rmdir "$BK" 2>/dev/null || true

# перезапуск плеера на новой версии
pkill -f 'md3-player\.py' 2>/dev/null || true
sleep 0.3
rm -f "${XDG_RUNTIME_DIR:-/tmp}/md3-player.pid"
[[ -n ${WAYLAND_DISPLAY:-} ]] && "$BIN/md3-player" --daemon || true

cat <<EOF

  ✓ Готово.$( [[ -d $BK ]] && echo "  Бэкап прежних файлов: $BK  ·" ) лог: $LOG

  Дальше:
    1. Перезагрузись и выбери сессию niri (или, если включён greetd, просто войди).
    2. Открой Zen Browser один раз, закрой и выполни:  md3-zen
    3. Цвета: Mod+Shift+T (или  md3 color "#6750A4",  md3 image ~/Pictures/Wallpapers/…)
    4. Все горячие клавиши: Mod+Shift+/
    5. В BIOS включи XMP/DOCP (Vega 8 очень зависит от скорости ОЗУ) и выдели iGPU 2 ГБ.
EOF
