#!/bin/bash
# Inicia o servidor web de controle do robô com ambiente ROS2 configurado.
# Uso: ./start.sh
#
# Pré-requisito: workspace ROS2 compilado com wheel_msgs e ros2-hoverboard-driver.
#   cd ~/ros2_ws && colcon build --packages-select ros2-hoverboard-driver wheel_msgs

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROS2_SETUP="$HOME/ros2_ws/install/setup.bash"

if [ ! -f "$ROS2_SETUP" ]; then
    echo "ERRO: $ROS2_SETUP não encontrado."
    echo "Execute: cd ~/ros2_ws && colcon build --packages-select ros2-hoverboard-driver wheel_msgs"
    exit 1
fi

source "$ROS2_SETUP"

cd "$SCRIPT_DIR/controle_web"

# Ativa o venv se existir
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

echo "Iniciando servidor de controle do robô em http://0.0.0.0:5000"
python3 app.py
