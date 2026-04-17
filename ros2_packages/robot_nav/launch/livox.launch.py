#!/usr/bin/env python3
"""
Sobe o driver do Livox Mid-360 (livox_ros_driver2).

Saídas:
  /livox/lidar  (sensor_msgs/PointCloud2) em frame "livox_frame"
  /livox/imu    (sensor_msgs/Imu)         em frame "livox_frame"

O Mid-360 é Ethernet — o PC precisa estar na mesma subnet que o LiDAR
(default do Mid-360 é 192.168.1.1XX; o PC normalmente vai em 192.168.1.5).
Edite ros2_packages/robot_nav/config/mid360_config.json se seu IP for outro.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory('robot_nav')
    default_config = os.path.join(pkg, 'config', 'mid360_config.json')

    config_arg = DeclareLaunchArgument(
        'livox_config',
        default_value=default_config,
        description='Caminho do JSON de configuração do livox_ros_driver2'
    )
    frame_arg = DeclareLaunchArgument(
        'livox_frame_id',
        default_value='livox_frame',
        description='frame_id usado nas mensagens /livox/lidar e /livox/imu'
    )

    livox_driver = Node(
        package='livox_ros_driver2',
        executable='livox_ros_driver2_node',
        name='livox_driver',
        output='screen',
        parameters=[{
            'xfer_format': 0,              # 0 = PointCloud2
            'multi_topic': 0,
            'data_src': 0,                 # 0 = LiDAR físico
            'publish_freq': 10.0,
            'output_data_type': 0,
            'frame_id': LaunchConfiguration('livox_frame_id'),
            'user_config_path': LaunchConfiguration('livox_config'),
            'cmdline_input_bd_code': 'livox0000000001',
        }],
    )

    return LaunchDescription([
        config_arg,
        frame_arg,
        livox_driver,
    ])
