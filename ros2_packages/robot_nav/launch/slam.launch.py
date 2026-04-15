#!/usr/bin/env python3
"""
SLAM launch: slam_toolbox em modo online async.

Usa /scan (LiDAR) + /odom + TF (base_link, base_laser) para construir
um mapa 2D em tempo real. Depois de mapear, salve com:

    ros2 run nav2_map_server map_saver_cli -f ~/ros2_ws/maps/meu_mapa

E use o arquivo .yaml gerado com nav2.launch.py.

No modo sim (Gazebo), passe use_sim_time:=true para que o slam_toolbox
consuma o /clock simulado em vez do wall clock.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time', default_value='false',
        description='true no modo sim (usa /clock do Gazebo)',
    )
    use_sim_time = LaunchConfiguration('use_sim_time')

    slam = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'odom_frame': 'odom',
            'map_frame': 'map',
            'base_frame': 'base_link',
            'scan_topic': '/scan',
            'mode': 'mapping',
            'resolution': 0.05,
            'max_laser_range': 12.0,
            'minimum_time_interval': 0.2,
            'transform_publish_period': 0.05,
            'map_update_interval': 1.0,
            'use_lifecycle_manager': True,
            'transform_timeout': 0.5,
        }]
    )

    lifecycle_manager = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_slam',
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'autostart': True,
            'node_names': ['slam_toolbox'],
            'bond_timeout': 4.0,
        }]
    )

    return LaunchDescription([use_sim_time_arg, slam, lifecycle_manager])
