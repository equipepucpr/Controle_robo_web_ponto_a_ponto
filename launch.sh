#!/bin/bash
# Launcher único do fork ponto-a-ponto.
# Sobe: hoverboard driver + Livox Mid-360 + FAST-LIO2 + recorder + follower + web.
# Ctrl+C encerra todos.
#
# Uso:
#   ./launch.sh                     # tudo
#   ./launch.sh --no-hoverboard     # sem a base física (teste da stack lógica)
#   ./launch.sh --no-lidar          # sem Mid-360/FAST-LIO2 (teste da web sem pose)

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROS2_SETUP="$HOME/ros2_ws/install/setup.bash"

NO_HOVERBOARD=false
NO_LIDAR=false

for arg in "$@"; do
    case $arg in
        --no-hoverboard) NO_HOVERBOARD=true ;;
        --no-lidar)      NO_LIDAR=true ;;
        -h|--help)
            sed -n '2,10p' "$0"
            exit 0
            ;;
        *) echo "Flag desconhecida: $arg"; exit 1 ;;
    esac
done

if [ ! -f "$ROS2_SETUP" ]; then
    echo "ERRO: $ROS2_SETUP não encontrado."
    echo "Execute: cd ~/ros2_ws && colcon build"
    exit 1
fi

source "$ROS2_SETUP"

# --- Bootstrap do venv Python ---
VENV_DIR="$SCRIPT_DIR/controle_web/.venv"
REQ_FILE="$SCRIPT_DIR/controle_web/requirements.txt"
REQ_STAMP="$VENV_DIR/.requirements.sha1"

if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "Criando venv em $VENV_DIR..."
    python3 -m venv "$VENV_DIR" || {
        echo "ERRO: falha ao criar venv. Instale: sudo apt install python3-venv"
        exit 1
    }
fi

REQ_HASH=$(sha1sum "$REQ_FILE" | awk '{print $1}')
if [ ! -f "$REQ_STAMP" ] || [ "$(cat "$REQ_STAMP" 2>/dev/null)" != "$REQ_HASH" ]; then
    echo "Instalando dependências Python ($REQ_FILE)..."
    "$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
    "$VENV_DIR/bin/pip" install -r "$REQ_FILE" || {
        echo "ERRO: falha ao instalar dependências."
        exit 1
    }
    echo "$REQ_HASH" > "$REQ_STAMP"
fi

# --- Limpa órfãos de execuções anteriores ---
pkill -9 -f "robot_nav/odom_publisher"        2>/dev/null
pkill -9 -f "robot_nav/cmd_vel_to_wheels"     2>/dev/null
pkill -9 -f "robot_nav/waypoint_recorder"     2>/dev/null
pkill -9 -f "robot_nav/waypoint_follower"     2>/dev/null
pkill -9 -f "robot_state_publisher"           2>/dev/null
pkill -9 -f "livox_ros_driver2_node"          2>/dev/null
pkill -9 -f "fastlio_mapping"                 2>/dev/null
pkill -9 -f "ros2-hoverboard-driver/main"     2>/dev/null

# --- Libera porta 5000 se já estiver em uso ---
PORT_PID=$(ss -tlnp 2>/dev/null | awk '/:5000 /{match($0,/pid=([0-9]+)/,a); if(a[1]) print a[1]}')
if [ -n "$PORT_PID" ]; then
    echo "Porta 5000 em uso pelo PID $PORT_PID — encerrando antes de subir..."
    kill -9 "$PORT_PID" 2>/dev/null
    sleep 1
fi

DRIVER_PID=""
PLAY_PID=""
SERVER_PID=""

kill_tree() {
    local pid="$1"
    [ -z "$pid" ] && return
    local children
    children=$(pgrep -P "$pid" 2>/dev/null)
    for c in $children; do
        kill_tree "$c"
    done
    kill "$pid" 2>/dev/null
}

cleanup() {
    trap '' EXIT INT TERM
    echo ""
    echo "Encerrando todos os processos..."
    kill_tree "$SERVER_PID"
    kill_tree "$PLAY_PID"
    kill_tree "$DRIVER_PID"
    sleep 1
    for pid in $SERVER_PID $PLAY_PID $DRIVER_PID; do
        for desc in $(pgrep -P "$pid" 2>/dev/null) $pid; do
            kill -9 "$desc" 2>/dev/null
        done
    done
    pkill -9 -f "robot_nav/odom_publisher"        2>/dev/null
    pkill -9 -f "robot_nav/cmd_vel_to_wheels"     2>/dev/null
    pkill -9 -f "robot_nav/waypoint_recorder"     2>/dev/null
    pkill -9 -f "robot_nav/waypoint_follower"     2>/dev/null
    pkill -9 -f "robot_state_publisher"           2>/dev/null
    pkill -9 -f "livox_ros_driver2_node"          2>/dev/null
    pkill -9 -f "fastlio_mapping"                 2>/dev/null
    pkill -9 -f "ros2-hoverboard-driver/main"     2>/dev/null
    echo "Pronto."
    exit 0
}
trap cleanup INT TERM EXIT

LOG_DIR="$SCRIPT_DIR/controle_web/logs"
mkdir -p "$LOG_DIR"

# --- [1] Driver do hoverboard ---
if [ "$NO_HOVERBOARD" = false ]; then
    echo "[1/3] Iniciando driver do hoverboard..."
    DRIVER_LOG="$LOG_DIR/hoverboard_driver.log"
    ros2 run ros2-hoverboard-driver main > "$DRIVER_LOG" 2>&1 &
    DRIVER_PID=$!
    echo "      PID: $DRIVER_PID  |  Log: $DRIVER_LOG"
    sleep 2
    if ! kill -0 "$DRIVER_PID" 2>/dev/null; then
        echo "AVISO: Driver do hoverboard falhou. Veja $DRIVER_LOG"
        echo "(Continuando sem hardware — só pose e logs de cmd_vel)"
    fi
else
    echo "[1/3] Hoverboard desativado (--no-hoverboard)"
fi

# --- [2] play.launch.py — nós do robô, LiDAR, LIO, recorder, follower ---
USE_LIDAR="true"
[ "$NO_LIDAR" = true ] && USE_LIDAR="false"

echo "[2/3] Iniciando play.launch.py (use_lidar=$USE_LIDAR)..."
PLAY_LOG="$LOG_DIR/play.log"
ros2 launch robot_nav play.launch.py use_lidar:="$USE_LIDAR" > "$PLAY_LOG" 2>&1 &
PLAY_PID=$!
echo "      PID: $PLAY_PID  |  Log: $PLAY_LOG"
sleep 4   # tempo pro FAST-LIO2 estabilizar antes do Flask começar a consumir /Odometry

# --- [3] Servidor web ---
cd "$SCRIPT_DIR/controle_web"
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Web em http://0.0.0.0:5000"
if [ "$USE_LIDAR" = "true" ]; then
    echo "  Mid-360 → FAST-LIO2 publicando /Odometry"
else
    echo "  (sem LiDAR — pose não estará disponível)"
fi
echo "  Logs dos nós em $LOG_DIR/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 app.py
SERVER_EXIT=$?
echo "Servidor web encerrou (exit=$SERVER_EXIT)"
