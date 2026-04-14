"""
Ponte ROS2 → WebSocket para mapa, pose do robô e navegação.

Responsabilidades:
  * Subscribe /map (OccupancyGrid) — converte para PNG e emite 'map_update'
    pelo Socket.IO (tanto no modo SLAM ao vivo quanto no NAV2 com mapa estático).
  * Subscribe TF map→base_link — emite 'robot_pose' a ~10 Hz.
  * Subscribe /plan (Path) — emite 'plan_update' quando o Nav2 calcula uma rota.
  * Publica PoseStamped em /goal_pose quando o cliente clica no mapa.
  * Salva o mapa em disco via map_saver_cli (usa o /map atual, SLAM ou NAV2).

Usa o contexto global do rclpy (já inicializado pelo ROS2Controller).
Roda um executor próprio em thread daemon pra processar callbacks.
"""
from __future__ import annotations

import base64
import logging
import math
import os
import subprocess
import threading
import time
from io import BytesIO
from typing import Optional

import numpy as np
from PIL import Image

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy

from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import OccupancyGrid, Path
from tf2_ros import Buffer, TransformException, TransformListener


log = logging.getLogger(__name__)


def _occupancy_to_png_b64(grid: OccupancyGrid) -> str:
    """Converte um OccupancyGrid em PNG grayscale (base64)."""
    w = grid.info.width
    h = grid.info.height
    arr = np.array(grid.data, dtype=np.int16).reshape((h, w))
    # Convenção OccupancyGrid: -1 desconhecido, 0 livre, 100 ocupado.
    img = np.full((h, w), 205, dtype=np.uint8)  # cinza (desconhecido)
    img[arr == 0] = 254                          # branco (livre)
    img[arr >= 50] = 0                           # preto (ocupado)
    # ROS: y cresce pra cima; PNG: y cresce pra baixo — inverte linhas.
    img = np.flipud(img)
    pil = Image.fromarray(img, mode='L')
    buf = BytesIO()
    pil.save(buf, format='PNG', optimize=True)
    return base64.b64encode(buf.getvalue()).decode('ascii')


def _quat_to_yaw(qx: float, qy: float, qz: float, qw: float) -> float:
    """Converte quaternion (xyzw) em yaw (radianos)."""
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    return math.atan2(siny_cosp, cosy_cosp)


def _yaw_to_quat(yaw: float) -> tuple:
    """Converte yaw em quaternion (x, y, z, w)."""
    return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))


class MapBridge:
    """Gerencia todos os tópicos ROS2 relacionados a mapa/navegação."""

    POSE_PUBLISH_HZ = 10.0

    def __init__(self, socketio, mode: str, maps_dir: str):
        self._sock = socketio
        self._mode = mode          # 'teleop' | 'slam' | 'nav2'
        self._maps_dir = maps_dir
        os.makedirs(maps_dir, exist_ok=True)

        if not rclpy.ok():
            rclpy.init()

        self._node: Node = rclpy.create_node('web_map_bridge')

        # /map é publicado com durability transient_local (latched).
        # Sem isso o subscriber não recebe a mensagem retida.
        map_qos = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            history=QoSHistoryPolicy.KEEP_LAST,
        )

        self._node.create_subscription(
            OccupancyGrid, '/map', self._on_map, map_qos
        )
        self._node.create_subscription(
            Path, '/plan', self._on_plan, 10
        )
        self._goal_pub = self._node.create_publisher(
            PoseStamped, '/goal_pose', 10
        )

        # TF map→base_link para rastrear o robô no mapa.
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self._node)

        # Guarda o último metadata do mapa para converter clique pixel→mundo
        # no cliente (o cliente já recebe isso no map_update).
        self._last_map_info: Optional[dict] = None

        # Executor próprio — permite spin dos callbacks sem bloquear o Flask.
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._running = True

        self._spin_thread = threading.Thread(
            target=self._spin_loop, daemon=True, name='map_bridge_spin'
        )
        self._spin_thread.start()

        self._pose_thread = threading.Thread(
            target=self._pose_loop, daemon=True, name='map_bridge_pose'
        )
        self._pose_thread.start()

        log.info(f"[MapBridge] inicializado (modo={mode}, maps_dir={maps_dir})")

    # ---- Loop do executor ROS2 ----
    def _spin_loop(self):
        while self._running and rclpy.ok():
            try:
                self._executor.spin_once(timeout_sec=0.1)
            except Exception as e:
                log.warning(f"[MapBridge] erro no spin: {e}")

    # ---- Loop de polling de pose (TF map→base_link) ----
    def _pose_loop(self):
        period = 1.0 / self.POSE_PUBLISH_HZ
        while self._running:
            try:
                t = self._tf_buffer.lookup_transform(
                    'map', 'base_link', rclpy.time.Time()
                )
                x = t.transform.translation.x
                y = t.transform.translation.y
                yaw = _quat_to_yaw(
                    t.transform.rotation.x,
                    t.transform.rotation.y,
                    t.transform.rotation.z,
                    t.transform.rotation.w,
                )
                self._sock.emit(
                    'robot_pose',
                    {'x': x, 'y': y, 'yaw': yaw, 'ts': time.time()},
                    namespace='/',
                )
            except TransformException:
                # Ainda não tem TF — normal antes do SLAM/AMCL convergir.
                pass
            except Exception as e:
                log.debug(f"[MapBridge] pose loop: {e}")
            time.sleep(period)

    # ---- Callbacks ROS2 ----
    def _on_map(self, msg: OccupancyGrid):
        try:
            png_b64 = _occupancy_to_png_b64(msg)
            info = {
                'width': msg.info.width,
                'height': msg.info.height,
                'resolution': msg.info.resolution,
                'origin_x': msg.info.origin.position.x,
                'origin_y': msg.info.origin.position.y,
                'origin_yaw': _quat_to_yaw(
                    msg.info.origin.orientation.x,
                    msg.info.origin.orientation.y,
                    msg.info.origin.orientation.z,
                    msg.info.origin.orientation.w,
                ),
                'stamp': time.time(),
            }
            self._last_map_info = info
            self._sock.emit(
                'map_update',
                {'info': info, 'png_b64': png_b64},
                namespace='/',
            )
            log.info(
                f"[MapBridge] /map {msg.info.width}x{msg.info.height} "
                f"@ {msg.info.resolution:.3f} m/px emitido"
            )
        except Exception as e:
            log.warning(f"[MapBridge] erro convertendo /map: {e}")

    def _on_plan(self, msg: Path):
        try:
            pts = [
                {'x': p.pose.position.x, 'y': p.pose.position.y}
                for p in msg.poses
            ]
            self._sock.emit('plan_update', {'points': pts}, namespace='/')
        except Exception as e:
            log.debug(f"[MapBridge] erro no /plan: {e}")

    # ---- API pública ----
    def send_goal(self, x: float, y: float, yaw: float = 0.0) -> dict:
        """Publica PoseStamped em /goal_pose (frame 'map')."""
        msg = PoseStamped()
        msg.header.frame_id = 'map'
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.pose.position.x = float(x)
        msg.pose.position.y = float(y)
        qx, qy, qz, qw = _yaw_to_quat(float(yaw))
        msg.pose.orientation.x = qx
        msg.pose.orientation.y = qy
        msg.pose.orientation.z = qz
        msg.pose.orientation.w = qw
        self._goal_pub.publish(msg)
        log.info(f"[MapBridge] /goal_pose → ({x:.2f}, {y:.2f}, yaw={yaw:.2f})")
        return {'ok': True, 'x': x, 'y': y, 'yaw': yaw}

    def save_map(self, name: str) -> dict:
        """Salva o mapa atual em disco via map_saver_cli."""
        # Sanitiza nome: só alfanumérico, '-' e '_'.
        safe = ''.join(c for c in name if c.isalnum() or c in '-_') or 'sala'
        base_path = os.path.join(self._maps_dir, safe)
        cmd = [
            'ros2', 'run', 'nav2_map_server', 'map_saver_cli',
            '-f', base_path,
            '--ros-args', '-p', 'map_subscribe_transient_local:=true',
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
        except subprocess.TimeoutExpired:
            return {'ok': False, 'error': 'timeout ao salvar mapa'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

        ok = proc.returncode == 0 and os.path.isfile(base_path + '.yaml')
        out = (proc.stdout + proc.stderr).strip().splitlines()
        tail = '\n'.join(out[-10:])
        if ok:
            log.info(f"[MapBridge] mapa salvo em {base_path}.yaml")
            return {
                'ok': True,
                'yaml': base_path + '.yaml',
                'pgm': base_path + '.pgm',
                'name': safe,
            }
        log.warning(f"[MapBridge] falha ao salvar mapa: {tail}")
        return {'ok': False, 'error': tail or f'exit {proc.returncode}'}

    def shutdown(self):
        self._running = False
        try:
            self._executor.shutdown()
            self._node.destroy_node()
        except Exception:
            pass
