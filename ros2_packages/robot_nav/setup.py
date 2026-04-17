from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'robot_nav'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'urdf'), glob('urdf/*')),
        (os.path.join('share', package_name, 'config'), glob('config/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='user',
    maintainer_email='user@robot.com',
    description='Navigation and LiDAR integration for hoverboard robot',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'odom_publisher = robot_nav.odom_publisher:main',
            'cmd_vel_to_wheels = robot_nav.cmd_vel_to_wheels:main',
            'waypoint_recorder = robot_nav.waypoint_recorder:main',
            'waypoint_follower = robot_nav.waypoint_follower:main',
        ],
    },
)
