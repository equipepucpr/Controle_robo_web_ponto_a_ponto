#!/usr/bin/env python3
"""
Sobe o FAST-LIO2 (hku-mars/FAST_LIO, branch ROS2) para o Livox Mid-360.

Saídas principais:
  /Odometry       (nav_msgs/Odometry) em frame "camera_init", child "body"
  /path           (nav_msgs/Path)
  /cloud_registered   (sensor_msgs/PointCloud2)
  TF camera_init -> body

Por compatibilidade com o resto do stack (que usa "odom" como frame de
referência), publicamos dois static TFs de alias:
  odom      -> camera_init   (identidade — renomeia o mundo)
  body      -> base_link     (inverso do offset do Mid-360 no URDF)

Assim a pose em /Odometry pode ser consumida direto e o TF tree conecta
o LiDAR ao corpo do robô.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory('robot_nav')
    default_cfg = os.path.join(pkg, 'config', 'fast_lio_mid360.yaml')

    cfg_arg = DeclareLaunchArgument(
        'fast_lio_config',
        default_value=default_cfg,
        description='YAML de parâmetros do FAST-LIO2'
    )

    # Alinhamento físico Mid-360 -> base_link.
    # No URDF o Mid-360 (livox_frame) está em (lidar_x, 0, body_height/2 + lidar_z)
    # = (0.10, 0, 0.17) acima do centro do base_link. Como queremos um TF de
    # body -> base_link, a translação é o inverso: (-0.10, 0, -0.17).
    mount_x = DeclareLaunchArgument(
        'mount_x', default_value='-0.10',
        description='Offset body->base_link em X (m). = -lidar_x do URDF.'
    )
    mount_z = DeclareLaunchArgument(
        'mount_z', default_value='-0.17',
        description='Offset body->base_link em Z (m). = -(body_height/2 + lidar_z) do URDF.'
    )

    fast_lio = Node(
        package='fast_lio',
        executable='fastlio_mapping',
        name='fast_lio_mapping',
        output='screen',
        parameters=[LaunchConfiguration('fast_lio_config')],
    )

    # odom -> camera_init (identidade). Torna "odom" sinônimo do frame mundo do LIO.
    odom_alias = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='odom_to_camera_init',
        arguments=['0', '0', '0', '0', '0', '0', 'odom', 'camera_init'],
        output='log',
    )

    # body -> base_link (monta o robô embaixo do Mid-360).
    body_to_base = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='body_to_base_link',
        arguments=[
            LaunchConfiguration('mount_x'), '0', LaunchConfiguration('mount_z'),
            '0', '0', '0',
            'body', 'base_link',
        ],
        output='log',
    )

    return LaunchDescription([
        cfg_arg,
        mount_x,
        mount_z,
        fast_lio,
        odom_alias,
        body_to_base,
    ])
