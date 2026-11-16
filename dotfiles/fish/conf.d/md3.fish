# md3-niri: базовая настройка fish
fish_add_path -g $HOME/.local/bin
set -g fish_greeting
alias ll 'ls -lah --color=auto'
alias update 'sudo pacman -Syu'
