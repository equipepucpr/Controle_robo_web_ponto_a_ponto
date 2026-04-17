#!/usr/bin/env python3
"""
Odometry publisher for hoverboard robot.

Subscribes to wheel velocity feedback from hoverboard driver
(/hoverboard/left_wheel/velocity and /hoverboard/right_wheel/velocity)
and publishes nav_msgs/Odometry em /wheel_odom.

Quando publish_tf=True também faz o broadcast TF odom->base_link. No fork
ponto-a-ponto a pose oficial vem do FAST-LIO2 (que já publica o TF), então
por padrão publish_tf=False — este nó é só um fallback/debug que registra
a odometria integrada das rodas em /wheel_odom.

O firmware do hoverboard reporta speedL_meas e speedR_meas em RPM.
"""

import math
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster


class OdomPublisher(Node):

    def __init__(self):
        super().__init__('odom_publisher')

        # Robot parameters (adjust to match your hoverboard)
        self.declare_parameter('wheel_radius', 0.085)   # meters - typical 6.5" hoverboard wheel
        self.declare_parameter('wheel_base', 0.45)      # meters - distance between wheel centers
        self.declare_parameter('rpm_to_rads', 2.0 * math.pi / 60.0)  # RPM -> rad/s
        self.declare_parameter('left_wheel_sign', 1.0)   # flip if odometry goes backwards
        self.declare_parameter('right_wheel_sign', -1.0) # flip if odometry goes backwards
        self.declare_parameter('odom_frame', 'odom')
        self.declare_parameter('base_frame', 'base_link')
        # No fork ponto-a-ponto o TF odom->base_link vem do FAST-LIO2 —
        # este nó só publica a msg /wheel_odom como fallback/debug.
        self.declare_parameter('publish_tf', False)
        self.declare_parameter('odom_topic', 'wheel_odom')

        self.wheel_radius = self.get_parameter('wheel_radius').value
        self.wheel_base = self.get_parameter('wheel_base').value
        self.rpm_to_rads = self.get_parameter('rpm_to_rads').value
        self.left_sign = self.get_parameter('left_wheel_sign').value
        self.right_sign = self.get_parameter('right_wheel_sign').value
        self.odom_frame = self.get_parameter('odom_frame').value
        self.base_frame = self.get_parameter('base_frame').value
        self.publish_tf = self.get_parameter('publish_tf').value
        self.odom_topic = self.get_parameter('odom_topic').value

        # State
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0
        self.last_time = self.get_clock().now()

        self.speed_left = 0.0   # m/s
        self.speed_right = 0.0  # m/s

        # Subscribers to hoverboard wheel velocities (in RPM)
        self.create_subscription(
            Float64,
            'hoverboard/left_wheel/velocity',
            self._left_vel_callback,
            10
        )
        self.create_subscription(
            Float64,
            'hoverboard/right_wheel/velocity',
            self._right_vel_callback,
            10
        )

        # Publishers
        self.odom_pub = self.create_publisher(Odometry, self.odom_topic, 10)
        self.tf_broadcaster = TransformBroadcaster(self) if self.publish_tf else None

        # Timer: publish odometry at 20 Hz
        self.create_timer(0.05, self._publish_odom)

        self.get_logger().info(
            f'OdomPublisher started | wheel_radius={self.wheel_radius}m '
            f'| wheel_base={self.wheel_base}m | topic=/{self.odom_topic} '
            f'| publish_tf={self.publish_tf}'
        )

    def _rpm_to_ms(self, rpm):
        """Convert RPM to linear wheel velocity (m/s)."""
        return rpm * self.rpm_to_rads * self.wheel_radius

    def _left_vel_callback(self, msg: Float64):
        # Driver "left" está fisicamente ligado à roda direita (fios trocados).
        self.speed_right = self._rpm_to_ms(msg.data * self.left_sign)

    def _right_vel_callback(self, msg: Float64):
        # Driver "right" está fisicamente ligado à roda esquerda.
        self.speed_left = self._rpm_to_ms(msg.data * self.right_sign)

    def _publish_odom(self):
        now = self.get_clock().now()
        dt = (now - self.last_time).nanoseconds / 1e9
        self.last_time = now

        if dt <= 0.0:
            return

        # Differential drive kinematics
        linear = (self.speed_right + self.speed_left) / 2.0
        angular = (self.speed_right - self.speed_left) / self.wheel_base

        # Integrate pose
        self.x += linear * math.cos(self.theta) * dt
        self.y += linear * math.sin(self.theta) * dt
        self.theta += angular * dt

        # Normalize theta to [-pi, pi]
        self.theta = math.atan2(math.sin(self.theta), math.cos(self.theta))

        q_z = math.sin(self.theta / 2.0)
        q_w = math.cos(self.theta / 2.0)

        # Publish TF: odom -> base_link (só se configurado — no fork ponto-a-ponto
        # quem publica esse TF é o FAST-LIO2, não queremos dois publicadores).
        if self.tf_broadcaster is not None:
            tf = TransformStamped()
            tf.header.stamp = now.to_msg()
            tf.header.frame_id = self.odom_frame
            tf.child_frame_id = self.base_frame
            tf.transform.translation.x = self.x
            tf.transform.translation.y = self.y
            tf.transform.translation.z = 0.0
            tf.transform.rotation.x = 0.0
            tf.transform.rotation.y = 0.0
            tf.transform.rotation.z = q_z
            tf.transform.rotation.w = q_w
            self.tf_broadcaster.sendTransform(tf)

        # Publish Odometry message
        odom = Odometry()
        odom.header.stamp = now.to_msg()
        odom.header.frame_id = self.odom_frame
        odom.child_frame_id = self.base_frame
        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        odom.pose.pose.position.z = 0.0
        odom.pose.pose.orientation.x = 0.0
        odom.pose.pose.orientation.y = 0.0
        odom.pose.pose.orientation.z = q_z
        odom.pose.pose.orientation.w = q_w
        odom.twist.twist.linear.x = linear
        odom.twist.twist.angular.z = angular
        self.odom_pub.publish(odom)


def main(args=None):
    rclpy.init(args=args)
    node = OdomPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
