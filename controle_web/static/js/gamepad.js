(() => {
  // Módulo de controle via Gamepad API (PS4 / DualShock 4 / DualSense).
  // Lê os joysticks analogicamente e envia eventos proporcionais ao servidor.

  const socket = window._robotSocket;
  const appendLog = window._robotAppendLog;
  const deliveryEl = window._robotDeliveryEl;
  const getMode = window._robotGetMode;
  const sendSpeed = window._robotSendSpeed;
  const updateSpeedUI = window._robotUpdateSpeedUI;
  const getMultiplier = window._robotGetMultiplier;

  if (!socket) {
    console.warn('[Gamepad] Socket não encontrado — módulo desativado.');
    return;
  }

  // Elementos da UI do gamepad
  const gamepadStatusEl = document.getElementById('gamepad-status');
  const stickDot = document.getElementById('stick-dot');
  const stickViz = document.getElementById('stick-viz');
  const speedLeftBar = document.getElementById('speed-left');
  const speedRightBar = document.getElementById('speed-right');
  const speedLeftVal = document.getElementById('speed-left-val');
  const speedRightVal = document.getElementById('speed-right-val');
  const valLinear = document.getElementById('val-linear');
  const valAngular = document.getElementById('val-angular');

  // Elementos dos botões visuais
  const gpBtns = {
    cross: document.getElementById('gp-cross'),
    circle: document.getElementById('gp-circle'),
    square: document.getElementById('gp-square'),
    triangle: document.getElementById('gp-triangle'),
    l2: document.getElementById('gp-l2'),
    r2: document.getElementById('gp-r2'),
  };

  // Estado do gamepad
  let activeGamepadIndex = null;
  let pollTimer = null;
  let lastLinear = 0;
  let lastAngular = 0;
  let lastButtonState = {};
  let emergencyActive = false;
  let savedMultiplier = null; // salva multiplicador original ao segurar □ ou ○

  // Dead zone para os eixos analógicos
  const DEADZONE = 0.10;

  // Taxa de envio (ms) — não enviar mais rápido que isso
  const SEND_INTERVAL = 50; // 20 Hz
  let lastSendTime = 0;

  // Mapeamento de botões do gamepad padrão (Standard Gamepad)
  // PS4: Cross=0, Circle=1, Square=2, Triangle=3, L1=4, R1=5, L2=6, R2=7
  const BUTTON_MAP = {
    0: 'cross',
    1: 'circle',
    2: 'square',
    3: 'triangle',
    4: 'l1',
    5: 'r1',
    6: 'l2',
    7: 'r2',
    8: 'share',
    9: 'options',
    10: 'l3',
    11: 'r3',
    12: 'dpad_up',
    13: 'dpad_down',
    14: 'dpad_left',
    15: 'dpad_right',
    16: 'ps',
    17: 'touchpad',
  };

  function applyDeadzone(value) {
    if (Math.abs(value) < DEADZONE) return 0;
    // Remapeia o range de DEADZONE..1 para 0..1 (suaviza a transição)
    const sign = value > 0 ? 1 : -1;
    return sign * (Math.abs(value) - DEADZONE) / (1 - DEADZONE);
  }

  // Detecção de gamepad
  window.addEventListener('gamepadconnected', (e) => {
    appendLog('gamepad', `Conectado: ${e.gamepad.id}`);
    if (gamepadStatusEl) gamepadStatusEl.textContent = e.gamepad.id;
    activeGamepadIndex = e.gamepad.index;
    startPolling();

    // Auto-switch para modo gamepad quando conecta
    const gpBtn = document.getElementById('btn-mode-gamepad');
    if (gpBtn && getMode() === 'web') {
      gpBtn.click();
    }
  });

  window.addEventListener('gamepaddisconnected', (e) => {
    appendLog('gamepad', `Desconectado: ${e.gamepad.id}`);
    if (gamepadStatusEl) gamepadStatusEl.textContent = 'desconectado';
    if (activeGamepadIndex === e.gamepad.index) {
      activeGamepadIndex = null;
      stopPolling();
      // Envia stop ao desconectar
      socket.emit('gamepad_event', { type: 'axis', linear: 0, angular: 0 });
    }
  });

  function startPolling() {
    if (pollTimer) return;
    pollTimer = requestAnimationFrame(pollLoop);
  }

  function stopPolling() {
    if (pollTimer) {
      cancelAnimationFrame(pollTimer);
      pollTimer = null;
    }
  }

  function pollLoop() {
    pollTimer = requestAnimationFrame(pollLoop);

    if (getMode() !== 'gamepad') return;
    if (activeGamepadIndex === null) return;

    const gamepads = navigator.getGamepads();
    const gp = gamepads[activeGamepadIndex];
    if (!gp) return;

    // Eixos do stick esquerdo: axes[0]=X (esq/dir), axes[1]=Y (cima/baixo)
    // Nota: Y invertido (cima = negativo)
    const rawX = gp.axes[0] || 0;
    const rawY = gp.axes[1] || 0;

    let angular = applyDeadzone(rawX);   // esquerda(-) / direita(+)
    let linear = -applyDeadzone(rawY);   // frente(+) / ré(-)

    // Atualiza visualização do stick
    updateStickViz(rawX, rawY);

    // Atualiza exibição dos valores
    if (valLinear) valLinear.textContent = linear.toFixed(2);
    if (valAngular) valAngular.textContent = angular.toFixed(2);

    // Processa botões
    for (let i = 0; i < gp.buttons.length; i++) {
      const btn = gp.buttons[i];
      const name = BUTTON_MAP[i];
      if (!name) continue;

      const wasPressed = !!lastButtonState[name];
      const isPressed = btn.pressed;

      // Atualiza visual dos botões
      if (gpBtns[name]) {
        gpBtns[name].classList.toggle('active', isPressed);
      }

      // L2/R2 como multiplicador de velocidade (trigger analógico)
      // Não envia como evento de botão — usa o valor para escalar

      // Detecta mudança de estado (press/release)
      if (isPressed !== wasPressed) {
        lastButtonState[name] = isPressed;

        // Cross (X) = trava de emergência (segurar para travar)
        if (name === 'cross') {
          emergencyActive = isPressed;
          socket.emit('gamepad_event', {
            type: 'button',
            button: name,
            value: btn.value,
            pressed: isPressed,
          });
          if (isPressed) {
            appendLog('gamepad', 'TRAVA DE EMERGÊNCIA ATIVADA (✕ segurado)');
            updateSpeedBars(0, 0);
            if (valLinear) valLinear.textContent = '0.00';
            if (valAngular) valAngular.textContent = '0.00';
          } else {
            appendLog('gamepad', 'Trava de emergência desativada');
          }
        } else if (name === 'square') {
          // □ segurado = boost (2.0x)
          if (isPressed) {
            savedMultiplier = getMultiplier();
            sendSpeed(2.0);
            updateSpeedUI(2.0);
            appendLog('gamepad', 'Boost ativado (□)');
          } else {
            sendSpeed(savedMultiplier || 1.0);
            updateSpeedUI(savedMultiplier || 1.0);
            savedMultiplier = null;
            appendLog('gamepad', 'Boost desativado');
          }
        } else if (name === 'circle') {
          // ○ segurado = ajuste fino (0.75x)
          if (isPressed) {
            savedMultiplier = getMultiplier();
            sendSpeed(0.75);
            updateSpeedUI(0.75);
            appendLog('gamepad', 'Ajuste fino ativado (○)');
          } else {
            sendSpeed(savedMultiplier || 1.0);
            updateSpeedUI(savedMultiplier || 1.0);
            savedMultiplier = null;
            appendLog('gamepad', 'Ajuste fino desativado');
          }
        }
      }
    }

    // Trava ativa — não envia eixos, mantém tudo zerado
    if (emergencyActive) return;

    // Follower autônomo está publicando /cmd_vel — bloqueia teleop.
    if (window.isFollowerActive && window.isFollowerActive()) return;

    // Envia eixos com rate limiting
    const now = Date.now();
    const changed = Math.abs(linear - lastLinear) > 0.02 || Math.abs(angular - lastAngular) > 0.02;

    if (changed && (now - lastSendTime) >= SEND_INTERVAL) {
      lastLinear = linear;
      lastAngular = angular;
      lastSendTime = now;

      socket.emit('gamepad_event', {
        type: 'axis',
        linear: Math.round(linear * 100) / 100,
        angular: Math.round(angular * 100) / 100,
      });
    }
  }

  function updateStickViz(x, y) {
    if (!stickDot || !stickViz) return;
    // Mapeia -1..1 para posição dentro do container
    const rect = stickViz.getBoundingClientRect();
    const cx = rect.width / 2;
    const cy = rect.height / 2;
    const maxR = cx - 8; // margem para o ponto

    const px = cx + x * maxR;
    const py = cy + y * maxR;

    stickDot.style.left = px + 'px';
    stickDot.style.top = py + 'px';
  }

  function updateSpeedBars(left, right) {
    const maxSpeed = 100 * 4; // BASE_LINEAR_SPEED * SPEED_MULT_MAX
    if (speedLeftBar) {
      const pct = Math.min(Math.abs(left) / maxSpeed * 100, 100);
      speedLeftBar.style.width = pct + '%';
      speedLeftBar.className = 'speed-bar' + (left < 0 ? ' reverse' : '');
    }
    if (speedRightBar) {
      const pct = Math.min(Math.abs(right) / maxSpeed * 100, 100);
      speedRightBar.style.width = pct + '%';
      speedRightBar.className = 'speed-bar' + (right < 0 ? ' reverse' : '');
    }
    if (speedLeftVal) speedLeftVal.textContent = Math.round(left);
    if (speedRightVal) speedRightVal.textContent = Math.round(right);
  }

  // Atualiza indicador visual de trava de emergência
  function updateEmergencyUI(active) {
    const gamepadSection = document.getElementById('gamepad-controls');
    if (gamepadSection) {
      gamepadSection.classList.toggle('emergency', active);
    }
    if (gamepadStatusEl) {
      if (active) {
        gamepadStatusEl.textContent = 'TRAVA DE EMERGÊNCIA ATIVA (solte X)';
        gamepadStatusEl.style.color = '#ef4444';
      } else if (activeGamepadIndex !== null) {
        const gps = navigator.getGamepads();
        const gp = gps[activeGamepadIndex];
        gamepadStatusEl.textContent = gp ? gp.id : 'conectado';
        gamepadStatusEl.style.color = '';
      }
    }
  }

  // Recebe ACK do gamepad
  socket.on('gamepad_ack', (res) => {
    if (!res) return;
    if (res.ok) {
      // Atualiza estado de emergência pela resposta do servidor
      if (res.emergency != null) {
        updateEmergencyUI(res.emergency);
      }
      if (res.left_speed != null) {
        updateSpeedBars(res.left_speed, res.right_speed);
      }
      if (res.command) {
        const cmdPt = { forward: 'frente', backward: 'ré', left: 'esquerda', right: 'direita', stop: 'parar' };
        const actPt = { start: 'Iniciar', stop: 'Parar' };
        const human = `${actPt[res.action] || res.action} ${cmdPt[res.command] || res.command}`;
        if (deliveryEl) deliveryEl.textContent = emergencyActive
          ? `TRAVA ATIVA — ${human}`
          : `Gamepad: ${human}`;
      }
    } else {
      if (deliveryEl) deliveryEl.textContent = `Gamepad erro: ${res.error || '?'}`;
    }
  });
})();
