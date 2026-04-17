#!/usr/bin/env python3
"""
Nó que executa uma sequência de waypoints usando controlador pure-pursuit
simplificado pra diff-drive.

Entrada:
  /Odometry (nav_msgs/Odometry) — pose ao vivo do FAST-LIO2.
  /waypoints (std_msgs/String JSON, TRANSIENT_LOCAL) — vindo do waypoint_recorder.

Serviços:
  ~/start             (std_srvs/Trigger) — percorre 1→N e para no último.
  ~/stop              (std_srvs/Trigger) — cmd_vel=0, estado IDLE.
  ~/return_to_origin  (std_srvs/Trigger) — percorre N→...→1→origem(0,0).

Saída:
  /cmd_vel          (geometry_msgs/Twist)
  /follower_status  (std_msgs/String JSON) a 5 Hz.

Controlador: "heading first, then forward":
  Se o erro angular para o alvo > heading_tolerance: gira no lugar.
  Senão: anda pra frente com correção proporcional de yaw.

Segurança: se /Odometry ficar velho por mais de pose_timeout_sec, para
automaticamente e vai pra estado STOPPED (publica status com razão).
"""

import json
import math
import threading
import time
from typing import Dict, List, Optional

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from std_srvs.srv import Trigger


def quat_to_yaw(qx: float, qy: float, qz: float, qw: float) -> float:
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    return math.atan2(siny_cosp, cosy_cosp)


def apply_inverse_offset(px: float, py: float, pyaw: float,
                         ox: float, oy: float, oyaw: float) -> tuple:
    dx = px - ox
    dy = py - oy
    c = math.cos(-oyaw)
    s = math.sin(-oyaw)
    rx = c * dx - s * dy
    ry = s * dx + c * dy
    ryaw = math.atan2(math.sin(pyaw - oyaw), math.cos(pyaw - oyaw))
    return rx, ry, ryaw


def wrap_angle(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


STATE_IDLE = 'IDLE'
STATE_FORWARD = 'FORWARD'
STATE_REVERSE = 'REVERSE'
STATE_STOPPED = 'STOPPED'


class WaypointFollower(Node):

    def __init__(self):
        super().__init__('waypoint_follower')

        self.declare_parameter('odometry_topic', '/Odometry')
        self.declare_parameter('cmd_vel_topic', '/cmd_vel')
        self.declare_parameter('control_rate_hz', 20.0)
        self.declare_parameter('status_rate_hz', 5.0)
        self.declare_parameter('linear_speed', 0.35)       # m/s cruzeiro
        self.declare_parameter('angular_speed', 0.8)       # rad/s no giro em lugar
        self.declare_parameter('kp_angular', 1.5)          # ganho proporcional pro heading
        self.declare_parameter('goal_tolerance', 0.20)     # m
        self.declare_parameter('final_tolerance', 0.12)    # m (último waypoint / origem)
        self.declare_parameter('heading_tolerance', 0.25)  # rad (acima disso, gira antes de andar)
        self.declare_parameter('pose_timeout_sec', 1.5)

        self.odom_topic = self.get_parameter('odometry_topic').value
        self.cmd_vel_topic = self.get_parameter('cmd_vel_topic').value
        self.control_rate = float(self.get_parameter('control_rate_hz').value)
        self.status_rate = float(self.get_parameter('status_rate_hz').value)
        self.v_target = float(self.get_parameter('linear_speed').value)
        self.w_target = float(self.get_parameter('angular_speed').value)
        self.kp_ang = float(self.get_parameter('kp_angular').value)
        self.goal_tol = float(self.get_parameter('goal_tolerance').value)
        self.final_tol = float(self.get_parameter('final_tolerance').value)
        self.heading_tol = float(self.get_parameter('heading_tolerance').value)
        self.pose_timeout = Duration(
            seconds=float(self.get_parameter('pose_timeout_sec').value)
        )

        self._lock = threading.Lock()
        self._state = STATE_IDLE
        self._state_reason = ''
        self._waypoints: List[Dict[str, float]] = []
        self._origin_offset = {'x': 0.0, 'y': 0.0, 'yaw': 0.0}
        self._queue: List[Dict[str, float]] = []   # fila de alvos a atingir
        self._current_target_idx = 0               # 0-based dentro do queue
        self._dist_to_target = float('inf')

        self._last_pose: Optional[Dict[str, float]] = None
        self._last_pose_stamp = None

        # Subscribers
        self.create_subscription(Odometry, self.odom_topic, self._on_odom, 20)
        wp_qos = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            history=QoSHistoryPolicy.KEEP_LAST,
        )
        self.create_subscription(String, '/waypoints', self._on_waypoints, wp_qos)

        # Publishers
        self._cmd_pub = self.create_publisher(Twist, self.cmd_vel_topic, 10)
        self._status_pub = self.create_publisher(String, '/follower_status', 10)

        # Serviços
        self.create_service(Trigger, '~/start', self._on_start)
        self.create_service(Trigger, '~/stop', self._on_stop)
        self.create_service(Trigger, '~/return_to_origin', self._on_return)

        # Timers
        self.create_timer(1.0 / self.control_rate, self._control_tick)
        self.create_timer(1.0 / self.status_rate, self._publish_status)

        self.get_logger().info(
            f'waypoint_follower pronto | odom={self.odom_topic} '
            f'| cmd_vel={self.cmd_vel_topic} | v={self.v_target} m/s'
        )

    # ---------- callbacks ----------

    def _on_odom(self, msg: Odometry) -> None:
        yaw = quat_to_yaw(
            msg.pose.pose.orientation.x,
            msg.pose.pose.orientation.y,
            msg.pose.pose.orientation.z,
            msg.pose.pose.orientation.w,
        )
        with self._lock:
            self._last_pose = {
                'x': msg.pose.pose.position.x,
                'y': msg.pose.pose.position.y,
                'yaw': yaw,
            }
            self._last_pose_stamp = self.get_clock().now()

    def _on_waypoints(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError as e:
            self.get_logger().warn(f'/waypoints JSON inválido: {e}')
            return
        with self._lock:
            origin = data.get('origin_offset') or {}
            self._origin_offset = {
                'x': float(origin.get('x', 0.0)),
                'y': float(origin.get('y', 0.0)),
                'yaw': float(origin.get('yaw', 0.0)),
            }
            self._waypoints = [
                {
                    'id': int(wp['id']),
                    'x': float(wp['x']),
                    'y': float(wp['y']),
                    'yaw': float(wp.get('yaw', 0.0)),
                }
                for wp in data.get('waypoints', [])
            ]
        self.get_logger().debug(
            f'/waypoints atualizado: {len(self._waypoints)} pontos'
        )

    # ---------- serviços ----------

    def _on_start(self, request, response):
        with self._lock:
            if not self._waypoints:
                response.success = False
                response.message = 'Lista vazia — nada pra seguir.'
                return response
            self._queue = list(self._waypoints)  # 1→N
            self._current_target_idx = 0
            self._state = STATE_FORWARD
            self._state_reason = f'Iniciando {len(self._queue)} waypoints'
        self.get_logger().info(
            f'START — percorrendo {len(self._queue)} waypoints'
        )
        response.success = True
        response.message = json.dumps({'count': len(self._waypoints)})
        return response

    def _on_stop(self, request, response):
        with self._lock:
            self._state = STATE_IDLE
            self._state_reason = 'stop solicitado'
            self._queue = []
            self._current_target_idx = 0
        self._publish_cmd(0.0, 0.0)
        self.get_logger().info('STOP')
        response.success = True
        response.message = 'parado'
        return response

    def _on_return(self, request, response):
        with self._lock:
            if not self._waypoints:
                # Sem waypoints, ir pra origem direto.
                self._queue = [{'id': 0, 'x': 0.0, 'y': 0.0, 'yaw': 0.0}]
            else:
                # N → N-1 → ... → 1 → origem(0,0).
                reverse = list(reversed(self._waypoints))
                reverse.append({'id': 0, 'x': 0.0, 'y': 0.0, 'yaw': 0.0})
                self._queue = reverse
            self._current_target_idx = 0
            self._state = STATE_REVERSE
            self._state_reason = f'Voltando ({len(self._queue)} pontos)'
        self.get_logger().info(
            f'RETURN_TO_ORIGIN — {len(self._queue)} pontos na fila'
        )
        response.success = True
        response.message = json.dumps({'count': len(self._queue)})
        return response

    # ---------- loop de controle ----------

    def _pose_fresh(self) -> bool:
        if self._last_pose is None or self._last_pose_stamp is None:
            return False
        return (self.get_clock().now() - self._last_pose_stamp) < self.pose_timeout

    def _current_pose_origin_frame(self) -> Optional[Dict[str, float]]:
        if self._last_pose is None:
            return None
        lio = self._last_pose
        off = self._origin_offset
        rx, ry, ryaw = apply_inverse_offset(
            lio['x'], lio['y'], lio['yaw'],
            off['x'], off['y'], off['yaw'],
        )
        return {'x': rx, 'y': ry, 'yaw': ryaw}

    def _control_tick(self) -> None:
        with self._lock:
            active = self._state in (STATE_FORWARD, STATE_REVERSE)
            if not active:
                return

            if not self._pose_fresh():
                self._state = STATE_STOPPED
                self._state_reason = 'pose timeout (FAST-LIO2 parou de publicar)'
                self._queue = []
                self._publish_cmd(0.0, 0.0)
                self.get_logger().warn(self._state_reason)
                return

            if self._current_target_idx >= len(self._queue):
                self._state = STATE_IDLE
                self._state_reason = 'trajeto concluído'
                self._queue = []
                self._current_target_idx = 0
                self._publish_cmd(0.0, 0.0)
                self.get_logger().info('Trajeto concluído.')
                return

            pose = self._current_pose_origin_frame()
            if pose is None:
                self._publish_cmd(0.0, 0.0)
                return

            target = self._queue[self._current_target_idx]
            is_last = (self._current_target_idx == len(self._queue) - 1)
            tol = self.final_tol if is_last else self.goal_tol

            dx = target['x'] - pose['x']
            dy = target['y'] - pose['y']
            dist = math.hypot(dx, dy)
            self._dist_to_target = dist

            if dist < tol:
                self._current_target_idx += 1
                self._publish_cmd(0.0, 0.0)
                self.get_logger().info(
                    f"Alvo {target['id']} atingido (dist={dist:.2f}m). "
                    f"Próximo: {self._current_target_idx + 1}/{len(self._queue)}"
                )
                return

            target_heading = math.atan2(dy, dx)
            heading_err = wrap_angle(target_heading - pose['yaw'])

            if abs(heading_err) > self.heading_tol:
                # Gira no lugar até alinhar com o alvo.
                w = math.copysign(
                    min(self.w_target, self.kp_ang * abs(heading_err)),
                    heading_err,
                )
                self._publish_cmd(0.0, w)
            else:
                # Anda pra frente com correção proporcional.
                v = self.v_target
                # Reduz velocidade perto do alvo pra suavizar a parada.
                v_scaled = min(v, max(0.1, dist * 1.5))
                w = self.kp_ang * heading_err
                self._publish_cmd(v_scaled, w)

    def _publish_cmd(self, linear: float, angular: float) -> None:
        msg = Twist()
        msg.linear.x = float(linear)
        msg.angular.z = float(angular)
        self._cmd_pub.publish(msg)

    # ---------- status ----------

    def _publish_status(self) -> None:
        with self._lock:
            payload = {
                'state': self._state,
                'reason': self._state_reason,
                'queue_len': len(self._queue),
                'current_idx': self._current_target_idx,
                'target_id': (
                    self._queue[self._current_target_idx]['id']
                    if self._queue and self._current_target_idx < len(self._queue)
                    else None
                ),
                'dist_to_target': round(self._dist_to_target, 3)
                if math.isfinite(self._dist_to_target) else None,
                'ts': time.time(),
            }
        msg = String()
        msg.data = json.dumps(payload)
        self._status_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = WaypointFollower()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
