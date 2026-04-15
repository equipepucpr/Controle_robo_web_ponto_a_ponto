#!/usr/bin/env python3
"""
Launch Nav2 completo (AMCL + planner + controller + bt_navigator +
waypoint_follower + behavior_server + velocity_smoother + costmaps),
consumindo um mapa estático previamente gerado com slam_toolbox.

Uso:
    ros2 launch robot_nav nav2.launch.py map:=/home/ubuntu/ros2_ws/maps/meu_mapa.yaml
"""

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory('robot_nav')
    params_file = os.path.join(pkg, 'config', 'nav2_params.yaml')

    map_arg = DeclareLaunchArgument(
        'map', default_value='',
        description='Caminho para o arquivo .yaml do mapa gerado pelo slam_toolbox'
    )
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time', default_value='false',
        description='true no modo sim (usa /clock do Gazebo)',
    )
    map_yaml = LaunchConfiguration('map')
    use_sim_time = LaunchConfiguration('use_sim_time')

    lifecycle_nodes = [
        'map_server',
        'amcl',
        'controller_server',
        'planner_server',
        'behavior_server',
        'bt_navigator',
        'waypoint_follower',
        'velocity_smoother',
    ]

    sim_time_param = {'use_sim_time': use_sim_time}

    nodes = [
        Node(
            package='nav2_map_server', executable='map_server', name='map_server',
            output='screen',
            parameters=[params_file, sim_time_param, {'yaml_filename': map_yaml}],
        ),
        Node(
            package='nav2_amcl', executable='amcl', name='amcl',
            output='screen', parameters=[params_file, sim_time_param],
        ),
        Node(
            package='nav2_controller', executable='controller_server',
            name='controller_server', output='screen',
            parameters=[params_file, sim_time_param],
            remappings=[('cmd_vel', 'cmd_vel_nav')],
        ),
        Node(
            package='nav2_planner', executable='planner_server',
            name='planner_server', output='screen',
            parameters=[params_file, sim_time_param],
        ),
        Node(
            package='nav2_behaviors', executable='behavior_server',
            name='behavior_server', output='screen',
            parameters=[params_file, sim_time_param],
            remappings=[('cmd_vel', 'cmd_vel_nav')],
        ),
        Node(
            package='nav2_bt_navigator', executable='bt_navigator',
            name='bt_navigator', output='screen',
            parameters=[params_file, sim_time_param],
        ),
        Node(
            package='nav2_waypoint_follower', executable='waypoint_follower',
            name='waypoint_follower', output='screen',
            parameters=[params_file, sim_time_param],
        ),
        Node(
            package='nav2_velocity_smoother', executable='velocity_smoother',
            name='velocity_smoother', output='screen',
            parameters=[params_file, sim_time_param],
            remappings=[('cmd_vel', 'cmd_vel_nav'), ('cmd_vel_smoothed', 'cmd_vel')],
        ),
        Node(
            package='nav2_lifecycle_manager', executable='lifecycle_manager',
            name='lifecycle_manager_navigation', output='screen',
            parameters=[{
                'use_sim_time': use_sim_time,
                'autostart': True,
                'node_names': lifecycle_nodes,
                'bond_timeout': 4.0,
            }],
        ),
    ]

    return LaunchDescription([map_arg, use_sim_time_arg, *nodes])
