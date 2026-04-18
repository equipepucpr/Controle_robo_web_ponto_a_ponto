#!/usr/bin/env python3
"""
Nó que grava waypoints em memória (e em disco JSON) enquanto o usuário
pilota o robô manualmente.

Entrada:
  /Odometry (nav_msgs/Odometry) — pose ao vivo do FAST-LIO2.

Serviços:
  ~/record_waypoint  (std_srvs/Trigger)
  ~/clear_waypoints  (std_srvs/Trigger)
  ~/reset_origin     (std_srvs/Trigger) — (0,0,0) passa a ser a pose atual.
  ~/next_round       (std_srvs/Trigger) — incrementa o round atual.

Saída (latched, TRANSIENT_LOCAL — subscribers novos pegam o estado atual):
  /waypoints (std_msgs/String com JSON)

Persistência:
  controle_web/waypoints/current.json é reescrito a cada mudança.

Modelo de coordenadas:
  O FAST-LIO2 publica pose no frame "camera_init" com origem na inicialização.
  Para permitir redefinir o ponto 0 sem reiniciar o LIO, guardamos um
  origin_offset (x0, y0, yaw0): os waypoints são armazenados no frame
  "origem" = pose_lio transformada pelo inverso desse offset. O follower
  aplica a mesma transformação à pose que recebe do /Odometry.
"""

import json
import math
import os
import threading
import time
from typing import Dict, Optional

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy

from nav_msgs.msg import Odometry
from std_msgs.msg import String
from std_srvs.srv import Trigger


def quat_to_yaw(qx: float, qy: float, qz: float, qw: float) -> float:
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    return math.atan2(siny_cosp, cosy_cosp)


def apply_inverse_offset(px: float, py: float, pyaw: float,
                         ox: float, oy: float, oyaw: float) -> tuple:
    """Transforma (px,py,pyaw) do frame LIO para o frame origem.

    origem tem pose (ox, oy, oyaw) no frame LIO. Retorna a pose relativa.
    """
    dx = px - ox
    dy = py - oy
    c = math.cos(-oyaw)
    s = math.sin(-oyaw)
    rx = c * dx - s * dy
    ry = s * dx + c * dy
    ryaw = math.atan2(math.sin(pyaw - oyaw), math.cos(pyaw - oyaw))
    return rx, ry, ryaw


class WaypointRecorder(Node):

    DEFAULT_JSON = os.path.expanduser(
        '~/Workspace/Controle_robo_web_ponto_a_ponto/controle_web/waypoints/current.json'
    )

    def __init__(self):
        super().__init__('waypoint_recorder')

        self.declare_parameter('odometry_topic', '/Odometry')
        self.declare_parameter('persist_path', self.DEFAULT_JSON)
        self.declare_parameter('pose_timeout_sec', 2.0)

        self.odom_topic = self.get_parameter('odometry_topic').value
        self.persist_path = os.path.abspath(
            os.path.expanduser(self.get_parameter('persist_path').value)
        )
        self.pose_timeout = Duration(
            seconds=float(self.get_parameter('pose_timeout_sec').value)
        )

        self._lock = threading.Lock()
        self._last_pose: Optional[Dict[str, float]] = None
        self._last_pose_stamp = None
        # (x, y, yaw) do ponto 0 expressos no frame do LIO.
        self._origin_offset: Dict[str, float] = {'x': 0.0, 'y': 0.0, 'yaw': 0.0}
        self._waypoints: list = []
        self._next_id = 1
        self._current_round = 1

        self._load_persisted()

        self.create_subscription(Odometry, self.odom_topic, self._on_odom, 20)

        wp_qos = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            history=QoSHistoryPolicy.KEEP_LAST,
        )
        self._wp_pub = self.create_publisher(String, '/waypoints', wp_qos)

        self.create_service(Trigger, '~/record_waypoint', self._on_record)
        self.create_service(Trigger, '~/clear_waypoints', self._on_clear)
        self.create_service(Trigger, '~/reset_origin', self._on_reset_origin)
        self.create_service(Trigger, '~/next_round', self._on_next_round)

        self._publish_waypoints()
        self.get_logger().info(
            f'waypoint_recorder pronto | odom={self.odom_topic} | '
            f'persist={self.persist_path}'
        )

    # ---------- persistência ----------

    def _load_persisted(self) -> None:
        if not os.path.isfile(self.persist_path):
            return
        try:
            with open(self.persist_path) as f:
                data = json.load(f)
            origin = data.get('origin_offset') or {}
            self._origin_offset = {
                'x': float(origin.get('x', 0.0)),
                'y': float(origin.get('y', 0.0)),
                'yaw': float(origin.get('yaw', 0.0)),
            }
            for wp in data.get('waypoints', []):
                self._waypoints.append({
                    'id': int(wp['id']),
                    'x': float(wp['x']),
                    'y': float(wp['y']),
                    'yaw': float(wp.get('yaw', 0.0)),
                    'ts': float(wp.get('ts', 0.0)),
                    'round': int(wp.get('round', 1)),
                })
                self._next_id = max(self._next_id, int(wp['id']) + 1)
                self._current_round = max(self._current_round, int(wp.get('round', 1)))
            self.get_logger().info(
                f'Carregados {len(self._waypoints)} waypoints de {self.persist_path}'
            )
        except Exception as e:
            self.get_logger().warn(f'Falha ao ler {self.persist_path}: {e}')

    def _persist(self) -> None:
        os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
        payload = self._state_dict()
        try:
            with open(self.persist_path, 'w') as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            self.get_logger().warn(f'Falha ao gravar {self.persist_path}: {e}')

    def _state_dict(self) -> dict:
        return {
            'version': 2,
            'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'origin_offset': dict(self._origin_offset),
            'current_round': self._current_round,
            'waypoints': list(self._waypoints),
        }

    # ---------- ROS ----------

    def _on_odom(self, msg: Odometry) -> None:
        with self._lock:
            self._last_pose = {
                'x': msg.pose.pose.position.x,
                'y': msg.pose.pose.position.y,
                'yaw': quat_to_yaw(
                    msg.pose.pose.orientation.x,
                    msg.pose.pose.orientation.y,
                    msg.pose.pose.orientation.z,
                    msg.pose.pose.orientation.w,
                ),
            }
            self._last_pose_stamp = self.get_clock().now()

    def _pose_fresh(self) -> bool:
        if self._last_pose is None or self._last_pose_stamp is None:
            return False
        return (self.get_clock().now() - self._last_pose_stamp) < self.pose_timeout

    def _publish_waypoints(self) -> None:
        msg = String()
        msg.data = json.dumps(self._state_dict())
        self._wp_pub.publish(msg)

    # ---------- serviços ----------

    def _on_record(self, request, response):
        with self._lock:
            if not self._pose_fresh():
                response.success = False
                response.message = 'Sem pose recente do LIO — não é seguro gravar waypoint.'
                return response
            lio = self._last_pose
            off = self._origin_offset
            rx, ry, ryaw = apply_inverse_offset(
                lio['x'], lio['y'], lio['yaw'],
                off['x'], off['y'], off['yaw'],
            )
            wp = {
                'id': self._next_id,
                'x': rx,
                'y': ry,
                'yaw': ryaw,
                'ts': time.time(),
                'round': self._current_round,
            }
            self._waypoints.append(wp)
            self._next_id += 1
            self._persist()
        self._publish_waypoints()
        response.success = True
        response.message = json.dumps(wp)
        self.get_logger().info(
            f'Waypoint #{wp["id"]} gravado em ({wp["x"]:.2f}, {wp["y"]:.2f})'
        )
        return response

    def _on_clear(self, request, response):
        with self._lock:
            n = len(self._waypoints)
            self._waypoints = []
            self._next_id = 1
            self._current_round = 1
            self._persist()
        self._publish_waypoints()
        response.success = True
        response.message = f'{n} waypoints apagados'
        self.get_logger().info(response.message)
        return response

    def _on_next_round(self, request, response):
        with self._lock:
            # Só avança se o round atual tem pelo menos 1 waypoint.
            count = sum(1 for w in self._waypoints if w.get('round') == self._current_round)
            if count == 0:
                response.success = False
                response.message = f'Round {self._current_round} vazio — grave pelo menos um ponto antes.'
                return response
            self._current_round += 1
            self._persist()
        self._publish_waypoints()
        response.success = True
        response.message = json.dumps({'round': self._current_round})
        self.get_logger().info(f'Avançou para round {self._current_round}')
        return response

    def _on_reset_origin(self, request, response):
        with self._lock:
            if not self._pose_fresh():
                response.success = False
                response.message = 'Sem pose do LIO — não é possível redefinir a origem.'
                return response
            lio = self._last_pose
            self._origin_offset = {
                'x': float(lio['x']),
                'y': float(lio['y']),
                'yaw': float(lio['yaw']),
            }
            # Ao trocar de origem, os waypoints antigos perdem sentido — apaga.
            n_cleared = len(self._waypoints)
            self._waypoints = []
            self._next_id = 1
            self._current_round = 1
            self._persist()
        self._publish_waypoints()
        response.success = True
        response.message = (
            f'Origem redefinida; {n_cleared} waypoints antigos descartados.'
        )
        self.get_logger().info(
            f'Nova origem = LIO ({self._origin_offset["x"]:.2f}, '
            f'{self._origin_offset["y"]:.2f}, {self._origin_offset["yaw"]:.2f})'
        )
        return response


def main(args=None):
    rclpy.init(args=args)
    node = WaypointRecorder()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
