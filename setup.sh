#!/bin/bash
# Setup do fork ponto-a-ponto: instala deps, clona Livox SDK2 + livox_ros_driver2
# + FAST-LIO2, linka o pacote robot_nav deste repo e compila tudo no workspace.
#
# Pré-requisitos: Ubuntu 24.04 com ROS2 Jazzy já instalado
# (https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html).
#
# Uso:
#   cd ~/Controle_robo_web_ponto_a_ponto
#   ./setup.sh
#
# Para hardware real (hoverboard via USB), rode depois: sudo ./setup_udev.sh

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
WS_DIR="${ROS2_WS:-$HOME/ros2_ws}"
SDK_DIR="${LIVOX_SDK_DIR:-$HOME/Livox-SDK2}"

echo "=== [1/5] Instalando dependências apt ==="
sudo apt update
sudo apt install -y \
    git build-essential cmake \
    python3-venv python3-pip \
    libpcl-dev libeigen3-dev \
    ros-jazzy-xacro ros-jazzy-robot-state-publisher \
    ros-jazzy-pcl-conversions ros-jazzy-pcl-ros \
    ros-jazzy-tf2 ros-jazzy-tf2-ros ros-jazzy-tf2-geometry-msgs

echo
echo "=== [2/5] Livox-SDK2 (dep nativa do livox_ros_driver2) ==="
if [ ! -d "$SDK_DIR" ]; then
    git clone https://github.com/Livox-SDK/Livox-SDK2.git "$SDK_DIR"
fi
cd "$SDK_DIR"
mkdir -p build && cd build
cmake ..
make -j"$(nproc)"
sudo make install
sudo ldconfig

echo
echo "=== [3/5] Preparando workspace em $WS_DIR ==="
mkdir -p "$WS_DIR/src"
cd "$WS_DIR/src"

link_if_missing() {
    local name="$1" target="$2"
    if [ -e "$name" ]; then
        echo "  $name já presente, pulando"
    else
        ln -s "$target" "$name"
        echo "  symlink $name -> $target"
    fi
}

clone_if_missing() {
    local dir="$1" url="$2" branch="$3"
    if [ -d "$dir" ]; then
        echo "  $dir já clonado, pulando"
    else
        if [ -n "$branch" ]; then
            git clone -b "$branch" "$url" "$dir"
        else
            git clone "$url" "$dir"
        fi
    fi
}

link_if_missing robot_nav "$REPO_DIR/ros2_packages/robot_nav"
clone_if_missing wheel_msgs             https://github.com/Richard-Haes-Ellis/wheel_msgs.git
# livox_ros_driver2 — branch ROS2 (master já é ROS2 no repo oficial)
clone_if_missing livox_ros_driver2      https://github.com/Livox-SDK/livox_ros_driver2.git
# FAST-LIO (hku-mars) — branch ROS2 (também é master na maioria das revisões)
clone_if_missing FAST_LIO                https://github.com/hku-mars/FAST_LIO.git

# Descomente para hardware real:
# clone_if_missing ros2-hoverboard-driver https://github.com/victorfdezc/ros2-hoverboard-driver.git

echo
echo "=== [4/5] Compilando com colcon ==="
cd "$WS_DIR"
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install

BASHRC_LINE="source $WS_DIR/install/setup.bash"
if ! grep -qxF "$BASHRC_LINE" "$HOME/.bashrc"; then
    echo "$BASHRC_LINE" >> "$HOME/.bashrc"
    echo "  adicionado ao ~/.bashrc: $BASHRC_LINE"
fi

echo
echo "=== [5/5] Venv Python do controle_web ==="
cd "$REPO_DIR/controle_web"
if [ ! -f ".venv/bin/activate" ]; then
    python3 -m venv .venv
fi
./.venv/bin/pip install --upgrade pip >/dev/null
./.venv/bin/pip install -r requirements.txt

echo
echo "=== Pronto! ==="
echo "1) Configure a placa de rede local para falar com o Mid-360:"
echo "   IP host padrão do driver: 192.168.1.5/24"
echo "   IP do Mid-360 (padrão de fábrica): 192.168.1.12x"
echo "   Se for outro IP, edite: $REPO_DIR/ros2_packages/robot_nav/config/mid360_config.json"
echo
echo "2) Abra um terminal novo (ou: source $WS_DIR/install/setup.bash) e teste:"
echo "   cd $REPO_DIR && ./launch.sh"
