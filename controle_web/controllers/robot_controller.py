from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

# Este módulo define a interface do controlador do robô,
# uma implementação de echo (EchoController) para testes sem robô,
# e o controlador real (ROS2Controller) que publica no tópico ROS2.

class RobotController(ABC):
    @abstractmethod
    def handle_key_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Processa um evento de teclado vindo do cliente remoto.
        Exemplo de evento:
        {
            'type': 'down' | 'up',
            'key': 'ArrowUp' | 'KeyW' | ...,
            'code': 'ArrowUp' | 'KeyW' | ...,
            'repeat': bool,
        }

        Deve retornar um dicionário opcional com a forma:
        { 'command': 'forward'|'backward'|'left'|'right'|'stop', 'action': 'start'|'stop', 'code': 'KeyW' }
        """
        raise NotImplementedError

    def handle_gamepad_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Processa um evento de gamepad (controle PS4/Xbox) com valores analógicos.
        Exemplo de evento:
        {
            'type': 'axis',
            'linear': float,    # -1.0 (ré) a 1.0 (frente) — eixo Y do stick esquerdo
            'angular': float,   # -1.0 (esquerda) a 1.0 (direita) — eixo X do stick esquerdo
        }
        ou:
        {
            'type': 'button',
            'button': str,      # nome do botão (ex: 'cross', 'circle', 'l2', 'r2')
            'value': float,     # 0.0 a 1.0 para triggers, 0 ou 1 para botões digitais
            'pressed': bool,
        }

        Retorna um dicionário com:
        { 'command': str, 'action': str, 'linear': float, 'angular': float, 'left_speed': float, 'right_speed': float }
        """
        return None


class EchoController(RobotController):
    def __init__(self) -> None:
        # Conjunto de teclas atualmente pressionadas (controle simples de estado)
        self.pressed = set()

    def handle_key_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        etype = event.get('type')
        code = event.get('code') or event.get('key')
        repeat = event.get('repeat', False)

        if etype == 'down' and not repeat:
            self.pressed.add(code)
        elif etype == 'up':
            self.pressed.discard(code)

        mapping = {
            'KeyW': 'forward', 'KeyS': 'backward',
            'KeyA': 'left',    'KeyD': 'right',
            'Space': 'stop',
            'ArrowUp': 'forward',   'ArrowDown': 'backward',
            'ArrowLeft': 'left',    'ArrowRight': 'right',
        }

        cmd = mapping.get(code)
        if cmd:
            action = 'start' if etype == 'down' else 'stop'
            print(f"[EchoController] {action} {cmd} (code={code})")
            return {'command': cmd, 'action': action, 'code': code}
        else:
            print(f"[EchoController] {etype} {code}")
            return None

    def handle_gamepad_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        etype = event.get('type')
        if etype == 'axis':
            linear = float(event.get('linear', 0))
            angular = float(event.get('angular', 0))
            if abs(linear) < 0.05 and abs(angular) < 0.05:
                cmd = 'stop'
            elif abs(linear) >= abs(angular):
                cmd = 'forward' if linear > 0 else 'backward'
            else:
                cmd = 'right' if angular > 0 else 'left'
            action = 'stop' if cmd == 'stop' else 'start'
            print(f"[EchoController] gamepad {action} {cmd} (L={linear:.2f} A={angular:.2f})")
            return {'command': cmd, 'action': action, 'linear': linear, 'angular': angular,
                    'left_speed': 0, 'right_speed': 0}
        elif etype == 'button':
            btn = event.get('button', '')
            pressed = event.get('pressed', False)
            print(f"[EchoController] gamepad button {btn} {'pressed' if pressed else 'released'}")
            if btn == 'cross' and pressed:
                return {'command': 'stop', 'action': 'stop', 'linear': 0, 'angular': 0,
                        'left_speed': 0, 'right_speed': 0}
        return None


class ROS2Controller(RobotController):
    """
    Controlador real que publica diretamente em /wheel_vel_setpoints
    (wheel_msgs/WheelSpeeds) pro driver do hoverboard. Também replica em
    /cmd_vel (geometry_msgs/Twist) para consumidores Nav2 / waypoint follower.

    A conversão cmd_vel → wheel_setpoints é feita inline aqui — não depende
    mais do nó externo cmd_vel_to_wheels.

    Arbitragem /cmd_vel:
      - Teleop ativo (tecla segurada / stick fora da dead zone): publica
        teleop em /cmd_vel E escreve nas rodas a 50 Hz.
      - Teleop idle: inscreve /cmd_vel (pegando o que o waypoint_follower
        publica) e encaminha pras rodas a 50 Hz — sem republicar /cmd_vel
        pra não lutar com o follower.
      - Chave geral (X segurado): força 0,0 nas rodas e chama
        /waypoint_follower/stop pra abortar qualquer trajeto em andamento.
    """

    # Tempo máximo (s) que um /cmd_vel externo é considerado válido pra forward.
    EXT_CMD_VEL_TIMEOUT: float = 0.5

    # Velocidades base em unidades SI.
    # Multiplicador de velocidade escala esses valores (0.5x–4.0x).
    BASE_LINEAR_SPEED: float = 0.3   # m/s
    BASE_ANGULAR_SPEED: float = 0.5  # rad/s

    SPEED_MULT_MIN: float = 0.8
    SPEED_MULT_MAX: float = 4.0

    # Conversão SI → unidades do driver do hoverboard.
    # right = linear * LINEAR_SCALE + angular * ANGULAR_SCALE
    # left  = linear * LINEAR_SCALE - angular * ANGULAR_SCALE
    LINEAR_SCALE: float = 400.0
    ANGULAR_SCALE: float = 150.0
    MAX_OUTPUT: float = 1000.0

    # Mapeamento tecla → direção semântica
    _KEY_MAP: Dict[str, str] = {
        'KeyW': 'forward',    'ArrowUp': 'forward',
        'KeyS': 'backward',   'ArrowDown': 'backward',
        'KeyA': 'left',       'ArrowLeft': 'left',
        'KeyD': 'right',      'ArrowRight': 'right',
        'Space': 'stop',
    }

    def __init__(self) -> None:
        import rclpy
        import time
        import threading
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node

        self.pressed: set = set()
        self._emergency_stop: bool = False
        self._speed_multiplier: float = 1.0
        self._last_gamepad_linear: float = 0.0
        self._last_gamepad_angular: float = 0.0
        self._rclpy = rclpy
        self._time = time

        if not rclpy.ok():
            rclpy.init()

        self._node: Node = rclpy.create_node('web_robot_controller')

        from geometry_msgs.msg import Twist
        from wheel_msgs.msg import WheelSpeeds
        from std_srvs.srv import Trigger
        self._Twist = Twist
        self._WheelSpeeds = WheelSpeeds
        self._Trigger = Trigger

        self._publisher = self._node.create_publisher(Twist, '/cmd_vel', qos_profile=10)
        self._wheels_pub = self._node.create_publisher(
            WheelSpeeds, '/wheel_vel_setpoints', qos_profile=10
        )

        # Republica último setpoint a 50 Hz em thread dedicada — substitui o
        # republish que o nav2_collision_monitor fazia na arquitetura anterior.
        # Sem isso, o driver do hoverboard desarma os motores (watchdog).
        self._last_linear: float = 0.0
        self._last_angular: float = 0.0

        # Estado de /cmd_vel externo (ex.: waypoint_follower) pra forward às rodas.
        self._ext_linear: float = 0.0
        self._ext_angular: float = 0.0
        self._ext_ts: float = 0.0

        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Subscription em /cmd_vel pra capturar comandos de outros nós
        # (waypoint_follower) quando teleop estiver idle.
        self._node.create_subscription(
            Twist, '/cmd_vel', self._on_external_cmd_vel, 10
        )

        # Cliente do serviço de parada do follower — chamado pelo botão X.
        self._cli_follower_stop = self._node.create_client(
            Trigger, '/waypoint_follower/stop'
        )

        # Executor próprio pra processar a subscription sem bloquear o Flask.
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(
            target=self._spin_loop, daemon=True, name='robot_ctl_spin'
        )
        self._spin_thread.start()

        self._pub_thread = threading.Thread(
            target=self._republish_loop, daemon=True, name='cmd_vel_republish'
        )
        self._pub_thread.start()

        print("[ROS2Controller] Nó inicializado. Publicando em /cmd_vel e /wheel_vel_setpoints @ 50 Hz")

    def shutdown(self) -> None:
        """Encerra o nó ROS2 corretamente."""
        try:
            self._stop_event.set()
            if self._pub_thread.is_alive():
                self._pub_thread.join(timeout=1.0)
            try:
                self._executor.shutdown()
            except Exception:
                pass
            self._node.destroy_node()
            if self._rclpy.ok():
                self._rclpy.shutdown()
            print("[ROS2Controller] Nó encerrado.")
        except Exception as e:
            print(f"[ROS2Controller] Erro ao encerrar: {e}")

    def _spin_loop(self) -> None:
        while not self._stop_event.is_set() and self._rclpy.ok():
            try:
                self._executor.spin_once(timeout_sec=0.1)
            except Exception:
                break

    def _is_teleop_active(self) -> bool:
        """True se há tecla pressionada ou stick fora da dead zone."""
        if self.pressed:
            return True
        if abs(self._last_gamepad_linear) > 0.01 or abs(self._last_gamepad_angular) > 0.01:
            return True
        return False

    def _on_external_cmd_vel(self, msg) -> None:
        """Recebe /cmd_vel de outros publishers (ex.: waypoint_follower).

        Só aceita quando teleop estiver idle — evita que o follower lute
        com o usuário apertando teclas, e evita feedback loop com nossos
        próprios publishes de teleop.
        """
        if self._emergency_stop or self._is_teleop_active():
            return
        with self._lock:
            self._ext_linear = float(msg.linear.x)
            self._ext_angular = float(msg.angular.z)
            self._ext_ts = self._time.monotonic()

    def _call_follower_stop(self) -> None:
        """Dispara /waypoint_follower/stop de forma não-bloqueante."""
        if not self._cli_follower_stop.service_is_ready():
            print("[ROS2Controller] /waypoint_follower/stop indisponível — pulando")
            return
        try:
            self._cli_follower_stop.call_async(self._Trigger.Request())
            print("[ROS2Controller] /waypoint_follower/stop acionado (chave geral)")
        except Exception as e:
            print(f"[ROS2Controller] Falha ao chamar follower stop: {e}")

    def _compute_wheels(self, linear: float, angular: float) -> tuple:
        """
        Converte (linear m/s, angular rad/s) em (left_wheel_field, right_wheel_field)
        em unidades do driver do hoverboard, com clamp em MAX_OUTPUT.

        Os fios do hoverboard estão invertidos: o campo left_wheel dirige a roda
        direita e vice-versa — fazemos o swap aqui pra preservar a convenção ROS
        (angular.z > 0 = girar à esquerda).
        """
        right = linear * self.LINEAR_SCALE + angular * self.ANGULAR_SCALE
        left = linear * self.LINEAR_SCALE - angular * self.ANGULAR_SCALE

        right = max(-self.MAX_OUTPUT, min(self.MAX_OUTPUT, right))
        left = max(-self.MAX_OUTPUT, min(self.MAX_OUTPUT, left))

        return float(right), float(left)  # (left_wheel_field, right_wheel_field)

    def _publish_wheels(self, linear: float, angular: float) -> None:
        left_field, right_field = self._compute_wheels(linear, angular)
        wmsg = self._WheelSpeeds()
        wmsg.left_wheel = left_field
        wmsg.right_wheel = right_field
        self._wheels_pub.publish(wmsg)

    def _republish_loop(self) -> None:
        import time
        period = 0.02  # 50 Hz — replica o comportamento do nav2_collision_monitor
        while not self._stop_event.is_set():
            try:
                if self._emergency_stop:
                    # Chave geral: força 0,0 nas rodas e no /cmd_vel. O driver
                    # precisa desse heartbeat pra não sair do modo armado.
                    self._publish_wheels(0.0, 0.0)
                    tmsg = self._Twist()
                    self._publisher.publish(tmsg)
                elif self._is_teleop_active():
                    # Teleop dirigindo — publica estado do teleop em ambos.
                    with self._lock:
                        linear = self._last_linear
                        angular = self._last_angular
                    tmsg = self._Twist()
                    tmsg.linear.x = linear
                    tmsg.angular.z = angular
                    self._publisher.publish(tmsg)
                    self._publish_wheels(linear, angular)
                else:
                    # Idle: encaminha último /cmd_vel externo (follower) pras
                    # rodas. NÃO republica em /cmd_vel pra não lutar com o
                    # publisher original.
                    with self._lock:
                        age = time.monotonic() - self._ext_ts
                        if age <= self.EXT_CMD_VEL_TIMEOUT and self._ext_ts > 0:
                            linear = self._ext_linear
                            angular = self._ext_angular
                        else:
                            linear = 0.0
                            angular = 0.0
                    self._publish_wheels(linear, angular)
            except Exception:
                break
            time.sleep(period)

    def _publish(self, linear: float, angular: float) -> None:
        with self._lock:
            self._last_linear = float(linear)
            self._last_angular = float(angular)
        msg = self._Twist()
        msg.linear.x = float(linear)
        msg.angular.z = float(angular)
        self._publisher.publish(msg)
        self._publish_wheels(float(linear), float(angular))
        print(f"[ROS2Controller] cmd_vel → linear={linear:+.3f} m/s  angular={angular:+.3f} rad/s")

    @property
    def _linear_speed(self) -> float:
        return self.BASE_LINEAR_SPEED * self._speed_multiplier

    @property
    def _angular_speed(self) -> float:
        return self.BASE_ANGULAR_SPEED * self._speed_multiplier

    def set_speed_multiplier(self, mult: float) -> float:
        """Define o multiplicador de velocidade e republica imediatamente."""
        self._speed_multiplier = max(self.SPEED_MULT_MIN, min(self.SPEED_MULT_MAX, mult))
        print(f"[ROS2Controller] Multiplicador de velocidade: {self._speed_multiplier:.2f}x "
              f"(linear={self._linear_speed:.0f}, angular={self._angular_speed:.0f})")

        # Republica com a velocidade nova se estiver em movimento
        if not self._emergency_stop:
            if self.pressed:
                # Modo teclado — recalcula com teclas pressionadas
                linear, angular = self._compute_cmd_vel()
                self._publish(linear, angular)
            elif abs(self._last_gamepad_linear) > 0.01 or abs(self._last_gamepad_angular) > 0.01:
                # Modo gamepad — recalcula com último eixo
                linear = self._last_gamepad_linear * self._linear_speed
                angular = -self._last_gamepad_angular * self._angular_speed
                self._publish(linear, angular)

        return self._speed_multiplier

    def _compute_cmd_vel(self) -> tuple:
        """
        Calcula linear (m/s) e angular (rad/s) com base nas teclas pressionadas.
        Suporta movimento composto (ex.: frente + direita ao mesmo tempo).
        Retorna (linear, angular) para publicar em /cmd_vel.
        """
        fwd = any(k in self.pressed for k in ('KeyW', 'ArrowUp'))
        bwd = any(k in self.pressed for k in ('KeyS', 'ArrowDown'))
        lft = any(k in self.pressed for k in ('KeyA', 'ArrowLeft'))
        rgt = any(k in self.pressed for k in ('KeyD', 'ArrowRight'))

        # +1 frente, -1 ré
        lin = (1.0 if fwd else 0.0) - (1.0 if bwd else 0.0)
        # +1 esquerda, -1 direita (convenção ROS: anti-horário positivo)
        ang = (1.0 if lft else 0.0) - (1.0 if rgt else 0.0)

        return lin * self._linear_speed, ang * self._angular_speed

    def handle_key_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        etype  = event.get('type')
        code   = event.get('code') or event.get('key')
        repeat = event.get('repeat', False)

        # Trava de emergência ativa — ignora tudo e mantém parado
        if self._emergency_stop:
            self._publish(0.0, 0.0)
            return {'command': 'stop', 'action': 'stop', 'code': code}

        cmd = self._KEY_MAP.get(code)
        if not cmd:
            # Tecla sem mapeamento — ignora
            return None

        # Atualiza conjunto de teclas pressionadas
        if etype == 'down' and not repeat:
            if cmd == 'stop':
                self.pressed.clear()
            else:
                self.pressed.add(code)
        elif etype == 'up':
            self.pressed.discard(code)

        # Calcula e publica velocidades resultantes
        linear, angular = self._compute_cmd_vel()
        self._publish(linear, angular)

        action = 'start' if etype == 'down' else 'stop'
        return {'command': cmd, 'action': action, 'code': code}

    def handle_gamepad_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        etype = event.get('type')

        if etype == 'button':
            btn = event.get('button', '')
            is_pressed = event.get('pressed', False)
            # Cross (X) = CHAVE GERAL: enquanto segurado, nada se move + aborta
            # qualquer trajeto do waypoint_follower em andamento.
            if btn == 'cross':
                self._emergency_stop = is_pressed
                if is_pressed:
                    self.pressed.clear()
                    self._last_gamepad_linear = 0.0
                    self._last_gamepad_angular = 0.0
                    # Limpa /cmd_vel externo pra não vazar comando stale após soltar
                    with self._lock:
                        self._ext_linear = 0.0
                        self._ext_angular = 0.0
                        self._ext_ts = 0.0
                    self._publish(0.0, 0.0)
                    self._call_follower_stop()
                    print("[ROS2Controller] CHAVE GERAL ATIVADA (X) — follower abortado")
                else:
                    self._publish(0.0, 0.0)
                    print("[ROS2Controller] Chave geral liberada")
                return {'command': 'stop', 'action': 'stop', 'linear': 0, 'angular': 0,
                        'left_speed': 0, 'right_speed': 0, 'emergency': is_pressed}
            # Square / Circle = controle de velocidade (tratado no cliente via set_speed)
            return None

        if etype == 'axis':
            # Trava ativa — ignora joystick e mantém parado
            if self._emergency_stop:
                self._publish(0.0, 0.0)
                return {'command': 'stop', 'action': 'stop', 'linear': 0, 'angular': 0,
                        'left_speed': 0, 'right_speed': 0, 'emergency': True}

            gp_linear = float(event.get('linear', 0))
            gp_angular = float(event.get('angular', 0))

            # Aplica dead zone
            if abs(gp_linear) < 0.05:
                gp_linear = 0.0
            if abs(gp_angular) < 0.05:
                gp_angular = 0.0

            # Salva para republicação instantânea ao mudar velocidade
            self._last_gamepad_linear = gp_linear
            self._last_gamepad_angular = gp_angular

            # Converte joystick para m/s e rad/s (angular: direita positiva no gamepad = negativo no ROS)
            linear = gp_linear * self._linear_speed
            angular = -gp_angular * self._angular_speed
            self._publish(linear, angular)

            # Determina comando semântico para log
            if abs(gp_linear) < 0.05 and abs(gp_angular) < 0.05:
                cmd = 'stop'
            elif abs(gp_linear) >= abs(gp_angular):
                cmd = 'forward' if gp_linear > 0 else 'backward'
            else:
                cmd = 'right' if gp_angular > 0 else 'left'

            action = 'stop' if cmd == 'stop' else 'start'
            return {'command': cmd, 'action': action, 'linear': linear, 'angular': angular,
                    'left_speed': 0, 'right_speed': 0}

        return None
