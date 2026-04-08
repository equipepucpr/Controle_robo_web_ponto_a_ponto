# Aplicação Flask com Socket.IO para receber eventos do navegador
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from controllers.robot_controller import RobotController, ROS2Controller
import logging
import os
import json
import time
import atexit
from logging.handlers import RotatingFileHandler

# Controlador ROS2 — publica em /wheel_vel_setpoints via wheel_msgs/msg/WheelSpeeds.
# Pré-requisito: source ~/ros2_ws/install/setup.bash antes de iniciar o servidor.
controller: RobotController = ROS2Controller()

# Encerra o nó ROS2 corretamente ao sair
atexit.register(lambda: controller.shutdown() if hasattr(controller, 'shutdown') else None)

# Instancia a aplicação web
app = Flask(__name__)
app.config['SECRET_KEY'] = 'change-me'
# Cria o servidor Socket.IO (tempo real) com logs habilitados
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    logger=True,
    engineio_logger=True,
    async_mode="eventlet",
)

# Configuração básica de logs no terminal
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

# Log de movimentos (JSON Lines) gravado em arquivo rotativo + arquivo legível
os.makedirs('logs', exist_ok=True)
movement_logger = logging.getLogger('movements')
movement_logger.setLevel(logging.INFO)
if not movement_logger.handlers:
    _mh = RotatingFileHandler('logs/movements.log', maxBytes=1_048_576, backupCount=5)
    _mh.setFormatter(logging.Formatter('%(message)s'))
    movement_logger.addHandler(_mh)
    # Logger adicional com linhas legíveis em português
    movement_human = logging.getLogger('movements_human')
    movement_human.setLevel(logging.INFO)
    _mht = RotatingFileHandler('logs/movements.txt', maxBytes=1_048_576, backupCount=5)
    _mht.setFormatter(logging.Formatter('%(message)s'))
    movement_human.addHandler(_mht)
else:
    movement_human = logging.getLogger('movements_human')

@app.before_request
def _log_request_start():
    # Loga início de cada requisição HTTP (método, rota, IP e user-agent)
    try:
        app.logger.info(f"HTTP {request.method} {request.path} from {request.remote_addr} UA={request.headers.get('User-Agent','-')}")
    except Exception:
        pass

@app.after_request
def _log_request_end(response):
    # Loga fim de cada requisição HTTP com status
    try:
        app.logger.info(f"HTTP {response.status_code} {request.method} {request.path}")
    except Exception:
        pass
    return response

@app.route('/')
def index():
    # Página principal com a interface do controle
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    # Evento de conexão de um cliente Socket.IO
    app.logger.info(f"Client connected: addr={request.remote_addr} sid={request.sid}")
    emit('server_status', {'message': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    # Evento de desconexão de um cliente Socket.IO
    app.logger.info(f"Client disconnected: addr={request.remote_addr} sid={request.sid}")

@socketio.on('key_event')
def handle_key_event(data):
    # Recebe um evento de tecla do cliente
    # Esperado: { type: 'down'|'up', key: 'KeyW'|'ArrowUp'|..., code: 'KeyW', repeat: bool, seq?: int }
    try:
        app.logger.info(f"key_event from {request.remote_addr}: {data}")
        # Encaminha o evento para o controlador do robô
        result = controller.handle_key_event(data)
        # Monta o registro padrão do evento para arquivo
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
        # Grava linha JSON no arquivo de movimentos
        movement_logger.info(json.dumps(entry, ensure_ascii=False))
        # Grava linha legível (português) no arquivo textual
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
        # Espelha no terminal uma versão humana do movimento
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

        # Envia ACK para o cliente (usado na UI para indicar "Recebido")
        emit('ack', {
            'ok': True,
            'seq': data.get('seq'),
            'type': entry['type'],
            'code': entry['code'],
            'action': entry.get('action'),
            'command': entry.get('command'),
        }, broadcast=False)
        # Eco opcional para debug na página (mantido comentado)
        # emit('server_echo', {'received': data}, broadcast=False)
    except Exception as e:
        # Em caso de erro, retorna ACK negativo com mensagem
        emit('ack', {
            'ok': False,
            'error': str(e),
            'seq': data.get('seq'),
            'type': data.get('type'),
            'code': data.get('code') or data.get('key'),
        }, broadcast=False)

@socketio.on('client_hello')
def handle_client_hello(payload):
    # Handshake simples para depuração (cliente informa dados básicos)
    app.logger.info(f"client_hello from {request.remote_addr} sid={request.sid} payload={payload}")
    emit('server_hello', {
        'sid': request.sid,
        'msg': 'hello from server',
    })

if __name__ == '__main__':
    # Sobe o servidor acessível na rede local (0.0.0.0:5000)
    app.logger.info("Starting Socket.IO server on 0.0.0.0:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False, log_output=True)
