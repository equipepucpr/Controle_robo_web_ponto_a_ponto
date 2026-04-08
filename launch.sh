#!/bin/bash
# Launcher completo: sobe o driver do hoverboard e o servidor web juntos.
# Uso: ./launch.sh
# Ctrl+C encerra os dois processos.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROS2_SETUP="$HOME/ros2_ws/install/setup.bash"

if [ ! -f "$ROS2_SETUP" ]; then
    echo "ERRO: $ROS2_SETUP não encontrado."
    echo "Execute: cd ~/ros2_ws && colcon build --packages-select ros2-hoverboard-driver wheel_msgs"
    exit 1
fi

source "$ROS2_SETUP"

# Encerra tudo ao sair (Ctrl+C ou erro)
cleanup() {
    echo ""
    echo "Encerrando..."
    kill "$DRIVER_PID" 2>/dev/null
    kill "$SERVER_PID" 2>/dev/null
    wait "$DRIVER_PID" "$SERVER_PID" 2>/dev/null
    echo "Pronto."
}
trap cleanup EXIT INT TERM

# --- Driver do hoverboard (background, log em arquivo) ---
LOG_DIR="$SCRIPT_DIR/controle_web/logs"
mkdir -p "$LOG_DIR"
DRIVER_LOG="$LOG_DIR/hoverboard_driver.log"

echo "[1/2] Iniciando driver do hoverboard..."
ros2 run ros2-hoverboard-driver main > "$DRIVER_LOG" 2>&1 &
DRIVER_PID=$!
echo "      PID: $DRIVER_PID  |  Log: $DRIVER_LOG"

# Aguarda o driver subir antes de iniciar o servidor
sleep 2

if ! kill -0 "$DRIVER_PID" 2>/dev/null; then
    echo "ERRO: Driver falhou ao iniciar. Veja o log:"
    cat "$DRIVER_LOG"
    exit 1
fi

# --- Servidor web (foreground, saída no terminal) ---
echo "[2/2] Iniciando servidor web em http://0.0.0.0:5000"
echo ""

cd "$SCRIPT_DIR/controle_web"
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

python3 app.py &
SERVER_PID=$!

# Exibe log do driver em paralelo no terminal
echo "--- Log do driver (tail) ---"
tail -f "$DRIVER_LOG" &
TAIL_PID=$!

# Espera o servidor terminar (Ctrl+C cai no trap acima)
wait "$SERVER_PID"
kill "$TAIL_PID" 2>/dev/null
