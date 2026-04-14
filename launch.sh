#!/bin/bash
# Launcher completo: hoverboard driver + LiDAR + servidor web.
#
# Modos:
#   ./launch.sh                                   # TELEOP (padrão) — web + collision monitor
#   ./launch.sh --slam                            # SLAM — mapeia o ambiente em tempo real
#   ./launch.sh --nav2                            # NAV2 — navegação autônoma (mapa padrão)
#   ./launch.sh --nav2 --map=/caminho/sala.yaml   # NAV2 — mapa específico
#
# Outras flags:
#   --no-lidar             desabilita o LiDAR
#   --no-nav2              desabilita o collision monitor (modo teleop)
#   --lidar-port=/dev/X    sobrescreve a porta do LiDAR (padrão /dev/lidar)
#
# Ctrl+C encerra todos os processos.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROS2_SETUP="$HOME/ros2_ws/install/setup.bash"

# --- Argumentos ---
NO_LIDAR=false
NO_NAV2=false
LIDAR_PORT="/dev/lidar"
MODE="teleop"                     # teleop | slam | nav2
MAP_FILE="$SCRIPT_DIR/maps/sala.yaml"

for arg in "$@"; do
    case $arg in
        --slam)         MODE="slam" ;;
        --nav2)         MODE="nav2" ;;
        --map=*)        MAP_FILE="${arg#*=}" ;;
        --no-lidar)     NO_LIDAR=true ;;
        --no-nav2)      NO_NAV2=true ;;
        --lidar-port=*) LIDAR_PORT="${arg#*=}" ;;
    esac
done

# Em SLAM e NAV2 o LiDAR é obrigatório.
if [ "$MODE" != "teleop" ] && [ "$NO_LIDAR" = true ]; then
    echo "ERRO: modo $MODE precisa do LiDAR. Remova --no-lidar."
    exit 1
fi

# Em NAV2 o arquivo de mapa precisa existir antes de subir.
if [ "$MODE" = "nav2" ] && [ ! -f "$MAP_FILE" ]; then
    echo "ERRO: mapa '$MAP_FILE' não encontrado."
    echo "  Rode primeiro: ./launch.sh --slam  (mapeie a sala e clique em 'Salvar mapa')"
    exit 1
fi

mkdir -p "$SCRIPT_DIR/maps"

if [ ! -f "$ROS2_SETUP" ]; then
    echo "ERRO: $ROS2_SETUP não encontrado."
    echo "Execute: cd ~/ros2_ws && colcon build"
    exit 1
fi

source "$ROS2_SETUP"

# --- Bootstrap do venv com dependências Python ---
VENV_DIR="$SCRIPT_DIR/controle_web/.venv"
REQ_FILE="$SCRIPT_DIR/controle_web/requirements.txt"
REQ_STAMP="$VENV_DIR/.requirements.sha1"

if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "Criando venv em $VENV_DIR..."
    python3 -m venv "$VENV_DIR" || {
        echo "ERRO: falha ao criar venv. Instale python3-venv: sudo apt install python3-venv"
        exit 1
    }
fi

# Reinstala apenas se requirements.txt mudou
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

# --- Limpa órfãos de execuções anteriores (nós ROS2 e app.py) ---
pkill -9 -f "robot_nav/odom_publisher"      2>/dev/null
pkill -9 -f "robot_nav/cmd_vel_to_wheels"   2>/dev/null
pkill -9 -f "robot_nav/obstacle_detector"   2>/dev/null
pkill -9 -f "robot_state_publisher"         2>/dev/null
pkill -9 -f "ldlidar_stl_ros2_node"         2>/dev/null
pkill -9 -f "ros2-hoverboard-driver/main"   2>/dev/null
pkill -9 -f "async_slam_toolbox_node"       2>/dev/null
pkill -9 -f "nav2_map_server"               2>/dev/null
pkill -9 -f "nav2_amcl"                     2>/dev/null
pkill -9 -f "nav2_planner"                  2>/dev/null
pkill -9 -f "nav2_controller"               2>/dev/null
pkill -9 -f "nav2_behaviors"                2>/dev/null
pkill -9 -f "nav2_bt_navigator"             2>/dev/null
pkill -9 -f "nav2_velocity_smoother"        2>/dev/null
pkill -9 -f "nav2_lifecycle_manager"        2>/dev/null
pkill -9 -f "nav2_waypoint_follower"        2>/dev/null

# --- Libera porta 5000 se já estiver em uso ---
PORT_PID=$(ss -tlnp 2>/dev/null | awk '/:5000 /{match($0,/pid=([0-9]+)/,a); if(a[1]) print a[1]}')
if [ -n "$PORT_PID" ]; then
    echo "Porta 5000 em uso pelo PID $PORT_PID — encerrando antes de subir..."
    kill -9 "$PORT_PID" 2>/dev/null
    sleep 1
fi

DRIVER_PID=""
SERVER_PID=""
ROBOT_PID=""
LIDAR_PID=""
OBSTACLE_PID=""
NAV2_PID=""
SLAM_PID=""
TAIL_PID=""

kill_tree() {
    # Mata o processo e todos os descendentes (filhos, netos...).
    # Necessário porque `ros2 launch` spawna nós filhos que não morrem
    # só matando o pai.
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
    [ -n "$TAIL_PID" ]     && kill "$TAIL_PID"     2>/dev/null
    kill_tree "$SERVER_PID"
    kill_tree "$SLAM_PID"
    kill_tree "$NAV2_PID"
    kill_tree "$OBSTACLE_PID"
    kill_tree "$LIDAR_PID"
    kill_tree "$ROBOT_PID"
    kill_tree "$DRIVER_PID"
    sleep 1
    # Segunda passada: SIGKILL em qualquer filho que tenha sobrevivido
    for pid in $SERVER_PID $SLAM_PID $NAV2_PID $OBSTACLE_PID $LIDAR_PID $ROBOT_PID $DRIVER_PID; do
        for desc in $(pgrep -P "$pid" 2>/dev/null) $pid; do
            kill -9 "$desc" 2>/dev/null
        done
    done
    # Rede de segurança: mata qualquer nó do robot_nav órfão que reste
    pkill -9 -f "robot_nav/odom_publisher"      2>/dev/null
    pkill -9 -f "robot_nav/cmd_vel_to_wheels"   2>/dev/null
    pkill -9 -f "robot_nav/obstacle_detector"   2>/dev/null
    pkill -9 -f "robot_state_publisher"         2>/dev/null
    pkill -9 -f "ldlidar_stl_ros2_node"         2>/dev/null
    pkill -9 -f "ros2-hoverboard-driver/main"   2>/dev/null
    pkill -9 -f "async_slam_toolbox_node"       2>/dev/null
    pkill -9 -f "nav2_map_server"               2>/dev/null
    pkill -9 -f "nav2_amcl"                     2>/dev/null
    pkill -9 -f "nav2_planner"                  2>/dev/null
    pkill -9 -f "nav2_controller"               2>/dev/null
    pkill -9 -f "nav2_behaviors"                2>/dev/null
    pkill -9 -f "nav2_bt_navigator"             2>/dev/null
    pkill -9 -f "nav2_velocity_smoother"        2>/dev/null
    pkill -9 -f "nav2_lifecycle_manager"        2>/dev/null
    pkill -9 -f "nav2_waypoint_follower"        2>/dev/null
    rm -f /tmp/obstacle_current.json
    echo "Pronto."
    exit 0
}
trap cleanup INT TERM EXIT

LOG_DIR="$SCRIPT_DIR/controle_web/logs"
mkdir -p "$LOG_DIR"

# --- [1] Driver do hoverboard ---
echo "[1/4] Iniciando driver do hoverboard (porta: /dev/hoverboard)..."
DRIVER_LOG="$LOG_DIR/hoverboard_driver.log"
ros2 run ros2-hoverboard-driver main > "$DRIVER_LOG" 2>&1 &
DRIVER_PID=$!
echo "      PID: $DRIVER_PID  |  Log: $DRIVER_LOG"

sleep 2

if ! kill -0 "$DRIVER_PID" 2>/dev/null; then
    echo "AVISO: Driver do hoverboard falhou. Veja o log:"
    cat "$DRIVER_LOG"
    echo "(Continuando sem hardware — modo simulação)"
fi

# --- [2] Nós do robô (robot_state_publisher + odom + cmd_vel_to_wheels) ---
echo "[2/4] Iniciando nós do robô (URDF, odometria, cmd_vel->wheels)..."
ROBOT_LOG="$LOG_DIR/robot_nodes.log"
ros2 launch robot_nav robot.launch.py > "$ROBOT_LOG" 2>&1 &
ROBOT_PID=$!
echo "      PID: $ROBOT_PID  |  Log: $ROBOT_LOG"

sleep 2

# --- [3] LiDAR FHL-LD20 + detector de obstáculos ---
if [ "$NO_LIDAR" = false ]; then
    if [ -e "$LIDAR_PORT" ]; then
        echo "[3/5] Iniciando LiDAR FHL-LD20 em $LIDAR_PORT..."
        LIDAR_LOG="$LOG_DIR/lidar.log"
        ros2 launch robot_nav lidar.launch.py lidar_port:="$LIDAR_PORT" > "$LIDAR_LOG" 2>&1 &
        LIDAR_PID=$!
        echo "      PID: $LIDAR_PID  |  Log: $LIDAR_LOG"
        sleep 1

        echo "      Iniciando detector de obstáculos..."
        OBSTACLE_LOG="$LOG_DIR/obstacle_detector.log"
        ros2 run robot_nav obstacle_detector > "$OBSTACLE_LOG" 2>&1 &
        OBSTACLE_PID=$!
        echo "      PID: $OBSTACLE_PID  |  Log: $OBSTACLE_LOG"
        sleep 1
    else
        echo "[3/5] AVISO: Porta do LiDAR $LIDAR_PORT não encontrada. Pulando LiDAR."
        echo "      Para especificar outra porta: ./launch.sh --lidar-port=/dev/ttyUSB2"
        NO_LIDAR=true
    fi
else
    echo "[3/5] LiDAR desativado (--no-lidar)"
fi

# --- [4] SLAM ou Nav2 ou Collision Monitor (conforme modo) ---
case "$MODE" in
    slam)
        echo "[4/5] Modo SLAM — subindo slam_toolbox (mapping online)..."
        SLAM_LOG="$LOG_DIR/slam.log"
        ros2 launch robot_nav slam.launch.py > "$SLAM_LOG" 2>&1 &
        SLAM_PID=$!
        echo "      PID: $SLAM_PID  |  Log: $SLAM_LOG"
        sleep 3
        ;;
    nav2)
        echo "[4/5] Modo NAV2 — subindo Nav2 com mapa $MAP_FILE..."
        NAV2_LOG="$LOG_DIR/nav2.log"
        ros2 launch robot_nav nav2.launch.py map:="$MAP_FILE" > "$NAV2_LOG" 2>&1 &
        NAV2_PID=$!
        echo "      PID: $NAV2_PID  |  Log: $NAV2_LOG"
        sleep 5
        ;;
    teleop)
        if [ "$NO_NAV2" = false ] && ros2 pkg list 2>/dev/null | grep -q "nav2_collision_monitor"; then
            echo "[4/5] Modo TELEOP — subindo Nav2 Collision Monitor..."
            NAV2_LOG="$LOG_DIR/nav2_collision.log"
            ros2 launch robot_nav nav2_collision.launch.py > "$NAV2_LOG" 2>&1 &
            NAV2_PID=$!
            echo "      PID: $NAV2_PID  |  Log: $NAV2_LOG"
            sleep 2
        else
            echo "[4/5] Modo TELEOP — sem collision monitor."
        fi
        ;;
esac

# --- [5] Servidor web ---
echo ""
echo "[5/5] Iniciando servidor web em http://0.0.0.0:5000 (modo: $MODE)"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
case "$MODE" in
    slam)
        echo "  MODO SLAM — dirija o robô para mapear. Salve o mapa pelo botão web."
        echo "  slam_toolbox publicando /map (~1 Hz) e TF map→odom."
        ;;
    nav2)
        echo "  MODO NAV2 — clique no mapa web para enviar o robô a um destino."
        echo "  Mapa: $MAP_FILE"
        echo "  AMCL publicando map→odom. bt_navigator consome /goal_pose."
        ;;
    teleop)
        echo "  MODO TELEOP — Web → /cmd_vel → cmd_vel_to_wheels → Hoverboard"
        ;;
esac
if [ "$NO_LIDAR" = false ]; then
    echo "  LiDAR FHL-LD20 publicando em: /scan"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd "$SCRIPT_DIR/controle_web"
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

echo "Logs dos nós em $LOG_DIR/ (ex: tail -f $DRIVER_LOG)"
echo ""

# Passa o modo e o diretório de mapas para o app.py via env.
export ROBOT_MODE="$MODE"
export ROBOT_MAPS_DIR="$SCRIPT_DIR/maps"

# Servidor em primeiro plano — Ctrl+C aqui dispara cleanup() via trap.
python3 app.py
SERVER_EXIT=$?
echo "Servidor web encerrou (exit=$SERVER_EXIT)"
