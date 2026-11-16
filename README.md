# md3-niri — Material 3 Expressive для niri

Установка «с нуля» на Arch Linux / CachyOS: niri, Waybar, mako, fuzzel, ghostty, Nautilus и остальное — всё в одной палитре,
которая меняется одной командой. Рассчитано на Ryzen 3 3200G / Vega 8 / 16 ГБ: без blur и теней, короткие анимации.

    ./install.sh               # интерактивно
    ./install.sh --yes         # всё по умолчанию
    ./install.sh --dotfiles-only   # только конфиги и команды md3 (на уже настроенной системе)

## Что ставится
| Что | Пакеты |
|---|---|
| Драйверы (по железу) | mesa, vulkan-radeon, libva (VA-API), amd-ucode / intel-ucode, linux-firmware |
| Окружение | niri, xwayland-satellite, waybar, mako, fuzzel, swaylock, swayidle, awww, matugen, ghostty, порталы |
| Приложения | nautilus, file-roller, loupe, gnome-text-editor, gnome-calculator, zathura, mpv, btop, fastfetch, Zen Browser |
| Шрифты | Google Sans, Google Sans Flex, Material Symbols, JetBrainsMono Nerd, Noto |
| Система | zram, fstrim, NetworkManager, Bluetooth, PipeWire, (по желанию) greetd, Steam + gamemode |

Списки лежат в `packages/*.txt` — убирай и добавляй строки. Каждый пакет автоматически ищется в репозиториях, затем в AUR.

## Цвет
    md3 color "#6750A4"        # любой seed-цвет; обои перерисуются в этой палитре
    md3 image ~/Pictures/Wallpapers/x.png
    md3 mode dark|light|amoled
    md3 scheme expressive      # tonal-spot (по умолчанию), content, fidelity, fruit-salad, rainbow, neutral, monochrome
    md3-menu                   # то же через меню (Mod+Shift+T)

Перекрашиваются: niri (обводка активного окна), Waybar, mako, fuzzel, ghostty, GTK3/4, Qt5/6, swaylock, btop, zathura, Zen, мини-плеер.

## Клавиши (полный список: Mod+Shift+/)
`Mod+Return` терминал · `Mod+D` запуск · `Mod+E` файлы · `Mod+B` браузер · `Mod+P` плеер · `Mod+Shift+V` буфер обмена ·
`Mod+Shift+T` цвета и обои · `Mod+Shift+E` сеанс · `Mod+Alt+L` блокировка · `Mod+O` обзор · `Mod+Q` закрыть ·
`Mod+Space` раскладка (us/ru; также Alt+Shift) · `Print` скриншот

## Железо (ручные шаги в BIOS)
* Включи **XMP/DOCP**: у Vega 8 нет своей памяти, скорость ОЗУ напрямую определяет скорость графики (2667 → 3200 МГц заметно).
* Память в **двухканале**, UMA Frame Buffer — 2 ГБ.

## Файлы
`~/.config/md3/` — шаблоны и конфиг matugen, `~/.config/md3/backup-*` — прежние версии затронутых файлов.
Мини-плеер: `md3-player` (фоновый процесс, клик по чипу в баре), лог `~/.cache/md3/player.log`.
Zen: после первого запуска браузера выполни `md3-zen`.
