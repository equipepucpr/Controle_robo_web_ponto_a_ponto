#!/usr/bin/env python3
"""
Nó ROS2 que controla um relé via Arduino (serial USB).

Protocolo serial:
  '1' → ativa relé   (Arduino seta pino HIGH)
  '0' → desativa relé (Arduino seta pino LOW)

Serviço:
  ~/pulse (std_srvs/Trigger)
    Ativa o relé por `pulse_duration` segundos e depois desativa.

Parâmetros:
  serial_port      (str)   — default '/dev/ttyUSB1'
  baud_rate        (int)   — default 9600
  pulse_duration   (float) — default 1.0 s
"""

import threading
import time

import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger

try:
    import serial
except ImportError:
    serial = None


class RelayController(Node):

    def __init__(self):
        super().__init__('relay_controller')

        self.declare_parameter('serial_port', '/dev/ttyUSB1')
        self.declare_parameter('baud_rate', 9600)
        self.declare_parameter('pulse_duration', 1.0)

        port = self.get_parameter('serial_port').value
        baud = int(self.get_parameter('baud_rate').value)

        self._serial = None
        self._serial_lock = threading.Lock()

        if serial is None:
            self.get_logger().warn(
                'pyserial não instalado — relay_controller operando em modo simulado. '
                'Instale com: pip install pyserial'
            )
        else:
            try:
                self._serial = serial.Serial(port, baud, timeout=1)
                time.sleep(2.0)  # espera reset do Arduino
                self.get_logger().info(f'Relay serial aberto: {port} @ {baud}')
            except Exception as e:
                self._serial = None
                self.get_logger().warn(
                    f'Falha ao abrir serial {port}: {e} — operando em modo simulado'
                )

        self.create_service(Trigger, '~/pulse', self._on_pulse)
        self.get_logger().info('relay_controller pronto')

    def _on_pulse(self, request, response):
        duration = float(self.get_parameter('pulse_duration').value)

        if self._serial is None:
            self.get_logger().info(f'[simulado] pulso de {duration}s no relé')
            time.sleep(duration)
            response.success = True
            response.message = f'pulso simulado {duration}s'
            return response

        with self._serial_lock:
            try:
                self._serial.write(b'1')
                self.get_logger().info(f'Relé ATIVADO por {duration}s')
                time.sleep(duration)
                self._serial.write(b'0')
                self.get_logger().info('Relé DESATIVADO')
                response.success = True
                response.message = f'pulso {duration}s concluído'
            except Exception as e:
                self.get_logger().error(f'Erro serial: {e}')
                response.success = False
                response.message = str(e)

        return response

    def destroy_node(self):
        if self._serial is not None:
            try:
                self._serial.write(b'0')  # garante relé desligado
                self._serial.close()
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = RelayController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
