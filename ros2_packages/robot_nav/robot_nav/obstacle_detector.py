#!/usr/bin/env python3
"""
Detector de obstáculos baseado no LiDAR.

Lê /scan (sensor_msgs/LaserScan), divide o campo de visão em setores
e publica /obstacle_info (std_msgs/String com JSON) a até 5 Hz.

Setores (ângulos no frame do LiDAR, 0° = frente):
  FRENTE       : -30° a +30°
  FRENTE-ESQ   : +30° a +75°
  FRENTE-DIR   : -75° a -30°
  ESQUERDA     : +75° a +135°
  DIREITA      : -135° a -75°
  TRÁS         : +135° a +180° | -180° a -135°
"""

import math
import json
import time
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String


SECTORS = {
    'frente':      (-30.0,   30.0),
    'frente_esq':  ( 30.0,   75.0),
    'frente_dir':  (-75.0,  -30.0),
    'esquerda':    ( 75.0,  135.0),
    'direita':     (-135.0, -75.0),
    'tras':        None,  # resto (>135 ou <-135)
}

# Limites de cor: verde > 1.5m, amarelo 0.5-1.5m, vermelho < 0.5m
DIST_DANGER = 0.5
DIST_WARN   = 1.5


def _color(d):
    if d is None or d > DIST_WARN:
        return 'verde'
    if d > DIST_DANGER:
        return 'amarelo'
    return 'vermelho'


OUTPUT_FILE = '/tmp/obstacle_current.json'


class ObstacleDetectorNode(Node):

    def __init__(self):
        super().__init__('obstacle_detector')
        self._last_write = 0.0
        self._write_interval = 0.2   # máx 5 Hz

        self.create_subscription(LaserScan, 'scan', self._scan_cb, 10)
        self.pub = self.create_publisher(String, 'obstacle_info', 10)
        self.get_logger().info(f'ObstacleDetector iniciado — escutando /scan → {OUTPUT_FILE}')

    def _scan_cb(self, msg: LaserScan):
        now = time.monotonic()
        if now - self._last_write < self._write_interval:
            return
        self._last_write = now

        data = self._analyze(msg)

        # Escreve no arquivo para o Flask ler (sem threading cruzado)
        try:
            with open(OUTPUT_FILE, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            self.get_logger().warn(f'write error: {e}')

        # Publica no tópico ROS2 também
        s = String()
        s.data = json.dumps(data)
        self.pub.publish(s)

    def _analyze(self, msg: LaserScan) -> dict:
        ranges = msg.ranges
        angle_min = msg.angle_min      # rad
        angle_inc = msg.angle_increment  # rad/step

        sector_mins = {k: None for k in SECTORS}
        closest_dist = None
        closest_angle = None

        for i, r in enumerate(ranges):
            if not math.isfinite(r) or r < msg.range_min or r > msg.range_max:
                continue
            angle_rad = angle_min + i * angle_inc
            angle_deg = math.degrees(angle_rad)

            # Normaliza para -180..180
            while angle_deg > 180:
                angle_deg -= 360
            while angle_deg < -180:
                angle_deg += 360

            sector = self._classify(angle_deg)
            if sector_mins[sector] is None or r < sector_mins[sector]:
                sector_mins[sector] = r

            if closest_dist is None or r < closest_dist:
                closest_dist = r
                closest_angle = angle_deg

        # Mínimo frontal (frente + frente_esq + frente_dir)
        front_dists = [sector_mins[k] for k in ('frente', 'frente_esq', 'frente_dir') if sector_mins[k] is not None]
        front_min = min(front_dists) if front_dists else None

        sectors_out = {}
        for k, d in sector_mins.items():
            sectors_out[k] = {
                'dist': round(d, 2) if d is not None else None,
                'cor': _color(d),
            }

        return {
            'conectado': True,
            'mais_proximo': {
                'dist': round(closest_dist, 2) if closest_dist is not None else None,
                'angulo': round(closest_angle, 1) if closest_angle is not None else None,
                'cor': _color(closest_dist),
            },
            'frente_min': round(front_min, 2) if front_min is not None else None,
            'frente_cor': _color(front_min),
            'setores': sectors_out,
        }

    @staticmethod
    def _classify(deg: float) -> str:
        if -30.0 <= deg <= 30.0:
            return 'frente'
        if 30.0 < deg <= 75.0:
            return 'frente_esq'
        if -75.0 <= deg < -30.0:
            return 'frente_dir'
        if 75.0 < deg <= 135.0:
            return 'esquerda'
        if -135.0 <= deg < -75.0:
            return 'direita'
        return 'tras'


def main(args=None):
    rclpy.init(args=args)
    node = ObstacleDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
        # Limpa o arquivo ao encerrar
        try:
            import os
            os.remove(OUTPUT_FILE)
        except Exception:
            pass


if __name__ == '__main__':
    main()
