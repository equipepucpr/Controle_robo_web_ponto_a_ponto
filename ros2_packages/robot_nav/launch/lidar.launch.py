#!/usr/bin/env python3
"""
LiDAR launch file for FHL-LD20.

The FHL-LD20 uses the LDROBOT protocol. Try 'LDLiDAR_LD19' first (same protocol family).
If the scan is empty or has errors, try 'LDLiDAR_LD06'.

Parameters to check:
  - port_name: serial port of the LiDAR (run `ls /dev/ttyUSB*` to find it)
  - product_name: 'LDLiDAR_LD19' or 'LDLiDAR_LD06'
  - laser_scan_dir: True = counterclockwise, False = clockwise
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    port_arg = DeclareLaunchArgument(
        'lidar_port', default_value='/dev/ttyUSB1',
        description='Serial port for the FHL-LD20 LiDAR'
    )
    product_arg = DeclareLaunchArgument(
        'lidar_product', default_value='LDLiDAR_LD19',
        description='LiDAR product name: LDLiDAR_LD19 or LDLiDAR_LD06'
    )

    # ---- LiDAR driver node ----
    lidar_node = Node(
        package='ldlidar_stl_ros2',
        executable='ldlidar_stl_ros2_node',
        name='fhl_ld20',
        output='screen',
        parameters=[
            {'product_name': LaunchConfiguration('lidar_product')},
            {'topic_name': 'scan'},
            {'frame_id': 'base_laser'},
            {'port_name': LaunchConfiguration('lidar_port')},
            {'port_baudrate': 230400},
            {'laser_scan_dir': True},
            {'enable_angle_crop_func': False},
            {'angle_crop_min': 135.0},
            {'angle_crop_max': 225.0},
        ]
    )

    return LaunchDescription([
        port_arg,
        product_arg,
        lidar_node,
    ])
