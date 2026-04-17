# Aplicação Flask com Socket.IO para o fork ponto-a-ponto.
# Teleop manual + gravação/reprodução de waypoints com pose do FAST-LIO2.
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from controllers.robot_controller import RobotController, ROS2Controller
from controllers.waypoint_bridge import WaypointBridge
import logging
import os
import json
import signal
import sys
import time
import atexit
from logging.handlers import RotatingFileHandler

# Controlador ROS2 — publica em /cmd_vel (geometry_msgs/Twist) via teleop.
# Pré-requisito: source ~/ros2_ws/install/setup.bash antes de iniciar o servidor.
controller: RobotController = ROS2Controller()

# Ponte ROS2 ↔ Socket.IO para pose / waypoints / follower.
waypoint_bridge: WaypointBridge | None = None

# rclpy.init() instala seus próprios handlers de SIGINT/SIGTERM que engolem o
# Ctrl+C. Sobrescreve com handlers Python que fazem shutdown limpo.
_shutting_down = False


def _shutdown_all():
    try:
        if waypoint_bridge is not None:
            waypoint_bridge.shutdown()
    except Exception:
        pass
    try:
        if hasattr(controller, 'shutdown'):
            controller.shutdown()
    except Exception:
        pass


def _force_shutdown_full(signum, _frame):
    global _shutting_down
    if _shutting_down:
        os._exit(1)
    _shutting_down = True
    print(f"\n[app] Sinal {signum} recebido, encerrando...", flush=True)
    _shutdown_all()
    os._exit(0)


signal.signal(signal.SIGINT,  _force_shutdown_full)
signal.signal(signal.SIGTERM, _force_shutdown_full)
atexit.register(_shutdown_all)

# Instancia a aplicação web
app = Flask(__name__)
app.config['SECRET_KEY'] = 'change-me'
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
    async_mode="threading",
)

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# ---- Ponte de waypoints (ROS2 ↔ Socket.IO) ----
try:
    waypoint_bridge = WaypointBridge(socketio=socketio)
except Exception as e:
    logging.getLogger(__name__).warning(
        f"[app] Falha ao iniciar WaypointBridge: {e}. Pose e waypoints desabilitados."
    )
    waypoint_bridge = None

# Log de movimentos (JSON Lines) gravado em arquivo rotativo + arquivo legível
os.makedirs('logs', exist_ok=True)
movement_logger = logging.getLogger('movements')
movement_logger.setLevel(logging.INFO)
if not movement_logger.handlers:
    _mh = RotatingFileHandler('logs/movements.log', maxBytes=1_048_576, backupCount=5)
    _mh.setFormatter(logging.Formatter('%(message)s'))
    movement_logger.addHandler(_mh)
    movement_human = logging.getLogger('movements_human')
    movement_human.setLevel(logging.INFO)
    _mht = RotatingFileHandler('logs/movements.txt', maxBytes=1_048_576, backupCount=5)
    _mht.setFormatter(logging.Formatter('%(message)s'))
    movement_human.addHandler(_mht)
else:
    movement_human = logging.getLogger('movements_human')


@app.before_request
def _log_request_start():
    try:
        app.logger.info(f"HTTP {request.method} {request.path} from {request.remote_addr} UA={request.headers.get('User-Agent','-')}")
    except Exception:
        pass


@app.after_request
def _log_request_end(response):
    try:
        app.logger.info(f"HTTP {response.status_code} {request.method} {request.path}")
    except Exception:
        pass
    return response


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    app.logger.info(f"Client connected: addr={request.remote_addr} sid={request.sid}")
    emit('server_status', {
        'message': 'connected',
        'has_pose_bridge': waypoint_bridge is not None,
    })


@socketio.on('disconnect')
def handle_disconnect():
    app.logger.info(f"Client disconnected: addr={request.remote_addr} sid={request.sid}")


# ---- Handlers de waypoints ----

def _require_bridge(ack_event: str) -> bool:
    if waypoint_bridge is None:
        emit(ack_event, {'ok': False, 'error': 'ponte ROS2 indisponível'})
        return False
    return True


@socketio.on('record_waypoint')
def handle_record_waypoint(_data=None):
    if not _require_bridge('wp_ack'):
        return
    result = waypoint_bridge.record_waypoint()
    app.logger.info(f"record_waypoint from {request.remote_addr}: {result}")
    emit('wp_ack', {'op': 'record', **result})


@socketio.on('clear_waypoints')
def handle_clear_waypoints(_data=None):
    if not _require_bridge('wp_ack'):
        return
    result = waypoint_bridge.clear_waypoints()
    app.logger.info(f"clear_waypoints from {request.remote_addr}: {result}")
    emit('wp_ack', {'op': 'clear', **result})


@socketio.on('reset_origin')
def handle_reset_origin(_data=None):
    if not _require_bridge('wp_ack'):
        return
    result = waypoint_bridge.reset_origin()
    app.logger.info(f"reset_origin from {request.remote_addr}: {result}")
    emit('wp_ack', {'op': 'reset_origin', **result})


@socketio.on('start_follow')
def handle_start_follow(_data=None):
    if not _require_bridge('follow_ack'):
        return
    result = waypoint_bridge.start_follow()
    app.logger.info(f"start_follow from {request.remote_addr}: {result}")
    emit('follow_ack', {'op': 'start', **result})


@socketio.on('stop_follow')
def handle_stop_follow(_data=None):
    if not _require_bridge('follow_ack'):
        return
    result = waypoint_bridge.stop_follow()
    app.logger.info(f"stop_follow from {request.remote_addr}: {result}")
    emit('follow_ack', {'op': 'stop', **result})


@socketio.on('return_to_origin')
def handle_return_to_origin(_data=None):
    if not _require_bridge('follow_ack'):
        return
    result = waypoint_bridge.return_to_origin()
    app.logger.info(f"return_to_origin from {request.remote_addr}: {result}")
    emit('follow_ack', {'op': 'return', **result})


# ---- Teleop ----

@socketio.on('key_event')
def handle_key_event(data):
    try:
        app.logger.info(f"key_event from {request.remote_addr}: {data}")
        result = controller.handle_key_event(data)
        entry = {
            'ts': time.time(),
            'addr': request.remote_addr,
            'sid': request.sid,
            'type': data.get('type'),
            'code': data.get('code') or data.get('key'),
            'repeat': bool(data.get('repeat', False)),
        }
        if isinstance(result, dict):
            entry.update({
                'action': result.get('action'),
                'command': result.get('command'),
            })
        movement_logger.info(json.dumps(entry, ensure_ascii=False))
        try:
            ts_readable = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(entry['ts']))
            if entry.get('action') and entry.get('command'):
                cmd_pt = {'forward': 'frente', 'backward': 'ré', 'left': 'esquerda', 'right': 'direita', 'stop': 'parar'}
                act_pt = {'start': 'Iniciar', 'stop': 'Parar'}
                movement_human.info(f"[{ts_readable}] {entry['addr']} {act_pt.get(entry['action'], entry['action'])} {cmd_pt.get(entry['command'], entry['command'])} (code={entry['code']}) sid={entry['sid']}")
            else:
                movement_human.info(f"[{ts_readable}] {entry['addr']} {entry['type']} {entry['code']} sid={entry['sid']}")
        except Exception:
            pass
        try:
            human = entry.get('action') and entry.get('command')
            if human:
                cmd_pt = {'forward': 'frente', 'backward': 'ré', 'left': 'esquerda', 'right': 'direita', 'stop': 'parar'}
                act_pt = {'start': 'Iniciar', 'stop': 'Parar'}
                app.logger.info(f"[Mov] {act_pt.get(entry['action'], entry['action'])} {cmd_pt.get(entry['command'], entry['command'])} (code={entry['code']}) from {entry['addr']}")
            else:
                app.logger.info(f"[Mov] {entry['type']} {entry['code']} from {entry['addr']}")
        except Exception:
            pass

        emit('ack', {
            'ok': True,
            'seq': data.get('seq'),
            'type': entry['type'],
            'code': entry['code'],
            'action': entry.get('action'),
            'command': entry.get('command'),
        }, broadcast=False)
    except Exception as e:
        emit('ack', {
            'ok': False,
            'error': str(e),
            'seq': data.get('seq'),
            'type': data.get('type'),
            'code': data.get('code') or data.get('key'),
        }, broadcast=False)


@socketio.on('gamepad_event')
def handle_gamepad_event(data):
    try:
        app.logger.info(f"gamepad_event from {request.remote_addr}: type={data.get('type')} L={data.get('linear','?')} A={data.get('angular','?')}")
        result = controller.handle_gamepad_event(data)

        entry = {
            'ts': time.time(),
            'addr': request.remote_addr,
            'sid': request.sid,
            'input': 'gamepad',
            'type': data.get('type'),
        }
        if data.get('type') == 'axis':
            entry['linear'] = data.get('linear')
            entry['angular'] = data.get('angular')
        elif data.get('type') == 'button':
            entry['button'] = data.get('button')
            entry['pressed'] = data.get('pressed')

        if isinstance(result, dict):
            entry.update({
                'action': result.get('action'),
                'command': result.get('command'),
                'left_speed': result.get('left_speed'),
                'right_speed': result.get('right_speed'),
            })

        movement_logger.info(json.dumps(entry, ensure_ascii=False))

        try:
            ts_readable = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(entry['ts']))
            if entry.get('action') and entry.get('command'):
                cmd_pt = {'forward': 'frente', 'backward': 'ré', 'left': 'esquerda', 'right': 'direita', 'stop': 'parar'}
                act_pt = {'start': 'Iniciar', 'stop': 'Parar'}
                extra = ''
                if entry.get('left_speed') is not None:
                    extra = f" L={entry['left_speed']:.0f} R={entry['right_speed']:.0f}"
                movement_human.info(f"[{ts_readable}] {entry['addr']} [GAMEPAD] {act_pt.get(entry['action'], entry['action'])} {cmd_pt.get(entry['command'], entry['command'])}{extra} sid={entry['sid']}")
            else:
                movement_human.info(f"[{ts_readable}] {entry['addr']} [GAMEPAD] {entry['type']} btn={entry.get('button','-')} sid={entry['sid']}")
        except Exception:
            pass

        try:
            if result and result.get('command'):
                cmd_pt = {'forward': 'frente', 'backward': 'ré', 'left': 'esquerda', 'right': 'direita', 'stop': 'parar'}
                act_pt = {'start': 'Iniciar', 'stop': 'Parar'}
                app.logger.info(f"[Gamepad] {act_pt.get(result['action'], result['action'])} {cmd_pt.get(result['command'], result['command'])} L={result.get('left_speed',0):.0f} R={result.get('right_speed',0):.0f} from {entry['addr']}")
        except Exception:
            pass

        emit('gamepad_ack', {
            'ok': True,
            'command': result.get('command') if result else None,
            'action': result.get('action') if result else None,
            'left_speed': result.get('left_speed') if result else None,
            'right_speed': result.get('right_speed') if result else None,
            'emergency': result.get('emergency') if result else None,
        }, broadcast=False)
    except Exception as e:
        emit('gamepad_ack', {
            'ok': False,
            'error': str(e),
        }, broadcast=False)


@socketio.on('set_speed')
def handle_set_speed(data):
    try:
        mult = float(data.get('multiplier', 1.0))
        effective = controller.set_speed_multiplier(mult)
        app.logger.info(f"set_speed from {request.remote_addr}: mult={mult:.2f} → effective={effective:.2f}")
        emit('speed_update', {
            'ok': True,
            'multiplier': effective,
            'linear_speed': controller._linear_speed,
            'angular_speed': controller._angular_speed,
        }, broadcast=True)
    except Exception as e:
        emit('speed_update', {'ok': False, 'error': str(e)}, broadcast=False)


@socketio.on('client_hello')
def handle_client_hello(payload):
    app.logger.info(f"client_hello from {request.remote_addr} sid={request.sid} payload={payload}")
    emit('server_hello', {
        'sid': request.sid,
        'msg': 'hello from server',
    })


if __name__ == '__main__':
    app.logger.info("Starting Socket.IO server on 0.0.0.0:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
