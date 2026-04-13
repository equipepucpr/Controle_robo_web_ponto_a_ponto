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

# --- Bootstrap do venv com dependências Python ---
VENV_DIR=".venv"
REQ_FILE="requirements.txt"
REQ_STAMP="$VENV_DIR/.requirements.sha1"

if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "Criando venv em $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

REQ_HASH=$(sha1sum "$REQ_FILE" | awk '{print $1}')
if [ ! -f "$REQ_STAMP" ] || [ "$(cat "$REQ_STAMP" 2>/dev/null)" != "$REQ_HASH" ]; then
    echo "Instalando dependências Python..."
    "$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
    "$VENV_DIR/bin/pip" install -r "$REQ_FILE"
    echo "$REQ_HASH" > "$REQ_STAMP"
fi

source "$VENV_DIR/bin/activate"

echo "Iniciando servidor de controle do robô em http://0.0.0.0:5000"
python3 app.py
