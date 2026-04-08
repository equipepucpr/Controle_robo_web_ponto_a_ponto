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


class ROS2Controller(RobotController):
    """
    Controlador real que publica velocidades de rodas via ROS2.

    Tópico: /wheel_vel_setpoints
    Mensagem: wheel_msgs/msg/WheelSpeeds { left_wheel: float, right_wheel: float }

    Velocidades (m/s) configuráveis nas constantes abaixo.
    A fórmula de acionamento diferencial é:
        left_wheel  = velocidade_linear - componente_giro
        right_wheel = velocidade_linear + componente_giro

    Pré-requisito: ROS2 instalado e workspace com ros2-hoverboard-driver compilado.
    Execute antes de iniciar o servidor:
        source ~/ros2_ws/install/setup.bash
    """

    # Velocidade linear (unidade raw int16 do firmware do hoverboard, faixa útil: 0–1000).
    # O driver calcula: speed = (right + left) / 2  →  int16_t enviado pela serial.
    # Ajuste aqui conforme o comportamento real do seu robô.
    LINEAR_SPEED: float = 300.0
    # Componente de giro (mesmo range). Reduzido para curvas mais suaves.
    ANGULAR_SPEED: float = 200.0

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
        from rclpy.node import Node

        self.pressed: set = set()
        self._rclpy = rclpy

        if not rclpy.ok():
            rclpy.init()

        self._node: Node = rclpy.create_node('web_robot_controller')

        # Importa a mensagem gerada pelo pacote wheel_msgs
        from wheel_msgs.msg import WheelSpeeds
        self._WheelSpeeds = WheelSpeeds

        self._publisher = self._node.create_publisher(
            WheelSpeeds,
            '/wheel_vel_setpoints',
            qos_profile=10,
        )

        print("[ROS2Controller] Nó inicializado. Publicando em /wheel_vel_setpoints")

    def shutdown(self) -> None:
        """Encerra o nó ROS2 corretamente."""
        try:
            self._node.destroy_node()
            if self._rclpy.ok():
                self._rclpy.shutdown()
            print("[ROS2Controller] Nó encerrado.")
        except Exception as e:
            print(f"[ROS2Controller] Erro ao encerrar: {e}")

    def _publish(self, left: float, right: float) -> None:
        msg = self._WheelSpeeds()
        msg.left_wheel = float(left)
        msg.right_wheel = float(right)
        self._publisher.publish(msg)
        print(f"[ROS2Controller] Publicado → L={left:+.2f}  R={right:+.2f} m/s")

    def _compute_wheel_speeds(self) -> tuple:
        """
        Calcula velocidades das rodas com base nas teclas pressionadas.
        Suporta movimento composto (ex.: frente + direita ao mesmo tempo).
        """
        fwd = any(k in self.pressed for k in ('KeyW', 'ArrowUp'))
        bwd = any(k in self.pressed for k in ('KeyS', 'ArrowDown'))
        lft = any(k in self.pressed for k in ('KeyA', 'ArrowLeft'))
        rgt = any(k in self.pressed for k in ('KeyD', 'ArrowRight'))

        # Componente linear: +1 frente, -1 ré, 0 sem movimento linear
        linear = (1.0 if fwd else 0.0) - (1.0 if bwd else 0.0)
        # Componente angular: +1 direita, -1 esquerda
        angular = (1.0 if rgt else 0.0) - (1.0 if lft else 0.0)

        left  = linear * self.LINEAR_SPEED - angular * self.ANGULAR_SPEED
        right = linear * self.LINEAR_SPEED + angular * self.ANGULAR_SPEED

        return left, right

    def handle_key_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        etype  = event.get('type')
        code   = event.get('code') or event.get('key')
        repeat = event.get('repeat', False)

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
        left, right = self._compute_wheel_speeds()
        self._publish(left, right)

        action = 'start' if etype == 'down' else 'stop'
        return {'command': cmd, 'action': action, 'code': code}
