#!/usr/bin/env python3
"""
Converts geometry_msgs/Twist (/cmd_vel_filtered from Nav2 Collision Monitor)
into wheel_msgs/WheelSpeeds (/wheel_vel_setpoints for the hoverboard driver).

Differential drive model:
  right_wheel = linear * LINEAR_SCALE + angular * ANGULAR_SCALE
  left_wheel  = linear * LINEAR_SCALE - angular * ANGULAR_SCALE

The scales convert m/s and rad/s into the hoverboard driver's internal units
(roughly -1000 to 1000). Tune linear_scale and angular_scale to match your robot.
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from wheel_msgs.msg import WheelSpeeds


class CmdVelToWheels(Node):

    def __init__(self):
        super().__init__('cmd_vel_to_wheels')

        # Scale factors: tune these to match your robot's response
        # linear_scale: hoverboard units per m/s  (e.g. 400 means 1 m/s = 400 units)
        # angular_scale: hoverboard units per rad/s
        self.declare_parameter('linear_scale', 400.0)
        self.declare_parameter('angular_scale', 150.0)
        self.declare_parameter('cmd_vel_topic', 'cmd_vel')
        self.declare_parameter('max_output', 1000.0)
        # Empurrão mínimo pra vencer atrito estático do hoverboard.
        # Saídas não-zero abaixo desse valor são elevadas ao min_output.
        self.declare_parameter('min_output', 180.0)

        self.linear_scale = self.get_parameter('linear_scale').value
        self.angular_scale = self.get_parameter('angular_scale').value
        self.cmd_vel_topic = self.get_parameter('cmd_vel_topic').value
        self.max_output = self.get_parameter('max_output').value
        self.min_output = self.get_parameter('min_output').value

        self.sub = self.create_subscription(
            Twist,
            self.cmd_vel_topic,
            self._cmd_vel_callback,
            10
        )

        self.pub = self.create_publisher(WheelSpeeds, 'wheel_vel_setpoints', 10)

        self.get_logger().info(
            f'CmdVelToWheels: listening on /{self.cmd_vel_topic} '
            f'| linear_scale={self.linear_scale} | angular_scale={self.angular_scale}'
        )

    def _cmd_vel_callback(self, msg: Twist):
        linear = msg.linear.x
        angular = msg.angular.z

        right = linear * self.linear_scale + angular * self.angular_scale
        left = linear * self.linear_scale - angular * self.angular_scale

        # Kicker: se a saída é não-zero mas abaixo do limiar de atrito estático,
        # empurra pro min_output preservando o sinal.
        if 0.0 < abs(right) < self.min_output:
            right = self.min_output if right > 0 else -self.min_output
        if 0.0 < abs(left) < self.min_output:
            left = self.min_output if left > 0 else -self.min_output

        # Clamp to safe range
        right = max(-self.max_output, min(self.max_output, right))
        left = max(-self.max_output, min(self.max_output, left))

        # Os fios do hoverboard estão invertidos: o que o driver chama de
        # "left_wheel" dirige a roda direita e vice-versa. Trocamos aqui para
        # que a convenção ROS (angular.z > 0 = girar à esquerda) seja respeitada.
        wheels = WheelSpeeds()
        wheels.right_wheel = float(left)
        wheels.left_wheel = float(right)
        self.pub.publish(wheels)


def main(args=None):
    rclpy.init(args=args)
    node = CmdVelToWheels()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
