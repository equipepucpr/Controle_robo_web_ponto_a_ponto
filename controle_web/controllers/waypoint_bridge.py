"""
Ponte ROS2 ↔ Socket.IO para o fluxo de waypoints.

Responsabilidades:
  - Inscreve /Odometry (FAST-LIO2)       → emite 'pose_update' a 10 Hz.
  - Inscreve /waypoints (TRANSIENT_LOCAL) → emite 'waypoints_update' on-change.
  - Inscreve /follower_status             → emite 'follower_status' on-change.
  - Expõe métodos que chamam os serviços std_srvs/Trigger dos nós
    waypoint_recorder e waypoint_follower:
        record_waypoint()      → /waypoint_recorder/record_waypoint
        clear_waypoints()      → /waypoint_recorder/clear_waypoints
        reset_origin()         → /waypoint_recorder/reset_origin
        next_round()           → /waypoint_recorder/next_round
        start_follow()         → /waypoint_follower/start
        stop_follow()          → /waypoint_follower/stop
        return_to_origin()     → /waypoint_follower/return_to_origin

Roda um executor próprio em thread daemon pra processar callbacks sem
bloquear o Flask.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from typing import Optional

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy

from nav_msgs.msg import Odometry
from std_msgs.msg import String
from std_srvs.srv import Trigger


log = logging.getLogger(__name__)


def _quat_to_yaw(qx: float, qy: float, qz: float, qw: float) -> float:
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    return math.atan2(siny_cosp, cosy_cosp)


def _apply_inverse_offset(px, py, pyaw, ox, oy, oyaw):
    dx = px - ox
    dy = py - oy
    c = math.cos(-oyaw)
    s = math.sin(-oyaw)
    rx = c * dx - s * dy
    ry = s * dx + c * dy
    ryaw = math.atan2(math.sin(pyaw - oyaw), math.cos(pyaw - oyaw))
    return rx, ry, ryaw


class WaypointBridge:

    POSE_EMIT_HZ = 10.0
    SERVICE_CALL_TIMEOUT = 3.0   # s
    SERVICE_READY_TIMEOUT = 5.0  # s

    def __init__(self, socketio):
        self._sock = socketio

        if not rclpy.ok():
            rclpy.init()

        self._node: Node = rclpy.create_node('web_waypoint_bridge')

        wp_qos = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            history=QoSHistoryPolicy.KEEP_LAST,
        )

        self._lock = threading.Lock()
        self._last_pose_lio: Optional[dict] = None
        self._origin_offset = {'x': 0.0, 'y': 0.0, 'yaw': 0.0}

        self._node.create_subscription(
            Odometry, '/Odometry', self._on_odom, 20
        )
        self._node.create_subscription(
            String, '/waypoints', self._on_waypoints, wp_qos
        )
        self._node.create_subscription(
            String, '/follower_status', self._on_status, 10
        )

        # Clientes de serviço (reaproveitados a cada chamada).
        self._cli_record = self._node.create_client(
            Trigger, '/waypoint_recorder/record_waypoint'
        )
        self._cli_clear = self._node.create_client(
            Trigger, '/waypoint_recorder/clear_waypoints'
        )
        self._cli_reset = self._node.create_client(
            Trigger, '/waypoint_recorder/reset_origin'
        )
        self._cli_next_round = self._node.create_client(
            Trigger, '/waypoint_recorder/next_round'
        )
        self._cli_start = self._node.create_client(
            Trigger, '/waypoint_follower/start'
        )
        self._cli_stop = self._node.create_client(
            Trigger, '/waypoint_follower/stop'
        )
        self._cli_return = self._node.create_client(
            Trigger, '/waypoint_follower/return_to_origin'
        )

        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._running = True

        self._spin_thread = threading.Thread(
            target=self._spin_loop, daemon=True, name='wp_bridge_spin'
        )
        self._spin_thread.start()

        self._pose_thread = threading.Thread(
            target=self._pose_emit_loop, daemon=True, name='wp_bridge_pose'
        )
        self._pose_thread.start()

        log.info('[WaypointBridge] inicializado')

    # ---------- loop ROS ----------

    def _spin_loop(self):
        while self._running and rclpy.ok():
            try:
                self._executor.spin_once(timeout_sec=0.1)
            except Exception as e:
                log.warning(f'[WaypointBridge] spin: {e}')

    # ---------- callbacks ----------

    def _on_odom(self, msg: Odometry) -> None:
        yaw = _quat_to_yaw(
            msg.pose.pose.orientation.x,
            msg.pose.pose.orientation.y,
            msg.pose.pose.orientation.z,
            msg.pose.pose.orientation.w,
        )
        with self._lock:
            self._last_pose_lio = {
                'x': msg.pose.pose.position.x,
                'y': msg.pose.pose.position.y,
                'yaw': yaw,
                'ts': time.time(),
            }

    def _on_waypoints(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError as e:
            log.warning(f'[WaypointBridge] /waypoints inválido: {e}')
            return
        origin = data.get('origin_offset') or {}
        with self._lock:
            self._origin_offset = {
                'x': float(origin.get('x', 0.0)),
                'y': float(origin.get('y', 0.0)),
                'yaw': float(origin.get('yaw', 0.0)),
            }
        self._sock.emit(
            'waypoints_update',
            {
                'waypoints': data.get('waypoints', []),
                'origin_offset': origin,
                'current_round': data.get('current_round', 1),
            },
            namespace='/',
        )

    def _on_status(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        self._sock.emit('follower_status', payload, namespace='/')

    # ---------- emissão de pose ----------

    def _pose_emit_loop(self):
        period = 1.0 / self.POSE_EMIT_HZ
        while self._running:
            with self._lock:
                lio = self._last_pose_lio
                off = self._origin_offset
            if lio is not None:
                rx, ry, ryaw = _apply_inverse_offset(
                    lio['x'], lio['y'], lio['yaw'],
                    off['x'], off['y'], off['yaw'],
                )
                self._sock.emit(
                    'pose_update',
                    {
                        'x': rx, 'y': ry, 'yaw': ryaw,
                        'ts': lio['ts'],
                        'lio': {'x': lio['x'], 'y': lio['y'], 'yaw': lio['yaw']},
                    },
                    namespace='/',
                )
            time.sleep(period)

    # ---------- serviços ----------

    def _call_trigger(self, client, label: str) -> dict:
        if not client.wait_for_service(timeout_sec=self.SERVICE_READY_TIMEOUT):
            return {'ok': False, 'error': f'{label}: serviço indisponível'}
        future = client.call_async(Trigger.Request())
        deadline = time.monotonic() + self.SERVICE_CALL_TIMEOUT
        while not future.done():
            if time.monotonic() > deadline:
                return {'ok': False, 'error': f'{label}: timeout'}
            time.sleep(0.02)
        try:
            result = future.result()
        except Exception as e:
            return {'ok': False, 'error': f'{label}: {e}'}
        out = {'ok': bool(result.success), 'message': result.message}
        try:
            # Alguns serviços retornam JSON em message (ex: record_waypoint).
            out['data'] = json.loads(result.message)
        except (json.JSONDecodeError, TypeError):
            pass
        return out

    def record_waypoint(self) -> dict:
        return self._call_trigger(self._cli_record, 'record_waypoint')

    def clear_waypoints(self) -> dict:
        return self._call_trigger(self._cli_clear, 'clear_waypoints')

    def reset_origin(self) -> dict:
        return self._call_trigger(self._cli_reset, 'reset_origin')

    def next_round(self) -> dict:
        return self._call_trigger(self._cli_next_round, 'next_round')

    def start_follow(self) -> dict:
        return self._call_trigger(self._cli_start, 'start')

    def stop_follow(self) -> dict:
        return self._call_trigger(self._cli_stop, 'stop')

    def return_to_origin(self) -> dict:
        return self._call_trigger(self._cli_return, 'return_to_origin')

    # ---------- shutdown ----------

    def shutdown(self):
        self._running = False
        try:
            self._executor.shutdown()
            self._node.destroy_node()
        except Exception:
            pass
