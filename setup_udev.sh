#!/bin/bash
# Configura /dev/hoverboard como symlink estável via localização física da porta USB.
# Neste fork o LiDAR é um Livox Mid-360 (Ethernet), então só o hoverboard entra
# nas regras udev. O Mid-360 se conecta via IP — ver setup.sh e mid360_config.json.
#
# Uso: sudo ./setup_udev.sh

set -e

if [ "$EUID" -ne 0 ]; then
    echo "ERRO: Execute com sudo: sudo ./setup_udev.sh"
    exit 1
fi

RULES_FILE="/etc/udev/rules.d/99-robot-usb.rules"

get_devpath() {
    local dev="$1"
    udevadm info "$dev" 2>/dev/null \
        | awk -F= '/DEVPATH/{print $2}' \
        | grep -oP '[0-9]+-[0-9]+(\.[0-9]+)*(?=:[0-9]+\.[0-9]+/ttyUSB)' \
        | head -1
}

get_vidpid() {
    local dev="$1"
    local vid pid
    vid=$(udevadm info "$dev" 2>/dev/null | awk -F= '/ID_VENDOR_ID/{print $2}')
    pid=$(udevadm info "$dev" 2>/dev/null | awk -F= '/ID_MODEL_ID/{print $2}')
    echo "${vid}:${pid}"
}

echo "========================================================"
echo "  Configuração de porta USB fixa — Hoverboard"
echo "========================================================"
echo ""
echo "Plugue SOMENTE o hoverboard. O Mid-360 é Ethernet — não precisa de udev."
read -p "Pressione ENTER quando estiver pronto..."

sleep 1
udevadm settle

PORTS_HOVER=$(ls /dev/ttyUSB* 2>/dev/null)
if [ -z "$PORTS_HOVER" ]; then
    echo "ERRO: Nenhum /dev/ttyUSB* encontrado. Verifique a conexão do hoverboard."
    exit 1
fi

echo "  Dispositivos detectados:"
for p in $PORTS_HOVER; do
    vidpid=$(get_vidpid "$p")
    path=$(get_devpath "$p")
    echo "    $p  [VID:PID=$vidpid  USB path=$path]"
done

if [ "$(echo "$PORTS_HOVER" | wc -l)" -eq 1 ]; then
    HOVER_PORT="$PORTS_HOVER"
else
    read -p "  Qual é a porta do hoverboard? (ex: /dev/ttyUSB0): " HOVER_PORT
fi

HOVER_PATH=$(get_devpath "$HOVER_PORT")
HOVER_VIDPID=$(get_vidpid "$HOVER_PORT")

echo "  Hoverboard: $HOVER_PORT → path=$HOVER_PATH  VID:PID=$HOVER_VIDPID"
echo ""

echo "Criando $RULES_FILE ..."

cat > "$RULES_FILE" << EOF
# Regra udev para symlink estável do hoverboard.
# Usa localização física da porta USB (KERNELS) pra sobreviver a renumeração.
# Gerado por setup_udev.sh em $(date).
#
# Para regenerar: sudo ./setup_udev.sh

SUBSYSTEM=="tty", KERNELS=="$HOVER_PATH", SYMLINK+="hoverboard", MODE="0666", GROUP="dialout"
EOF

echo ""
cat "$RULES_FILE"

echo ""
echo "Recarregando regras udev..."
udevadm control --reload-rules
udevadm trigger
sleep 1

echo ""
echo "=== Verificando symlink ==="
ls -la /dev/hoverboard 2>/dev/null || echo "AVISO: /dev/hoverboard não apareceu ainda — desplugue e replugue o cabo USB."

echo ""
echo "=== Pronto! ==="
echo "Se trocar o cabo de entrada USB, rode este script novamente."
echo ""
echo "Próximo passo — recompile o driver do hoverboard:"
echo "  cd ~/ros2_ws"
echo "  colcon build --packages-select ros2-hoverboard-driver"
echo "  source install/setup.bash"
