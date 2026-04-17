#!/usr/bin/env python3
"""
Launch único do fork ponto-a-ponto.

Sobe, nessa ordem:
  1. robot_state_publisher (URDF com TFs estáticos base_link → rodas / livox_frame)
  2. odom_publisher (nav_msgs/Odometry em /wheel_odom, SEM publicar TF)
  3. cmd_vel_to_wheels
  4. livox_ros_driver2 (Livox Mid-360)          — opcional (no-lidar)
  5. FAST-LIO2 + static TFs (odom→camera_init, body→base_link) — opcional (no-lidar)
  6. waypoint_recorder
  7. waypoint_follower

O driver do hoverboard (pacote ros2-hoverboard-driver) continua fora deste
launch porque seu ciclo de vida depende do USB — o launch.sh de topo é
quem sobe/mata ele.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    pkg = get_package_share_directory('robot_nav')
    urdf_file = os.path.join(pkg, 'urdf', 'robot.urdf.xacro')

    use_lidar_arg = DeclareLaunchArgument(
        'use_lidar', default_value='true',
        description='Sobe Livox Mid-360 + FAST-LIO2 (false = teste puro da web).'
    )
    wheel_radius_arg = DeclareLaunchArgument('wheel_radius', default_value='0.085')
    wheel_base_arg = DeclareLaunchArgument('wheel_base', default_value='0.45')
    linear_scale_arg = DeclareLaunchArgument('linear_scale', default_value='400.0')
    angular_scale_arg = DeclareLaunchArgument('angular_scale', default_value='150.0')

    robot_description = ParameterValue(
        Command(['xacro ', urdf_file]), value_type=str
    )
    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_description}],
    )

    odom_publisher = Node(
        package='robot_nav',
        executable='odom_publisher',
        name='odom_publisher',
        output='screen',
        parameters=[{
            'wheel_radius': LaunchConfiguration('wheel_radius'),
            'wheel_base': LaunchConfiguration('wheel_base'),
            'publish_tf': False,
            'odom_topic': 'wheel_odom',
        }],
    )

    cmd_vel_to_wheels = Node(
        package='robot_nav',
        executable='cmd_vel_to_wheels',
        name='cmd_vel_to_wheels',
        output='screen',
        parameters=[{
            'linear_scale': LaunchConfiguration('linear_scale'),
            'angular_scale': LaunchConfiguration('angular_scale'),
            'cmd_vel_topic': 'cmd_vel',
        }],
    )

    # --- LiDAR stack (opcional) ---
    lidar_group = GroupAction(
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution([pkg, 'launch', 'livox.launch.py'])
                ),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution([pkg, 'launch', 'fast_lio.launch.py'])
                ),
            ),
        ],
        condition=IfCondition(LaunchConfiguration('use_lidar')),
    )

    # --- Waypoint recorder + follower ---
    waypoint_recorder = Node(
        package='robot_nav',
        executable='waypoint_recorder',
        name='waypoint_recorder',
        output='screen',
        parameters=[{'odometry_topic': '/Odometry'}],
    )
    waypoint_follower = Node(
        package='robot_nav',
        executable='waypoint_follower',
        name='waypoint_follower',
        output='screen',
        parameters=[{
            'odometry_topic': '/Odometry',
            'cmd_vel_topic': '/cmd_vel',
        }],
    )

    return LaunchDescription([
        use_lidar_arg,
        wheel_radius_arg,
        wheel_base_arg,
        linear_scale_arg,
        angular_scale_arg,
        robot_state_publisher,
        odom_publisher,
        cmd_vel_to_wheels,
        lidar_group,
        waypoint_recorder,
        waypoint_follower,
    ])
