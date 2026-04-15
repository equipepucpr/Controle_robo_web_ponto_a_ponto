#!/bin/bash
# Setup automatizado para rodar o projeto no modo --sim (Gazebo).
# Segue os passos 2 e 4 do README ("Guia rápido — do zero ao click-to-go").
#
# Pré-requisitos: Ubuntu 24.04 com ROS2 Jazzy já instalado
# (https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html).
#
# Uso:
#   cd ~/Controle_robo_web
#   ./setup.sh
#
# Para hardware real, rode depois: sudo ./setup_udev.sh

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
WS_DIR="${ROS2_WS:-$HOME/ros2_ws}"

echo "=== [1/4] Instalando dependências apt ==="
sudo apt update
sudo apt install -y \
    git python3-venv python3-pip \
    ros-jazzy-xacro ros-jazzy-robot-state-publisher \
    ros-jazzy-slam-toolbox \
    ros-jazzy-nav2-bringup ros-jazzy-nav2-collision-monitor \
    ros-jazzy-nav2-map-server ros-jazzy-nav2-amcl \
    ros-jazzy-ros-gz ros-jazzy-ros-gz-sim \
    ros-jazzy-ros-gz-bridge ros-jazzy-ros-gz-interfaces

echo
echo "=== [2/4] Preparando workspace em $WS_DIR ==="
mkdir -p "$WS_DIR/src"
cd "$WS_DIR/src"

if [ ! -e robot_nav ]; then
    ln -s "$REPO_DIR/ros2_packages/robot_nav" robot_nav
    echo "  symlink robot_nav -> $REPO_DIR/ros2_packages/robot_nav"
else
    echo "  robot_nav já presente, pulando"
fi

echo
echo "=== [3/4] Clonando pacotes externos ==="
clone_if_missing() {
    local dir="$1" url="$2"
    if [ -d "$dir" ]; then
        echo "  $dir já clonado, pulando"
    else
        git clone "$url" "$dir"
    fi
}

clone_if_missing wheel_msgs             https://github.com/Richard-Haes-Ellis/wheel_msgs.git
# Descomente as duas linhas abaixo se for usar o hardware real:
# clone_if_missing ros2-hoverboard-driver https://github.com/victorfdezc/ros2-hoverboard-driver.git
# clone_if_missing ldlidar_stl_ros2       https://github.com/ldrobotSensorTeam/ldlidar_stl_ros2.git

echo
echo "=== [4/4] Compilando com colcon ==="
cd "$WS_DIR"
source /opt/ros/jazzy/setup.bash
colcon build

BASHRC_LINE="source $WS_DIR/install/setup.bash"
if ! grep -qxF "$BASHRC_LINE" "$HOME/.bashrc"; then
    echo "$BASHRC_LINE" >> "$HOME/.bashrc"
    echo "  adicionado ao ~/.bashrc: $BASHRC_LINE"
fi

echo
echo "=== Pronto! ==="
echo "Abra um terminal novo (ou rode: source $WS_DIR/install/setup.bash)"
echo "e teste com:"
echo "  cd $REPO_DIR && ./launch.sh --sim"
