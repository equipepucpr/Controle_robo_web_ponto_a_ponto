#!/usr/bin/env python3
"""
Nav2 Collision Monitor launch file.

Starts the collision monitor which reads /scan and filters /cmd_vel
to prevent the robot from hitting obstacles.

Data flow:
  Web Interface -> /cmd_vel
  Collision Monitor: /cmd_vel + /scan -> /cmd_vel_filtered
  cmd_vel_to_wheels: /cmd_vel_filtered -> /wheel_vel_setpoints
"""

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory('robot_nav')
    params_file = os.path.join(pkg, 'config', 'collision_monitor.yaml')

    collision_monitor = Node(
        package='nav2_collision_monitor',
        executable='collision_monitor',
        name='collision_monitor',
        output='screen',
        parameters=[params_file],
        remappings=[
            ('cmd_vel_in', 'cmd_vel'),
            ('cmd_vel_out', 'cmd_vel_filtered'),
        ]
    )

    lifecycle_manager = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_collision',
        output='screen',
        parameters=[{
            'autostart': True,
            'node_names': ['collision_monitor'],
            'bond_timeout': 4.0,
        }]
    )

    return LaunchDescription([
        collision_monitor,
        lifecycle_manager,
    ])
