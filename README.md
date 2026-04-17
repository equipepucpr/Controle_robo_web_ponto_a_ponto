# Controle Web — Robô Ponto-a-Ponto (Mid-360 + FAST-LIO2)

Fork do projeto `Controle_robo_web` com foco diferente: sem SLAM, sem Nav2, sem Gazebo. O fluxo é:

1. **Pilota manualmente** (teclado / gamepad PS4) um robô hoverboard com um **Livox Mid-360** no topo.
2. Durante a pilotagem, **grava waypoints** clicando num botão na interface web — a pose vem do **FAST-LIO2** (LiDAR-Inertial Odometry).
3. **Reproduz o trajeto** automaticamente a partir da origem (ponto 0) ou faz o caminho reverso ("voltar ao 0").

Tudo sobe com um único comando (`./launch.sh`). Sem múltiplos terminais.

## Sumário

- [Como funciona](#como-funciona)
- [Hardware](#hardware)
- [Setup inicial (uma vez)](#setup-inicial-uma-vez)
- [Rodando](#rodando)
- [Interface web](#interface-web)
- [Fluxo gravar → reproduzir](#fluxo-gravar--reproduzir)
- [Arquitetura](#arquitetura)
- [Formato dos waypoints](#formato-dos-waypoints)
- [Troubleshooting](#troubleshooting)

---

## Como funciona

```
Mid-360 ─► livox_ros_driver2 ─► /livox/lidar + /livox/imu
                                     │
                                     ▼
                                 FAST-LIO2 ─► /Odometry  +  TF odom → base_link
                                     │
                                     ├─► waypoint_recorder ─► /waypoints (lista JSON)
                                     │         ↑ serviços: record / clear / reset_origin
                                     │
                                     └─► waypoint_follower ─► /cmd_vel
                                               ↑ serviços: start / stop / return_to_origin
                                               
  hoverboard ◄─── /wheel_vel_setpoints ◄─── cmd_vel_to_wheels ◄─── /cmd_vel
                                                                      ▲
                                                                      │
  Browser ◄── Socket.IO ── Flask app.py ── WaypointBridge ── serviços ROS2
                                              │
                                              └─► /cmd_vel (teleop manual WASD/PS4)
```

- **Origem (0, 0, 0)**: pose atual do LIO no momento em que você clica "Resetar origem". A partir daí, todas as coordenadas gravadas são relativas.
- **Voltar ao 0 = trajeto reverso** (N → 1 → origem), não linha reta.
- **Play termina no último waypoint** — não volta sozinho, use "Voltar ao 0".
- **Teleop e follower publicam no mesmo `/cmd_vel`**. Quando o follower está ativo, o browser bloqueia teclado e gamepad automaticamente pra não brigar.

## Hardware

- Robô hoverboard controlado via `ros2-hoverboard-driver` (USB, `/dev/hoverboard`).
- **Livox Mid-360** no topo, conectado via **Ethernet** (não USB).
  - IP de fábrica do Mid-360 costuma ser `192.168.1.12x`.
  - A placa de rede do host precisa estar em `192.168.1.5/24` (ou o que você configurar no `mid360_config.json`).
- PC com Ubuntu 24.04 + ROS2 Jazzy.

## Setup inicial (uma vez)

### 1. Instalar ROS2 Jazzy

Siga o guia oficial: https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html

```bash
source /opt/ros/jazzy/setup.bash
echo "source /opt/ros/jazzy/setup.bash" >> ~/.bashrc
```

### 2. Clonar o repo

```bash
git clone <url-do-repo> ~/Controle_robo_web_ponto_a_ponto
cd ~/Controle_robo_web_ponto_a_ponto
```

### 3. Rodar o setup

```bash
./setup.sh
```

O script é idempotente e cobre:

- **apt**: `xacro`, `robot_state_publisher`, `pcl`, `eigen`, `tf2`, compiladores.
- **Livox-SDK2**: clona em `~/Livox-SDK2`, compila e instala (dependência nativa do driver Livox).
- **Workspace em `~/ros2_ws/src`**:
  - symlink de `robot_nav` para este repo.
  - clone de `wheel_msgs` (mensagens de velocidade das rodas).
  - clone de [Livox-SDK/livox_ros_driver2](https://github.com/Livox-SDK/livox_ros_driver2).
  - clone de [hku-mars/FAST_LIO](https://github.com/hku-mars/FAST_LIO).
- **`colcon build --symlink-install`** em `~/ros2_ws`.
- **`controle_web/.venv`** com as deps Python (flask, socketio, numpy).

Se for rodar no robô real, descomente no `setup.sh` a linha que clona `ros2-hoverboard-driver`.

### 4. (Só hardware real) Fixar porta USB do hoverboard

```bash
sudo ./setup_udev.sh
```

Cria `/dev/hoverboard` estável. O Mid-360 é Ethernet — não precisa de udev.

### 5. Ajustar IPs do Mid-360

Edite `ros2_packages/robot_nav/config/mid360_config.json` se o IP do seu Mid-360 ou o da sua placa de rede host forem diferentes dos padrões (`192.168.1.12x` / `192.168.1.5`).

Configure a interface de rede local:

```bash
sudo ip addr add 192.168.1.5/24 dev <sua-iface-ethernet>
```

(Torne permanente em `netplan` se for usar sempre.)

## Rodando

```bash
cd ~/Controle_robo_web_ponto_a_ponto
./launch.sh
```

Isso sobe **em um único terminal**:

1. Driver do hoverboard (USB).
2. `play.launch.py`:
   - `robot_state_publisher` (URDF).
   - `odom_publisher` (odometria das rodas em `/wheel_odom`, **sem publicar TF**).
   - `cmd_vel_to_wheels` (converte `/cmd_vel` em setpoints das rodas).
   - `livox_ros_driver2` (Mid-360 → PointCloud2 + IMU).
   - FAST-LIO2 + TFs estáticos (`odom → camera_init`, `body → base_link`).
   - `waypoint_recorder`, `waypoint_follower`.
3. Servidor Flask em `http://0.0.0.0:5000`.

Ctrl+C encerra tudo.

### Flags

| Flag | Quando usar |
|---|---|
| `--no-hoverboard` | Testar a stack lógica sem a base física conectada |
| `--no-lidar` | Testar só a web sem o Mid-360 (sem pose) |

## Interface web

Abra `http://<ip-do-pc>:5000` no browser.

- **Badge "pose ok / sem pose"**: indica se o FAST-LIO2 está publicando `/Odometry`.
- **Badge do follower**: `IDLE` / `FORWARD` / `REVERSE` / `STOPPED`.
- **Pose**: x, y em metros; θ em graus (relativo à origem gravada).
- **Canvas**: mostra a origem (círculo verde), os waypoints numerados (azul) e a pose atual do robô (triângulo amarelo). Auto-escala pra caber tudo.

### Botões

| Botão | Efeito |
|---|---|
| Resetar origem (0) | Marca a pose atual do LIO como novo ponto (0,0,0) |
| ● Salvar ponto | Grava a pose atual como próximo waypoint |
| Limpar pontos | Apaga todos os waypoints gravados |
| ▶ Iniciar trajeto | Reproduz 1 → N e para no último ponto |
| ⟲ Voltar ao 0 | Reproduz N → 1 → origem (trajeto reverso) |
| ■ Parar | Para imediatamente o follower (zera `/cmd_vel`) |

### Controles manuais

- **Teclado**: WASD ou setas. Espaço = stop.
- **Gamepad PS4**: analógico esquerdo = mover; X = trava de emergência; □ = boost; ○ = ajuste fino.
- **Slider de velocidade** no topo, compartilhado entre teclado e gamepad.

Enquanto o follower está ativo (FORWARD/REVERSE), teclado e gamepad ficam **bloqueados**.

## Fluxo gravar → reproduzir

1. Liga robô + PC. Mid-360 já plugado na rede.
2. `./launch.sh`. Espera o terminal mostrar `Web em http://0.0.0.0:5000`.
3. Abre browser. Badge deve estar `pose ok` em poucos segundos.
4. Clica **Resetar origem**. Confirma que pose = (0, 0, 0°).
5. Pilota até o primeiro ponto. Clica **● Salvar ponto**. Waypoint aparece no canvas.
6. Repete até ter N pontos.
7. Pilota de volta à origem manualmente (ou clica **⟲ Voltar ao 0** pra voltar autônomo).
8. Clica **▶ Iniciar trajeto**. Teclado bloqueia, robô percorre 1→N, para no último.
9. Pronto. Pode clicar **⟲ Voltar ao 0** pra retornar autônomo, ou pilotar manualmente.

Os waypoints ficam salvos em `controle_web/waypoints/current.json` e persistem entre runs — se subir de novo, a lista volta.

## Arquitetura

### Nós ROS2 (pacote `robot_nav`)

| Nó | Função | Tópicos/Serviços principais |
|---|---|---|
| `odom_publisher` | Odometria das rodas (fallback humano) | pub `/wheel_odom` |
| `cmd_vel_to_wheels` | Traduz `/cmd_vel` pra setpoints L/R | sub `/cmd_vel`, pub `/wheel_vel_setpoints` |
| `waypoint_recorder` | Grava pontos a partir de `/Odometry` | sub `/Odometry`, pub `/waypoints`, srv `record_waypoint`, `clear_waypoints`, `reset_origin` |
| `waypoint_follower` | Pure-pursuit simples (heading-first) | sub `/Odometry`, `/waypoints`; pub `/cmd_vel`, `/follower_status`; srv `start`, `stop`, `return_to_origin` |

### TF tree

```
odom ──(static identity)──► camera_init ──(FAST-LIO2 dinâmico)──► body
body ──(static offset mount)──► base_link ──(URDF)──► {wheels, livox_frame}
```

Só o FAST-LIO2 mexe no TF dinâmico. O `odom_publisher` roda com `publish_tf:=False` pra não conflitar.

### Web (controle_web/)

- `app.py`: servidor Flask + Socket.IO. Handlers de teleop + handlers de waypoints.
- `controllers/robot_controller.py`: publica `/cmd_vel` do teleop (herança do projeto original).
- `controllers/waypoint_bridge.py`: nó ROS2 `web_waypoint_bridge` num executor separado. Escuta `/Odometry`, `/waypoints`, `/follower_status` e emite via Socket.IO. Chama os 6 serviços dos nós via `rclpy` client.
- `static/js/waypoints.js`: canvas 2D + amarração dos botões.

## Formato dos waypoints

`controle_web/waypoints/current.json`:

```json
{
  "version": 1,
  "updated": "2026-04-17T13:40:00Z",
  "origin_offset": { "x": 1.23, "y": -0.05, "yaw": 0.01 },
  "waypoints": [
    { "id": 1, "x": 1.42, "y": 0.03, "yaw": 0.01, "ts": 1713275410.3 },
    { "id": 2, "x": 2.85, "y": 0.50, "yaw": 0.35, "ts": 1713275422.7 }
  ]
}
```

`origin_offset` é a pose absoluta do LIO (no frame `odom`) que corresponde ao ponto (0,0,0) da gravação. Os `waypoints[].x/y/yaw` são **já no frame da origem** (i.e., a pose do LIO com o offset inverso aplicado). Origem (0,0,0) é implícita — nunca aparece na lista.

## Troubleshooting

**`pose sem sinal` e nunca aparece**
- Confirma que o Mid-360 está ligado e acessível: `ping 192.168.1.12x`.
- `ros2 topic list | grep -E 'livox|Odometry'` dentro do `launch.sh` deve listar os tópicos.
- Veja `controle_web/logs/play.log` pra erros do FAST-LIO2.

**`▶ Iniciar` responde "lista vazia"**
- Nenhum waypoint gravado. Clique em `● Salvar ponto` pelo menos uma vez.

**Follower para sozinho no meio do trajeto**
- Pose timeout (>1.5s sem `/Odometry`). Normalmente o cabo Ethernet do Mid-360 caiu, ou o FAST-LIO2 divergiu. Badge fica `STOPPED`.

**Robô "anda em círculo" em vez de ir pro waypoint**
- Ganhos do pure-pursuit muito altos/baixos. Edite em `ros2_packages/robot_nav/robot_nav/waypoint_follower.py`: `linear_speed`, `kp_angular`, `goal_tolerance`.

**Drift do LIO em trajetos longos**
- FAST-LIO2 não faz loop closure. Para trajetos repetitivos em ambiente pequeno, é aceitável. Se virar problema, considere `FAST-LIO-SAM` ou gravar mapa offline.
