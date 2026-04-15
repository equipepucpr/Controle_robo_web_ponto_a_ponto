#!/usr/bin/env python3
"""
Robot base launch file.
Starts:
  1. robot_state_publisher (URDF / TF for body, wheels, laser)
  2. odom_publisher (computes odometry from hoverboard wheel feedback)
  3. cmd_vel_to_wheels (converts /cmd_vel_filtered -> /wheel_vel_setpoints)
"""

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, Command
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    pkg = get_package_share_directory('robot_nav')
    urdf_file = os.path.join(pkg, 'urdf', 'robot.urdf.xacro')

    # ---- Arguments ----
    wheel_radius_arg = DeclareLaunchArgument(
        'wheel_radius', default_value='0.085',
        description='Wheel radius in meters (measure your actual wheels)'
    )
    wheel_base_arg = DeclareLaunchArgument(
        'wheel_base', default_value='0.45',
        description='Wheel base (distance between wheel centers) in meters'
    )
    linear_scale_arg = DeclareLaunchArgument(
        'linear_scale', default_value='400.0',
        description='Hoverboard units per m/s for linear velocity'
    )
    angular_scale_arg = DeclareLaunchArgument(
        'angular_scale', default_value='150.0',
        description='Hoverboard units per rad/s for angular velocity'
    )

    # ---- Robot State Publisher (URDF + static TFs) ----
    robot_description = ParameterValue(
        Command(['xacro ', urdf_file]),
        value_type=str
    )

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_description}]
    )

    # ---- Odometry Publisher ----
    odom_publisher = Node(
        package='robot_nav',
        executable='odom_publisher',
        name='odom_publisher',
        output='screen',
        parameters=[{
            'wheel_radius': LaunchConfiguration('wheel_radius'),
            'wheel_base': LaunchConfiguration('wheel_base'),
        }]
    )

    # ---- cmd_vel -> wheel_vel_setpoints converter ----
    cmd_vel_to_wheels = Node(
        package='robot_nav',
        executable='cmd_vel_to_wheels',
        name='cmd_vel_to_wheels',
        output='screen',
        parameters=[{
            'linear_scale': LaunchConfiguration('linear_scale'),
            'angular_scale': LaunchConfiguration('angular_scale'),
            'cmd_vel_topic': 'cmd_vel',
        }]
    )

    return LaunchDescription([
        wheel_radius_arg,
        wheel_base_arg,
        linear_scale_arg,
        angular_scale_arg,
        robot_state_publisher,
        odom_publisher,
        cmd_vel_to_wheels,
    ])
