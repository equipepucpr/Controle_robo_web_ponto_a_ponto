# Controle Web do Robô Hoverboard

Interface web para controlar um robô hoverboard com ROS2, LiDAR FHL-LD20, detecção de obstáculos, **mapeamento SLAM** e **navegação autônoma Nav2 com click-to-go** no mapa web.

## Sumário

- [Guia rápido — do zero ao click-to-go](#guia-rápido--do-zero-ao-click-to-go)
- [Visão geral](#visão-geral)
- [Os três modos de operação](#os-três-modos-de-operação)
- [Modo SIM — testar tudo no Gazebo sem hardware](#modo-sim--testar-tudo-no-gazebo-sem-hardware)
- [Pré-requisitos](#pré-requisitos)
- [Configuração inicial (uma vez)](#configuração-inicial-uma-vez)
  - [1. Workspace ROS2](#1-workspace-ros2)
  - [2. Portas USB fixas](#2-portas-usb-fixas-obrigatório)
  - [3. Dependências Python](#3-dependências-python)
- [Como rodar](#como-rodar)
  - [Modo TELEOP (padrão)](#modo-teleop-padrão)
  - [Modo SLAM — mapear a sala](#modo-slam--mapear-a-sala)
  - [Modo NAV2 — navegação autônoma](#modo-nav2--navegação-autônoma)
- [Controles](#controles)
- [Arquitetura](#arquitetura)
  - [Ponte ROS2 ↔ Web para mapa e navegação](#ponte-ros2--web-para-mapa-e-navegação)
- [Logs](#logs)
- [Limitações conhecidas](#limitações-conhecidas)
- [Solução de problemas](#solução-de-problemas)

---

## Guia rápido — do zero ao click-to-go

Passo a passo condensado para quem está pegando uma máquina nova e quer ver o robô andando sozinho no Gazebo, clicando num ponto do mapa. Todas as seções abaixo têm mais detalhes, isto aqui é o caminho feliz.

### 1. Instalar o ROS2 Jazzy

Siga o guia oficial (~10 min): https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html

Confirme:

```bash
source /opt/ros/jazzy/setup.bash
echo "source /opt/ros/jazzy/setup.bash" >> ~/.bashrc
ros2 --help   # deve listar os comandos
```

### 2. Clonar este repositório

```bash
git clone <url-do-repo> ~/Controle_robo_web
```

### 3. Rodar o setup automatizado

O script `setup.sh` na raiz do repo faz tudo de uma vez: instala dependências apt, monta o `~/ros2_ws`, faz symlink do `robot_nav`, clona o `wheel_msgs` e roda `colcon build`.

```bash
cd ~/Controle_robo_web
./setup.sh
```

O script é idempotente — se já tiver rodado antes, pode rodar de novo sem quebrar nada. Ele cobre:

- **apt install**: `xacro`, `robot-state-publisher`, `slam-toolbox`, `nav2-bringup`, `nav2-collision-monitor`, `nav2-map-server`, `nav2-amcl`, `ros-gz`, `ros-gz-sim`, `ros-gz-bridge`, `ros-gz-interfaces` (tudo para Jazzy), além de `git`, `python3-venv`, `python3-pip`.
- **Workspace**: cria `~/ros2_ws/src`, faz o symlink do `robot_nav` deste repo, clona `wheel_msgs` ([Richard-Haes-Ellis/wheel_msgs](https://github.com/Richard-Haes-Ellis/wheel_msgs)), compila com `colcon build` e adiciona o `source` ao `~/.bashrc`.

Se for usar hardware real, descomente no `setup.sh` as duas linhas de clone de `ros2-hoverboard-driver` e `ldlidar_stl_ros2` antes de rodar, ou clone/compile manualmente depois.

| Pacote | Obrigatório? | Para quê |
|--------|--------------|----------|
| `wheel_msgs` | **sempre** (até no sim, senão `colcon build` falha) | Tipo de mensagem `WheelSpeeds` |
| `ros2-hoverboard-driver` | só no modo real | Driver C++ do hoverboard |
| `ldlidar_stl_ros2` | só no modo real | Driver do LiDAR FHL-LD20 |

### 4. (Só hardware real) Fixar portas USB

Se for rodar no robô físico, o hoverboard e o LiDAR precisam de symlinks estáveis em `/dev/hoverboard` e `/dev/lidar`:

```bash
sudo ~/Controle_robo_web/setup_udev.sh
```

Depois recompile o driver:
```bash
cd ~/ros2_ws && colcon build --packages-select ros2-hoverboard-driver
```

Pule este passo inteiro se só vai usar `--sim`.

### 5. Primeira execução — teste rápido no sim

Não precisa configurar mais nada. O `launch.sh` cria o `venv` Python e instala Flask/Socket.IO/Pillow automaticamente na primeira vez.

```bash
cd ~/Controle_robo_web
./launch.sh --sim
```

O que deve acontecer:
1. Uma janela do Gazebo Harmonic abre mostrando uma sala 6×6 m vazia (do `worlds/empty.sdf`) com o robô simulado no centro.
2. No terminal aparece `Iniciando servidor web em http://0.0.0.0:5000 (modo: teleop [SIM/Gazebo])`.
3. Abra `http://localhost:5000` no navegador — você vê a UI com o badge `TELEOP`.
4. Clique na área da página e use `WASD` ou setas: o robô se move no Gazebo.

`Ctrl+C` no terminal fecha tudo (Gazebo, bridges, web).

### 6. Mapear a sala simulada (SLAM)

```bash
./launch.sh --sim --slam
```

Na UI o badge vira `SLAM` e um painel **Mapa** aparece. Dirija o robô **devagar** pela sala com WASD/setas (ver [dicas de mapeamento](#modo-slam--mapear-a-sala)). O mapa cresce em tempo real no painel web.

Quando o mapa estiver bom, clique em **Salvar mapa** → nome padrão `sala` → gera `maps/sala.yaml` + `maps/sala.pgm`. Depois `Ctrl+C`.

### 7. Navegação autônoma (NAV2 click-to-go)

```bash
./launch.sh --sim --nav2
```

O badge vira `NAV2`, o painel **Mapa** mostra o mapa estático que você salvou, o robô aparece como seta laranja. **Clique em qualquer ponto livre do mapa** — o Nav2 calcula a rota (linha azul), o bt_navigator dispara o controlador e o robô do Gazebo vai até lá.

### 8. (Opcional) Use a sala que você projetou

Coloque o arquivo `.sdf` da sua sala em `Controle_robo_web/worlds/` e passe por flag:

```bash
./launch.sh --sim --slam  --world=worlds/minha_sala.sdf
./launch.sh --sim --nav2  --world=worlds/minha_sala.sdf
```

Veja [Onde colocar o arquivo da sala](#onde-colocar-o-arquivo-da-sala-mundo-gazebo) para o checklist do que o `.sdf` precisa ter (physics, luz, ground_plane, collisions).

### 9. Migrar para o hardware real

Quando o fluxo estiver funcionando no sim, basta tirar o `--sim` dos comandos. A mesma UI, o mesmo `/goal_pose`, o mesmo mapa (se for a mesma sala) — e agora com `launch.sh --slam` / `launch.sh --nav2` o robô físico responde. O único diferencial é que você precisa ter rodado o passo **4** antes.

---

## Visão geral

```
Navegador (WASD / Gamepad / Clique no mapa)
        │  Socket.IO
        ▼
  Flask + Socket.IO (porta 5000)
        │  /cmd_vel  (geometry_msgs/Twist)
        │  /goal_pose (PoseStamped) — só em NAV2
        ▼
  cmd_vel_to_wheels
        │  /wheel_vel_setpoints  (wheel_msgs/WheelSpeeds)
        ▼
  ros2-hoverboard-driver  ──────►  /dev/hoverboard (USB serial)

  LiDAR FHL-LD20  ──────────────►  /dev/lidar (USB serial)
        │  /scan  (sensor_msgs/LaserScan)
        ▼
  ┌─────────────────────────┬─────────────────────────┐
  │  TELEOP                 │  SLAM                   │  NAV2
  │  obstacle_detector      │  slam_toolbox           │  map_server + amcl
  │  → /tmp/obstacle_*.json │  → /map (ao vivo)       │  → /map (estático)
  │                         │  → TF map→odom          │  + planner + controller
  │                         │                         │  → /goal_pose → /plan
  └─────────────────────────┴─────────────────────────┘
        │
        ▼  map_service.py (ponte ROS2 → Socket.IO)
  /map (OccupancyGrid → PNG)
  TF map→base_link (pose do robô, 10 Hz)
  /plan (trajetória, quando Nav2 está ativo)
        │
        ▼
  Canvas do mapa no navegador
    (renderiza mapa + robô + plano;
     click envia /goal_pose em modo NAV2)
```

---

## Os três modos de operação

O `launch.sh` tem um conceito central: **o modo**. Cada modo sobe uma combinação diferente de nós ROS2 para um propósito distinto:

| Modo | Flag | Pra quê serve | O que sobe a mais |
|------|------|---------------|-------------------|
| **TELEOP** | *(padrão)* | Dirigir manualmente pela sala | `nav2_collision_monitor` — só segurança (freia se tiver obstáculo perto) |
| **SLAM** | `--slam` | Construir o mapa da sala pela primeira vez | `slam_toolbox` em modo *mapping online* (gera `/map` ao vivo) |
| **NAV2** | `--nav2` | Navegação autônoma usando um mapa já salvo | `map_server` + `amcl` + `planner_server` + `controller_server` + `bt_navigator` + `behavior_server` + `velocity_smoother` + `waypoint_follower` |

Nos três modos o web control, o hoverboard e o LiDAR rodam normalmente — você sempre pode dirigir manualmente, mesmo durante SLAM ou NAV2.

### Espera, por que aparece "nav2" em dois lugares? (collision_monitor vs Nav2 completo)

Dá pra confundir: no modo TELEOP o log mostra `nav2_collision.log` e no modo `--nav2` aparece `nav2.log`. **Não são dois jeitos de rodar o Nav2** — são dois pedaços distintos do mesmo projeto upstream Nav2:

- **`nav2_collision_monitor`** (modo TELEOP) — um único nó pequeno de segurança. Só intercepta `/cmd_vel`, olha o LiDAR, e freia o robô se detectar obstáculo muito perto. **Não** planeja rota, **não** precisa de mapa, **não** sabe onde o robô está no mundo. É uma camada de proteção pra dirigir manualmente.
- **Stack Nav2 completa** (modo `--nav2`) — uma dúzia de nós que fazem navegação autônoma de verdade: carregam um mapa salvo (`map_server`), localizam o robô nele por correlação de scans (`amcl`), planejam rota até um destino (`planner_server`), executam a trajetória desviando de obstáculos dinâmicos (`controller_server`), orquestram tudo com uma árvore de comportamento (`bt_navigator`).

Por vir do mesmo projeto Nav2, os dois compartilham o prefixo `nav2_` no nome dos pacotes — mas têm papéis completamente diferentes.

---

## Modo SIM — testar tudo no Gazebo sem hardware

Antes de arriscar o hoverboard na sala real, você pode rodar o pipeline inteiro (teleop + SLAM + Nav2 click-to-go) dentro do **Gazebo Harmonic**, com um robô diferencial simulado em um mundo customizado por você.

A flag `--sim` troca tudo que é hardware por simulação:

| Stage | Modo real | Modo `--sim` |
|-------|-----------|--------------|
| Driver do hoverboard | `ros2-hoverboard-driver` | — (não usa) |
| Odometria | `odom_publisher` (feedback das rodas) | plugin `DiffDrive` do Gazebo |
| `/cmd_vel → rodas` | `cmd_vel_to_wheels` | plugin `DiffDrive` do Gazebo |
| LiDAR | `ldlidar_stl_ros2` em `/dev/lidar` | sensor `gpu_lidar` na SDF do robô |
| Corpo do robô | URDF (`robot.urdf.xacro`) | URDF + SDF (`sim_robot.sdf`) |
| `/scan`, `/odom`, `/tf` | tópicos reais | via `ros_gz_bridge` (GZ → ROS) |

O servidor web, o `map_service.py` e a UI são exatamente os mesmos — o sim é transparente do ponto de vista do navegador.

### Instalando o Gazebo e o bridge ROS↔GZ

Em Jazzy o Gazebo moderno é o **Harmonic**, separado do ROS:

```bash
sudo apt install \
    ros-$ROS_DISTRO-ros-gz \
    ros-$ROS_DISTRO-ros-gz-sim \
    ros-$ROS_DISTRO-ros-gz-bridge \
    ros-$ROS_DISTRO-ros-gz-interfaces
```

Isso traz o `gz sim` (binário do Gazebo Harmonic) + o `parameter_bridge` que traduz mensagens `gz.msgs.*` ↔ `*_msgs/msg/*`.

### Onde colocar o arquivo da sala (mundo Gazebo)

**Os mundos do Gazebo ficam em `Controle_robo_web/worlds/`** (mesmo nível de `maps/`). O repositório já vem com um arquivo `worlds/empty.sdf` que cria uma sala 6×6 m com quatro paredes, um chão e uma luz — suficiente pra você testar se tudo sobe antes de trocar pelo seu mundo.

Para usar seu próprio mundo, tem dois caminhos:

1. **Substituir o padrão** — jogue seu arquivo como `worlds/sala.sdf` (ou salve por cima do `worlds/empty.sdf`):
   ```bash
   cp ~/minha_sala_projetada.sdf Controle_robo_web/worlds/empty.sdf
   ./launch.sh --sim
   ```

2. **Passar por flag** — aceita caminho absoluto ou relativo à raiz do projeto:
   ```bash
   ./launch.sh --sim --world=worlds/sala_projetada.sdf
   ./launch.sh --sim --world=/home/ubuntu/mundos/hangar.sdf
   ```

**Checklist do arquivo `.sdf` do mundo** (coisas que, se faltarem, fazem o robô cair ou o LiDAR atravessar paredes):

- `<physics>` definido (ex: `dart` ou `ode`)
- Plugins obrigatórios: `Physics`, `UserCommands`, `SceneBroadcaster`, `Sensors` com `render_engine=ogre2`
- Pelo menos uma `<light>` (sol) — senão a cena fica preta e o GPU LiDAR não vê nada
- Um `<model name="ground_plane">` estático — senão o robô despenca
- Todos os objetos com `<collision>` (paredes, móveis) — senão o LiDAR trespassa

O `worlds/empty.sdf` serve como template pronto de todos esses campos, olhe lá se estiver em dúvida.

### Rodando no modo SIM

```bash
# 1. Sim + teleop (dirige no Gazebo pelo teclado/UI web)
./launch.sh --sim

# 2. Sim + SLAM (mapeia a sala simulada com o slam_toolbox)
./launch.sh --sim --slam
#    Dirija o robô pelo Gazebo até o mapa no painel web ficar bom,
#    clique em "Salvar mapa" → fica em maps/sala.yaml

# 3. Sim + NAV2 (navegação autônoma por click-to-go dentro do Gazebo)
./launch.sh --sim --nav2
#    Clique num ponto do mapa web → o robô simulado vai até lá
```

Todas as flags combinam. `--sim --slam --world=worlds/minha_sala.sdf` também funciona.

### O robô simulado

O modelo fica em `~/ros2_ws/src/robot_nav/urdf/sim_robot.sdf` — um diff drive de 50×45×10 cm (mesmo tamanho do hoverboard real), rodas de 8,5 cm de raio, caster traseiro e um GPU LiDAR de 360° no topo. A SDF inclui três plugins Gazebo:

- `DiffDrive` — consome `/cmd_vel`, publica `/odom` e o TF `odom → base_link`
- `JointStatePublisher` — roda as rodas na visualização
- `PosePublisher` — snapshot da pose dos links

As dimensões batem com o URDF do hoverboard real de propósito: assim os parâmetros que você tunar no sim (velocidade do planner, inflation radius do costmap, footprint do Nav2) transferem razoavelmente para o robô real.

> **Atenção:** este modo é um scaffold pra você conseguir iterar no pipeline sem hardware. Ele não foi validado end-to-end ainda — espere pequenos ajustes nos parâmetros do `slam_toolbox` e do Nav2 no primeiro uso. Veja [Limitações conhecidas](#limitações-conhecidas).

---

## Pré-requisitos

- Ubuntu 22.04 (testado) ou 24.04
- ROS2 Humble ou Jazzy instalado e no PATH (testado em **Jazzy**)
- `xacro`: `sudo apt install ros-$ROS_DISTRO-xacro`
- `robot_state_publisher`: `sudo apt install ros-$ROS_DISTRO-robot-state-publisher`
- **SLAM**: `sudo apt install ros-$ROS_DISTRO-slam-toolbox`
- **Nav2** (qualquer modo, inclusive o collision_monitor do teleop):
  ```bash
  sudo apt install \
      ros-$ROS_DISTRO-nav2-bringup \
      ros-$ROS_DISTRO-nav2-collision-monitor \
      ros-$ROS_DISTRO-nav2-map-server \
      ros-$ROS_DISTRO-nav2-amcl
  ```
- **Modo SIM (Gazebo Harmonic)** — opcional, só se você for rodar `--sim`:
  ```bash
  sudo apt install \
      ros-$ROS_DISTRO-ros-gz \
      ros-$ROS_DISTRO-ros-gz-sim \
      ros-$ROS_DISTRO-ros-gz-bridge \
      ros-$ROS_DISTRO-ros-gz-interfaces
  ```
- Python 3.10+

---

## Configuração inicial (uma vez)

### 1. Workspace ROS2

**Nada disso está neste repositório.** O `~/ros2_ws/` é um workspace ROS2 **que você cria na máquina** e precisa popular manualmente. Só o `robot_nav` mora neste repo (em `ros2_packages/robot_nav/`), via symlink. Os outros pacotes são externos e precisam ser clonados antes do `colcon build`, senão a compilação falha:

| Pacote | Origem | Obrigatório? |
|--------|--------|--------------|
| `robot_nav` | este repo (symlink) | **sempre** |
| `wheel_msgs` | repo externo | **sempre** — o `robot_nav` declara `<depend>wheel_msgs</depend>`, então mesmo no sim o `colcon build` quebra sem ele |
| `ros2-hoverboard-driver` | repo externo | só no modo real (hardware) |
| `ldlidar_stl_ros2` | repo externo | só no modo real (hardware) |

```bash
# Cria a pasta do workspace e entra nela
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src

# 1) robot_nav — symlink do pacote deste repo
ln -s ~/Controle_robo_web/ros2_packages/robot_nav robot_nav

# 2) wheel_msgs — sempre obrigatório
git clone https://github.com/Richard-Haes-Ellis/wheel_msgs.git wheel_msgs

# 3) Só se for rodar no hardware real — pule estes dois se for só --sim
git clone https://github.com/victorfdezc/ros2-hoverboard-driver.git ros2-hoverboard-driver
git clone https://github.com/ldrobotSensorTeam/ldlidar_stl_ros2.git  ldlidar_stl_ros2

# Compila tudo de uma vez
cd ~/ros2_ws
colcon build
source install/setup.bash

# Adicione ao ~/.bashrc para não precisar fazer source toda vez:
echo "source ~/ros2_ws/install/setup.bash" >> ~/.bashrc
```

> **Se o `colcon build` falhar com `Package 'wheel_msgs' not found`**, é porque você pulou o passo 2. Clone o `wheel_msgs` em `~/ros2_ws/src/` e rode de novo.

Depois de editar qualquer arquivo em `ros2_packages/robot_nav/`, rode `colcon build --packages-select robot_nav` para reinstalar os launches/URDFs no `install/`.

### 2. Portas USB fixas (obrigatório)

O hoverboard e o LiDAR usam o mesmo chip USB-serial (CH340 ou similar), sem número de série. Por isso o Linux pode atribuir `/dev/ttyUSB0` e `/dev/ttyUSB1` em qualquer ordem a cada boot — causando o bug: **ao subir o LiDAR o robô para de andar**, ou vice-versa.

A solução é fixar cada dispositivo a um nome permanente usando a porta USB física:

```bash
# Com o hoverboard E o LiDAR plugados:
sudo ~/Controle_robo_web/setup_udev.sh
```

O script vai:
1. Pedir que você desplugue o LiDAR para identificar a porta do hoverboard
2. Pedir que você replugue o LiDAR para identificar a porta dele
3. Criar `/etc/udev/rules.d/99-robot-usb.rules` com os symlinks permanentes

Depois recompile o driver (necessário porque o `PORT` foi atualizado para `/dev/hoverboard`):

```bash
cd ~/ros2_ws
colcon build --packages-select ros2-hoverboard-driver
source install/setup.bash
```

Verifique se os symlinks estão corretos (devem apontar para portas **diferentes**):

```bash
ls -la /dev/hoverboard /dev/lidar
# Esperado:
# /dev/hoverboard -> ttyUSB0
# /dev/lidar      -> ttyUSB1
```

> **Atenção:** Se trocar o cabo de porta USB física (ex: plugar o hoverboard em outra entrada do notebook), rode `setup_udev.sh` novamente. Os symlinks são baseados na porta física, não no dispositivo.

### 3. Dependências Python

```bash
cd ~/Controle_robo_web/controle_web
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Como rodar

Todos os modos usam o mesmo `launch.sh` e a mesma interface web em `http://<IP>:5000`. O modo é passado como flag e propagado ao servidor web via a variável de ambiente `ROBOT_MODE` — a UI mostra um badge colorido (TELEOP / SLAM / NAV2) no topo e exibe ou esconde o painel de mapa conforme o modo.

Para descobrir o IP:

```bash
hostname -I
```

### Modo TELEOP (padrão)

Dirigir manualmente. Sobe o Nav2 Collision Monitor como camada de segurança.

```bash
cd ~/Controle_robo_web
./launch.sh
```

O script inicia, nesta ordem:

| # | Processo | Log |
|---|----------|-----|
| 1 | `ros2-hoverboard-driver` (porta `/dev/hoverboard`) | `logs/hoverboard_driver.log` |
| 2 | Nós do robô: `robot_state_publisher`, `odom_publisher`, `cmd_vel_to_wheels` | `logs/robot_nodes.log` |
| 3 | LiDAR FHL-LD20 (`ldlidar_stl_ros2`) + `obstacle_detector` | `logs/lidar.log`, `logs/obstacle_detector.log` |
| 4 | `nav2_collision_monitor` *(só segurança, não é a stack Nav2 completa)* | `logs/nav2_collision.log` |
| 5 | Servidor web Flask + Socket.IO em `http://0.0.0.0:5000` | terminal |

### Modo SLAM — mapear a sala

Primeira etapa do fluxo de navegação: você dirige o robô pela sala (com WASD, gamepad ou pad touch na UI), o `slam_toolbox` constrói o mapa em tempo real, e você salva com um clique quando terminar.

```bash
./launch.sh --slam
```

Troca o passo `[4/5]`: em vez do collision_monitor sobe o `slam_toolbox` em modo *mapping online async*. O painel **Mapa** da UI aparece automaticamente e vai mostrando o mapa crescendo à medida que você dirige.

**Como mapear bem:**
1. Comece com o robô parado no centro de onde você quer mapear.
2. Dirija **devagar** — o SLAM precisa de tempo para casar scans consecutivos. Velocidade alta quebra o matching.
3. Faça movimentos suaves, priorize retas longas e evite girar no mesmo lugar.
4. **Feche loops**: volte por onde já passou para o SLAM fechar laços e corrigir drift acumulado.
5. Evite ambientes muito simétricos (corredores longos com paredes lisas) — se o scan não tem features, o matching falha.

**Salvando o mapa:** Quando o mapa estiver bom, clique em **Salvar mapa** no canto do painel. Um prompt pede o nome (padrão: `sala`). O backend chama o `nav2_map_server/map_saver_cli`, que grava dois arquivos em `maps/`:

- `maps/sala.yaml` — metadados (resolução, origem, thresholds)
- `maps/sala.pgm` — imagem grayscale do occupancy grid

Esses arquivos ficam fora do git (`.gitignore`). Depois de salvar, você pode encerrar o SLAM (`Ctrl+C`) e rodar o modo NAV2.

### Modo NAV2 — navegação autônoma

Segunda etapa: usa um mapa já salvo pelo SLAM e ativa a stack Nav2 completa. Você clica num ponto do mapa na UI e o robô se localiza (AMCL), planeja uma rota (planner) e executa (controller) até chegar lá.

```bash
./launch.sh --nav2                           # usa maps/sala.yaml (padrão)
./launch.sh --nav2 --map=/caminho/outro.yaml # mapa customizado
```

No painel da UI:
- **Mapa** aparece com o mapa estático carregado.
- **Robô** aparece como seta laranja apontando para o yaw, atualizada a 10 Hz via TF `map→base_link`.
- **Click** no mapa publica `/goal_pose` (PoseStamped, frame `map`) que o `bt_navigator` consome.
- **Trajetória planejada** pelo Nav2 aparece como linha azul (escutando `/plan`).
- **Último alvo** aparece como bolinha vermelha.

Se o arquivo de mapa não existir, o `launch.sh` aborta com uma mensagem clara e sugere rodar `--slam` antes.

### Modo SIM — Gazebo sem hardware

Adicione `--sim` em qualquer um dos modos acima para rodar no Gazebo Harmonic em vez do hardware real. Veja a seção [Modo SIM](#modo-sim--testar-tudo-no-gazebo-sem-hardware) para detalhes completos, mas o resumo é:

```bash
./launch.sh --sim                              # sim + teleop
./launch.sh --sim --slam                       # sim + mapeamento
./launch.sh --sim --nav2                       # sim + navegação autônoma
./launch.sh --sim --world=worlds/sala.sdf      # sim com mundo customizado
```

**Seu arquivo de mundo** vai em `Controle_robo_web/worlds/` (padrão: `worlds/empty.sdf`, que já vem com uma sala 6×6m para teste inicial).

### Outras flags

```bash
./launch.sh --no-lidar              # Sobe sem LiDAR (só teleop, modos slam/nav2 exigem lidar)
./launch.sh --no-nav2               # Teleop sem collision_monitor
./launch.sh --lidar-port=/dev/lidar # Porta do LiDAR (padrão: /dev/lidar)
```

### Encerrar

`Ctrl+C` encerra todos os processos limpos. O `cleanup()` do script mata a árvore inteira de filhos (inclusive os nós spawnados pelo `ros2 launch`, que ficariam órfãos se só matasse o pai).

> **Por que tem um handler de SIGINT custom no `app.py`?** O `rclpy.init()` instala seus próprios handlers de SIGINT/SIGTERM que engolem o Ctrl+C — o processo Python fica preso esperando o executor do ROS2 que nunca acorda, e o bash em foreground nunca roda o `trap cleanup`. Por isso o `app.py` instala handlers Python que sobrescrevem os do rclpy: primeiro Ctrl+C faz shutdown limpo, segundo Ctrl+C força `os._exit(1)` imediato.

---

## Controles

### Teclado

| Tecla | Ação |
|-------|------|
| `W` / `↑` | Avançar |
| `S` / `↓` | Recuar |
| `A` / `←` | Girar esquerda |
| `D` / `→` | Girar direita |
| `Espaço` | Parar |

Combinações são suportadas (ex: `W + D` = frente + direita).

### Gamepad (PS4 / Xbox)

| Controle | Ação |
|----------|------|
| Analógico esquerdo | Movimento (linear + angular) |
| `X` (PS4) / `A` (Xbox) — segurado | Trava de emergência |
| `□` (PS4) / `X` (Xbox) | Reduz velocidade (0.8×) |
| `○` (PS4) / `B` (Xbox) | Aumenta velocidade (até 4×) |

### Velocidades

- Base: `0.3 m/s` linear, `0.5 rad/s` angular
- Multiplicador: `0.8×` a `4.0×` (controlado pelo gamepad ou interface web)

---

## Arquitetura

### Tópicos ROS2

| Tópico | Tipo | Produtor | Consumidor | Quando |
|--------|------|----------|------------|--------|
| `/cmd_vel` | `geometry_msgs/Twist` | servidor web (teleop) / `velocity_smoother` (nav2) | `cmd_vel_to_wheels` | sempre |
| `/wheel_vel_setpoints` | `wheel_msgs/WheelSpeeds` | `cmd_vel_to_wheels` | hoverboard driver | sempre |
| `/scan` | `sensor_msgs/LaserScan` | LiDAR driver | `obstacle_detector` / `slam_toolbox` / `amcl` | sempre |
| `/odom` | `nav_msgs/Odometry` | `odom_publisher` | `slam_toolbox` / `amcl` | sempre |
| `/obstacle_info` | `std_msgs/String` (JSON) | `obstacle_detector` | (monitoramento) | teleop |
| `/map` | `nav_msgs/OccupancyGrid` | `slam_toolbox` / `map_server` | `map_service.py` (ponte web) | slam, nav2 |
| `/goal_pose` | `geometry_msgs/PoseStamped` | `map_service.py` (click na UI) | `bt_navigator` | nav2 |
| `/plan` | `nav_msgs/Path` | `planner_server` | `map_service.py` (ponte web) | nav2 |

**TFs publicadas:**
- `base_link → base_laser`, `base_link → wheels` — static (URDF via `robot_state_publisher`)
- `odom → base_link` — dinâmica (`odom_publisher` a partir do feedback das rodas)
- `map → odom` — dinâmica, em SLAM pelo `slam_toolbox`, em NAV2 pelo `amcl`

### Ponte ROS2 ↔ Web para mapa e navegação

O arquivo `controle_web/map_service.py` contém uma classe `MapBridge` que roda dentro do servidor Flask como uma thread daemon com seu próprio executor ROS2. Isso é o que permite o mapa aparecer no navegador e os clicks virarem comandos Nav2.

**O que o MapBridge faz:**

| Responsabilidade | Como |
|------------------|------|
| Receber o mapa | Subscribe `/map` com QoS `TRANSIENT_LOCAL` (a mensagem é *latched*, sem essa durability o subscriber nunca recebe). Converte o `OccupancyGrid` em PNG grayscale com `numpy` + `Pillow` (−1 cinza, 0 branco, ≥50 preto), flipa verticalmente (ROS y sobe, PNG y desce), base64-encoda e emite `map_update` via Socket.IO com `{info, png_b64}` |
| Rastrear o robô | `tf2_ros.TransformListener` em polling a 10 Hz. Olha `map→base_link`, extrai x/y/yaw (yaw do quaternion via `atan2`), emite `robot_pose` via Socket.IO |
| Receber trajetória | Subscribe `/plan`, converte cada pose em `{x, y}`, emite `plan_update` via Socket.IO |
| Enviar goal | Publisher em `/goal_pose` (`PoseStamped`, frame `map`). Handler `nav_goal` do Socket.IO recebe `{x, y, yaw}` do click no canvas e publica — mas só em modo NAV2 (fora disso retorna erro) |
| Salvar mapa | Handler `save_map` chama `ros2 run nav2_map_server map_saver_cli -f maps/<nome> --ros-args -p map_subscribe_transient_local:=true` via subprocess. O `map_subscribe_transient_local:=true` é obrigatório porque o `/map` é latched |

**Rodar só em modo slam/nav2:** o `app.py` só instancia o `MapBridge` se `ROBOT_MODE in ('slam', 'nav2')` — no teleop não há `/map` pra subscribee, então o módulo nem sobe. Falha na inicialização do MapBridge não derruba o servidor (só loga um warning e desabilita o painel de mapa).

**Cliente (navegador):** o `static/js/map.js` escuta todos esses eventos, mantém estado local (`mapInfo`, `mapImage`, `robotPose`, `plan`, `lastGoal`) e redesenha o canvas a ~15 Hz. A conversão click→mundo usa `origin + resolution`:

```js
world_x = origin_x + px_in_img * resolution
world_y = origin_y + (height-1 - py_in_img) * resolution
```

Precisa inverter o eixo y porque o PNG foi flipado verticalmente antes de ser mandado.

### Detecção de obstáculos (modo TELEOP)

O `obstacle_detector` divide o campo de visão em 6 setores e classifica por distância:

| Cor | Distância |
|-----|-----------|
| Verde | > 1,5 m |
| Amarelo | 0,5 – 1,5 m |
| Vermelho | < 0,5 m |

Os dados são escritos em `/tmp/obstacle_current.json` e lidos pelo Flask a 5 Hz via thread separada (sem ROS2 dentro do Flask).

### Arquivos principais

```
Controle_robo_web/
├── launch.sh                          # Launcher principal (flags --slam / --nav2 / --map=)
├── setup_udev.sh                      # Configura portas USB fixas
├── maps/                              # Mapas salvos pelo SLAM (ignorado pelo git)
│   ├── sala.yaml                      # Metadados: resolução, origem, thresholds
│   └── sala.pgm                       # Grayscale do occupancy grid
├── worlds/                            # Mundos do Gazebo usados pelo --sim
│   └── empty.sdf                      # Mundo padrão (sala 6×6 m vazia)
├── ros2_packages/
│   └── robot_nav/                     # Pacote ROS2 (linkado em ~/ros2_ws/src/robot_nav)
│       ├── launch/                    # robot.launch.py, lidar, slam, nav2, sim, ...
│       ├── urdf/robot.urdf.xacro      # URDF do hoverboard real
│       ├── urdf/sim_robot.sdf         # SDF do robô simulado
│       ├── config/nav2_params.yaml
│       └── robot_nav/                 # Nodes Python (odom, cmd_vel_to_wheels, ...)
└── controle_web/
    ├── app.py                         # Servidor Flask + Socket.IO (lê ROBOT_MODE)
    ├── map_service.py                 # Ponte ROS2↔Web: /map, TF, /plan, /goal_pose
    ├── controllers/
    │   └── robot_controller.py        # ROS2Controller (publica /cmd_vel)
    ├── templates/index.html           # Interface web (badge de modo + painel de mapa)
    ├── static/
    │   ├── css/styles.css
    │   └── js/
    │       ├── client.js              # Teclado/gamepad → Socket.IO
    │       ├── gamepad.js             # Leitura do gamepad e visualização
    │       └── map.js                 # Canvas do mapa, render, click → goal
    └── logs/                          # Logs rotativos

~/ros2_ws/src/
├── robot_nav -> ~/Controle_robo_web/ros2_packages/robot_nav  # symlink
├── ros2-hoverboard-driver/                 # Driver C++ do hoverboard (repo separado)
│   └── include/.../config.hpp              # PORT = /dev/hoverboard
├── ldlidar_stl_ros2/                       # Driver do LiDAR FHL-LD20 (repo separado)
└── wheel_msgs/                             # Mensagens custom das rodas (repo separado)
```

---

## Logs

Todos os logs ficam em `controle_web/logs/`:

| Arquivo | Conteúdo |
|---------|----------|
| `hoverboard_driver.log` | Saída do driver C++ (serial, erros) |
| `robot_nodes.log` | robot_state_publisher, odom, cmd_vel_to_wheels |
| `lidar.log` | Driver LiDAR |
| `obstacle_detector.log` | Detecção de obstáculos |
| `nav2_collision.log` | Nav2 Collision Monitor (se ativo) |
| `movements.log` | Histórico de comandos em JSON Lines |
| `movements.txt` | Histórico legível em português |

Para acompanhar em tempo real:

```bash
tail -f controle_web/logs/hoverboard_driver.log
tail -f controle_web/logs/lidar.log
```

---

## Limitações conhecidas

Coisas que ainda não funcionam perfeitamente ou que exigem atenção ao usar SLAM/Nav2:

- **Click no mapa manda o robô com `yaw = 0`.** A UI só captura o ponto clicado, não a orientação final desejada. O `bt_navigator` aceita o goal, mas o robô chega apontando para o eixo X do mapa — não necessariamente a direção que você queria. *Mitigação futura:* capturar drag no canvas para definir yaw.
- **Contenção do `/cmd_vel` em modo NAV2.** Tanto o teleop (Socket.IO → `/cmd_vel`) quanto o `velocity_smoother` do Nav2 publicam no mesmo tópico. Se você mover o joystick durante uma navegação autônoma, os comandos se atropelam — o último mensagem vence. Na prática funciona como "override manual por cima do Nav2", mas não é um protocolo robusto. *Mitigação futura:* roteamento explícito via `twist_mux`.
- **Drift de odometria.** O `odom_publisher` integra o feedback das rodas do hoverboard. Em mapeamentos longos ou salas com piso escorregadio, o drift acumula e o SLAM fecha loops mal. Dirija devagar e volte por onde já passou para ajudar o `slam_toolbox` a corrigir.
- **Ambientes muito simétricos.** Corredor longo com paredes lisas, salas quadradas vazias: o scan-matching do SLAM não encontra features suficientes e o mapa pode dobrar sobre si mesmo. Prefira mapear ambientes com móveis, quinas e variação.
- **Bateria do hoverboard.** Sem bateria o driver até sobe, mas falha ao escrever na porta serial (`Error writing to hoverboard serial port`) — não é bug do código. Conecte a bateria antes de abrir um bug.
- **Pipeline não validado end-to-end em hardware.** A integração SLAM → salvar → Nav2 → click-to-go passou nos smoke tests (imports, subida de processos, SIGINT limpo), mas ainda não rodou na sala real com o LiDAR e o hoverboard conectados. Espere pequenos ajustes de tuning ao primeiro uso (parâmetros do `slam_toolbox`, `amcl` e dos planners).
- **Modo `--sim` é um scaffold, não foi executado ponta-a-ponta.** O `sim.launch.py`, o `sim_robot.sdf` e o `worlds/empty.sdf` compilam e carregam, mas a primeira execução real no Gazebo Harmonic pode pedir ajustes: frame do LiDAR (`gz_frame_id`), QoS do bridge, nomes de tópicos `gz.msgs.*` (que às vezes mudam entre releases). Se o `/scan` não aparecer no `ros2 topic list`, é quase certo algum desses três. *Mitigação:* testar incrementalmente — primeiro `./launch.sh --sim` só com teleop, depois `--sim --slam`, depois `--sim --nav2`.

---

## Solução de problemas

### Robô não anda quando o LiDAR está ligado (ou vice-versa)

Causa: os dois dispositivos caíram no mesmo `/dev/ttyUSBX`. Veja [Portas USB fixas](#2-portas-usb-fixas-obrigatório).

```bash
# Diagnóstico rápido:
ls -la /dev/hoverboard /dev/lidar
# Se apontarem para a mesma porta → rode setup_udev.sh novamente
```

### Porta /dev/hoverboard não encontrada

```bash
ls /dev/ttyUSB*
# Se nenhuma aparecer: verifique cabo USB e permissões
sudo usermod -aG dialout $USER  # adiciona usuário ao grupo serial
# Depois faça logout e login
```

### Driver do hoverboard falha ao abrir porta

```bash
# Verifique permissões:
ls -la /dev/hoverboard
# Deve ter MODE=0666 ou pertencer ao grupo dialout

# Force permissão temporária:
sudo chmod 666 /dev/hoverboard
```

### LiDAR não publica /scan

```bash
# Verifique se o nó está rodando:
ros2 node list | grep lidar

# Verifique se há dados no tópico:
ros2 topic hz /scan

# Veja o log:
tail -f controle_web/logs/lidar.log
```

### Nav2 não instalado (aviso no launch.sh)

```bash
sudo ./install_nav2.sh
```

Sem Nav2, o robô funciona normalmente — apenas sem parada automática por obstáculos.

### Painel de mapa não aparece na UI (modo SLAM ou NAV2)

Checklist:

1. Confirme que subiu no modo certo: o badge no topo da página deve mostrar `SLAM` ou `NAV2` (não `TELEOP`). Se estiver `TELEOP`, o `MapBridge` nem é instanciado.
2. Confirme que o `/map` está sendo publicado:
   ```bash
   ros2 topic echo /map --once
   ```
   Em SLAM pode demorar alguns segundos até o `slam_toolbox` publicar o primeiro mapa (ele espera acumular scans).
3. Olhe o log do servidor web no terminal: o `MapBridge` loga `[map] recebido /map (WxH)` quando o subscriber dispara. Se não aparecer, quase certo que o QoS está errado (`TRANSIENT_LOCAL` é obrigatório).
4. Em NAV2, se o `map_server` não sobe, o `/map` nunca aparece — veja `logs/nav2.log`.

### Salvar mapa falha com "no messages received"

Causa quase sempre é o `map_server`/`slam_toolbox` publicando o `/map` como *latched* (`TRANSIENT_LOCAL`), e o `map_saver_cli` tentando se inscrever com QoS default. O `MapBridge` já passa `-p map_subscribe_transient_local:=true`, mas se você rodar manualmente:

```bash
ros2 run nav2_map_server map_saver_cli -f maps/sala \
    --ros-args -p map_subscribe_transient_local:=true
```

### Nav2 rejeita o goal (TF timeout ou frame error)

```bash
# Confirme que a cadeia de TFs está completa:
ros2 run tf2_tools view_frames
# Esperado: map → odom → base_link → base_laser

# Se faltar map → odom: o AMCL não conseguiu localizar o robô.
#   Certifique-se de que o mapa carregado é o mesmo onde o robô está
#   e dê um "pose inicial" empurrando o robô um pouco com o teclado.

# Se faltar odom → base_link: odom_publisher não está rodando
#   (veja logs/robot_nodes.log).
```

### `rclpy` reclama de `Could not find a valid TF` no MapBridge

O `MapBridge` faz `lookup_transform('map', 'base_link', ...)` a 10 Hz. No começo, antes do AMCL/SLAM publicar `map → odom`, essas buscas falham e logam warnings — é esperado nos primeiros segundos. Se persistir, veja o item acima.
