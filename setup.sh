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
    arp-scan iproute2 iputils-ping \
    ros-jazzy-xacro ros-jazzy-robot-state-publisher \
    ros-jazzy-pcl-conversions ros-jazzy-pcl-ros \
    ros-jazzy-tf2 ros-jazzy-tf2-ros ros-jazzy-tf2-geometry-msgs

echo
echo "=== [2/5] Livox-SDK2 (dep nativa do livox_ros_driver2) ==="
if [ ! -d "$SDK_DIR" ]; then
    git clone https://github.com/Livox-SDK/Livox-SDK2.git "$SDK_DIR"
fi
cd "$SDK_DIR"

# Patch: GCC 13+ não inclui <cstdint> transitivamente — adiciona onde falta
echo "  Aplicando patch cstdint (GCC 13+)..."
grep -rl --include='*.h' --include='*.cpp' -E '\buint(8|16|32|64)_t\b' sdk_core/ | while read f; do
    grep -qE '#include\s*<(cstdint|stdint\.h)>' "$f" || \
        sed -i '0,/#include/s/#include/#include <cstdint>\n#include/' "$f"
done

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
# livox_ros_driver2 — repo único com suporte ROS1/ROS2; precisa de package.xml + launch/
clone_if_missing livox_ros_driver2      https://github.com/Livox-SDK/livox_ros_driver2.git
if [ ! -f livox_ros_driver2/package.xml ]; then
    ln -sf package_ROS2.xml livox_ros_driver2/package.xml
    echo "  criado symlink package.xml -> package_ROS2.xml"
fi
if [ ! -d livox_ros_driver2/launch ]; then
    cp -rf livox_ros_driver2/launch_ROS2/ livox_ros_driver2/launch/
    echo "  copiado launch_ROS2/ -> launch/"
fi
# FAST-LIO (hku-mars) — branch ROS2 (default é ROS1/main, precisamos da branch ROS2)
clone_if_missing FAST_LIO                https://github.com/hku-mars/FAST_LIO.git ROS2
# ikd-Tree é submódulo do FAST_LIO
cd FAST_LIO && git submodule update --init --recursive
# Patch: FAST_LIO usa C++14, mas ROS2 Jazzy (rclcpp) exige C++17
if grep -q 'CMAKE_CXX_STANDARD 14' CMakeLists.txt 2>/dev/null; then
    echo "  Aplicando patch C++17 no FAST_LIO..."
    sed -i 's/std=c++14/std=c++17/g; s/std=c++0x//g; s/CMAKE_CXX_STANDARD 14/CMAKE_CXX_STANDARD 17/g' CMakeLists.txt
fi
# Patch: FAST_LIO tem um "-" solto em CMAKE_CXX_FLAGS que o gcc interpreta como
# stdin, gerando "cannot specify -o with -c ... with multiple files" em Jazzy/GCC13+.
if grep -q 'pthread - -std=c++17' CMakeLists.txt 2>/dev/null; then
    echo "  Removendo '-' solto em CMAKE_CXX_FLAGS do FAST_LIO..."
    sed -i 's/-pthread - -std=c++17/-pthread/g' CMakeLists.txt
fi
cd ..

clone_if_missing ros2-hoverboard-driver https://github.com/victorfdezc/ros2-hoverboard-driver.git

echo
echo "=== [4/5] Compilando com colcon ==="
cd "$WS_DIR"
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --cmake-args -DROS_EDITION=ROS2 -DDISTRO_ROS=jazzy

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
echo "=== [6/7] udev do hoverboard ==="
if [ -f "$REPO_DIR/setup_udev.sh" ]; then
    sudo "$REPO_DIR/setup_udev.sh" || echo "  (opcional) falhou — rode 'sudo ./setup_udev.sh' manualmente se for usar o hoverboard"
fi

echo
echo "=== [7/7] Auto-detecção do Mid-360 ==="
# Se o LiDAR estiver plugado AGORA, descobre o IP e atualiza o mid360_config.json.
MID360_CONFIG="$REPO_DIR/ros2_packages/robot_nav/config/mid360_config.json"
detect_livox_iface() {
    # Procura interface ethernet UP que não seja loopback/wifi/docker
    ip -o link show 2>/dev/null \
        | awk -F': ' '$2 !~ /^(lo|wlo|wlan|docker|br-|veth)/ && $0 ~ /state UP/ {print $2}' \
        | head -n 1
}
IFACE="$(detect_livox_iface)"
if [ -z "$IFACE" ]; then
    echo "  Nenhuma interface ethernet UP detectada. Plugue o cabo RJ45 do Mid-360 e rode:"
    echo "    sudo nmcli connection add type ethernet ifname <iface> con-name livox ipv4.addresses 192.168.1.5/24 ipv4.method manual ipv6.method disabled"
    echo "    sudo nmcli connection up livox"
else
    echo "  Interface ethernet detectada: $IFACE"
    # Garante IP na subnet 192.168.1.0/24 via NetworkManager (idempotente)
    if ! sudo nmcli connection show livox >/dev/null 2>&1; then
        echo "  Criando perfil NetworkManager 'livox' em $IFACE..."
        sudo nmcli connection add type ethernet ifname "$IFACE" con-name livox \
            ipv4.addresses 192.168.1.5/24 ipv4.method manual ipv6.method disabled \
            connection.autoconnect yes || true
    fi
    sudo nmcli connection up livox >/dev/null 2>&1 || true
    sleep 1

    # Varre rede pra achar o LiDAR
    echo "  Varredura arp-scan em $IFACE/192.168.1.0/24 ..."
    SCAN_OUT="$(sudo arp-scan --interface="$IFACE" 192.168.1.0/24 2>/dev/null || true)"
    LIDAR_IP="$(echo "$SCAN_OUT" | awk '/^192\.168\.1\./ {print $1; exit}')"
    if [ -n "$LIDAR_IP" ]; then
        echo "  LiDAR encontrado em $LIDAR_IP"
        if [ -f "$MID360_CONFIG" ] && grep -q '"ip":' "$MID360_CONFIG"; then
            sed -i "s|\"ip\": \"192\.168\.1\.[0-9]\+\"|\"ip\": \"$LIDAR_IP\"|" "$MID360_CONFIG"
            echo "  mid360_config.json atualizado com $LIDAR_IP"
        fi
    else
        echo "  Nenhum dispositivo respondeu na 192.168.1.0/24. Verifique:"
        echo "    - Cabo RJ45 direto PC↔LiDAR"
        echo "    - Alimentação 9–27V no Mid-360 (LED aceso)"
        echo "  Depois rode: sudo arp-scan --interface=$IFACE --localnet"
        echo "  E edite manualmente o IP em $MID360_CONFIG"
    fi
fi

echo
echo "=== Pronto! ==="
echo
echo "1) Rede do Mid-360 — plugue o cabo RJ45 e configure IP estático:"
echo "   a) Descubra o nome da sua interface (ex: enp3s0):"
echo "        ip -o link show | awk -F': ' '\$2 !~ /^(lo|wlo|docker)/ {print \$2}'"
echo "   b) Crie o perfil (substitua enp3s0 pelo seu):"
echo "        sudo nmcli connection add type ethernet ifname enp3s0 con-name livox \\"
echo "             ipv4.addresses 192.168.1.5/24 ipv4.method manual ipv6.method disabled"
echo "        sudo nmcli connection up livox"
echo "   c) Descubra o IP do Mid-360 (varre rede):"
echo "        sudo arp-scan --interface=enp3s0 --localnet"
echo "   d) Edite mid360_config.json com o IP do lidar (campo 'ip'):"
echo "        $REPO_DIR/ros2_packages/robot_nav/config/mid360_config.json"
echo
echo "2) Abra um terminal novo (ou: source $WS_DIR/install/setup.bash) e rode:"
echo "   cd $REPO_DIR && ./launch.sh                  # tudo (com LiDAR)"
echo "   cd $REPO_DIR && ./launch.sh --no-lidar       # sem LiDAR (teleop puro)"
echo "   cd $REPO_DIR && ./launch.sh --no-hoverboard  # sem base física"
