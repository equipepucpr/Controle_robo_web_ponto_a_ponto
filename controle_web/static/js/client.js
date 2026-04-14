(() => {
  // Script do cliente: captura teclado/botões, envia eventos via Socket.IO
  // e exibe status de conexão e confirmação de entrega (ACK) do servidor.
  // Também gerencia o modo de controle (web vs gamepad).

  const connEl = document.getElementById('conn');
  const pressedEl = document.getElementById('pressed');
  const logEl = document.getElementById('log');
  const deliveryEl = document.getElementById('delivery');
  const modeDisplay = document.getElementById('mode-display');
  const pressedRow = document.getElementById('pressed-row');
  const gamepadStatusRow = document.getElementById('gamepad-status-row');
  const webControls = document.getElementById('web-controls');
  const gamepadControls = document.getElementById('gamepad-controls');

  // Rastreia teclas pressionadas para evitar flood por autorepeat
  const pressed = new Set();

  // Modo ativo: 'web' ou 'gamepad'
  let controlMode = 'web';

  // Prefere polling e faz upgrade para websocket (melhor compatibilidade)
  const socket = io({ transports: ['polling', 'websocket'] });
  // Exposto para outros scripts (map.js) reutilizarem a mesma conexão
  window.robotSocket = socket;

  // --- Controle de velocidade (compartilhado entre modos) ---
  const speedSlider = document.getElementById('speed-slider');
  const speedMultDisplay = document.getElementById('speed-mult-display');
  const speedLinearVal = document.getElementById('speed-linear-val');
  const speedAngularVal = document.getElementById('speed-angular-val');
  const BASE_LINEAR = 100;
  const BASE_ANGULAR = 65;
  let currentMultiplier = 1.0;

  function updateSpeedUI(mult, linearSpeed, angularSpeed) {
    currentMultiplier = mult;
    if (speedSlider) speedSlider.value = mult;
    if (speedMultDisplay) speedMultDisplay.textContent = mult.toFixed(1) + 'x';
    if (speedLinearVal) speedLinearVal.textContent = Math.round(linearSpeed || BASE_LINEAR * mult);
    if (speedAngularVal) speedAngularVal.textContent = Math.round(angularSpeed || BASE_ANGULAR * mult);
    // Destaca o preset ativo
    document.querySelectorAll('.speed-preset-btn').forEach(b => {
      const bm = parseFloat(b.getAttribute('data-mult'));
      b.classList.toggle('active', Math.abs(bm - mult) < 0.05);
    });
  }

  function sendSpeed(mult) {
    socket.emit('set_speed', { multiplier: mult });
  }

  if (speedSlider) {
    speedSlider.addEventListener('input', () => {
      const mult = parseFloat(speedSlider.value);
      updateSpeedUI(mult);
      sendSpeed(mult);
    });
  }

  document.querySelectorAll('.speed-preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const mult = parseFloat(btn.getAttribute('data-mult'));
      updateSpeedUI(mult);
      sendSpeed(mult);
    });
  });

  socket.on('speed_update', (data) => {
    if (data && data.ok) {
      updateSpeedUI(data.multiplier, data.linear_speed, data.angular_speed);
      appendLog('vel', `Velocidade: ${data.multiplier.toFixed(1)}x (L=${Math.round(data.linear_speed)} A=${Math.round(data.angular_speed)})`);
    }
  });

  // Expõe socket e helpers para o módulo gamepad
  window._robotSocket = socket;
  window._robotAppendLog = appendLog;
  window._robotDeliveryEl = deliveryEl;
  window._robotGetMode = () => controlMode;
  window._robotSendSpeed = sendSpeed;
  window._robotUpdateSpeedUI = updateSpeedUI;
  window._robotGetMultiplier = () => currentMultiplier;

  // Sequência incremental para correlacionar ACKs (confirmação)
  let seq = 0;
  const pending = new Map(); // seq -> {code, type, timer}

  // --- Seletor de modo ---
  document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = btn.getAttribute('data-mode');
      if (mode === controlMode) return;
      controlMode = mode;

      document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      if (mode === 'web') {
        modeDisplay.textContent = 'Teclado / Web';
        pressedRow.style.display = '';
        gamepadStatusRow.style.display = 'none';
        webControls.style.display = '';
        gamepadControls.style.display = 'none';
      } else {
        modeDisplay.textContent = 'Controle PS4';
        pressedRow.style.display = 'none';
        gamepadStatusRow.style.display = '';
        webControls.style.display = 'none';
        gamepadControls.style.display = '';
        // Limpa teclas pressionadas ao trocar para gamepad
        pressed.clear();
        renderPressed();
      }
      appendLog('modo', `Alterado para: ${modeDisplay.textContent}`);
    });
  });

  socket.on('connect', () => {
    connEl.textContent = 'conectado';
    const transport = socket.io.engine.transport && socket.io.engine.transport.name;
    appendLog('socket', `conectado sid=${socket.id} transport=${transport || 'n/a'}`);
    try {
      socket.emit('client_hello', {
        ts: Date.now(),
        href: location.href,
        ua: navigator.userAgent,
      });
    } catch (e) {
      console.error('hello emit failed', e);
    }
  });

  socket.on('disconnect', () => {
    connEl.textContent = 'desconectado';
    pressed.clear();
    renderPressed();
    appendLog('socket', 'desconectado');
    if (deliveryEl) deliveryEl.textContent = 'desconectado';
  });

  socket.on('connect_error', (err) => {
    appendLog('socket', `connect_error: ${err?.message || err}`);
    console.error('connect_error', err);
  });

  socket.on('error', (err) => {
    appendLog('socket', `error: ${err?.message || err}`);
    console.error('socket error', err);
  });

  socket.on('reconnect_error', (err) => {
    appendLog('socket', `reconnect_error: ${err?.message || err}`);
    console.error('reconnect_error', err);
  });

  socket.on('server_status', (data) => {
    connEl.textContent = 'conectado';
    appendLog('socket', 'conectado');
  });

  socket.on('server_hello', (data) => {
    appendLog('server', `hello sid=${data?.sid || '-'} ok`);
  });

  socket.on('ack', (res) => {
    const { ok, seq: rseq, type, code, action, command, error } = res || {};
    if (pending.has(rseq)) {
      const item = pending.get(rseq);
      clearTimeout(item.timer);
      pending.delete(rseq);
    }
    const human = humanize(type, code, action, command);
    if (ok) {
      if (deliveryEl) deliveryEl.textContent = `Recebido: ${human}`;
      appendLog('ok', `Recebido: ${human}`);
    } else {
      if (deliveryEl) deliveryEl.textContent = `Não recebido: ${human} (${error || 'erro'})`;
      appendLog('fail', `Não recebido: ${human} (${error || 'erro'})`);
    }
  });

  function send(type, code, repeat) {
    const id = ++seq;
    const payload = { type, code, repeat: !!repeat, seq: id };
    const timer = setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id);
        const human = humanize(type, code);
        if (deliveryEl) deliveryEl.textContent = `Não recebido: ${human} (timeout)`;
        appendLog('timeout', `Não recebido: ${human} (timeout)`);
      }
    }, 2000);
    pending.set(id, { code, type, timer });
    socket.emit('key_event', payload);
  }

  function renderPressed() {
    if (pressed.size === 0) {
      pressedEl.textContent = '(nenhuma)';
    } else {
      pressedEl.textContent = Array.from(pressed).join(', ');
    }
  }

  function appendLog(tag, message) {
    if (!logEl) return;
    const ts = new Date().toLocaleTimeString();
    const li = document.createElement('li');
    li.textContent = `[${ts}] ${tag}: ${message}`;
    logEl.prepend(li);
    while (logEl.children.length > 50) {
      logEl.removeChild(logEl.lastChild);
    }
  }

  // Listeners de teclado (só ativos no modo web)
  window.addEventListener('keydown', (e) => {
    if (controlMode !== 'web') return;
    const code = e.code || e.key;
    if (!pressed.has(code)) {
      pressed.add(code);
      send('down', code, e.repeat);
      renderPressed();
    }
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space'].includes(code)) {
      e.preventDefault();
    }
  }, { passive: false });

  window.addEventListener('keyup', (e) => {
    if (controlMode !== 'web') return;
    const code = e.code || e.key;
    if (pressed.has(code)) {
      pressed.delete(code);
      send('up', code, e.repeat);
      renderPressed();
    }
  });

  // Botões de toque/clique (suporte mobile) + diagonais via data-combo
  function setupPad(button) {
    const comboAttr = button.getAttribute('data-combo');
    const codes = comboAttr
      ? comboAttr.split(',').map((s) => s.trim()).filter(Boolean)
      : [button.getAttribute('data-code')].filter(Boolean);

    const down = () => {
      if (controlMode !== 'web') return;
      let changed = false;
      for (const code of codes) {
        if (!pressed.has(code)) {
          pressed.add(code);
          send('down', code, false);
          changed = true;
        }
      }
      if (changed) renderPressed();
    };
    const up = () => {
      if (controlMode !== 'web') return;
      let changed = false;
      for (const code of codes) {
        if (pressed.has(code)) {
          pressed.delete(code);
          send('up', code, false);
          changed = true;
        }
      }
      if (changed) renderPressed();
    };
    button.addEventListener('mousedown', down);
    button.addEventListener('mouseup', up);
    button.addEventListener('mouseleave', up);
    button.addEventListener('touchstart', (e) => { e.preventDefault(); down(); }, { passive: false });
    button.addEventListener('touchend', (e) => { e.preventDefault(); up(); }, { passive: false });
    button.addEventListener('touchcancel', (e) => { e.preventDefault(); up(); }, { passive: false });
  }

  document.querySelectorAll('.pad').forEach(setupPad);

  function humanize(type, code, action, command) {
    const cmdPt = { forward: 'frente', backward: 'ré', left: 'esquerda', right: 'direita', stop: 'parar' };
    const actPt = { start: 'Iniciar', stop: 'Parar' };
    if (action && command && cmdPt[command] && actPt[action]) {
      return `${actPt[action]} ${cmdPt[command]} (${code})`;
    }
    const typPt = { down: 'pressionar', up: 'soltar' };
    return `${typPt[type] || type} ${code}`;
  }

  // ---- LiDAR: painel de obstáculos ----
  const lidarBadge    = document.getElementById('lidar-badge');
  const obstacleCls   = document.getElementById('obstacle-closest');
  const SETOR_IDS = ['frente', 'frente_esq', 'frente_dir', 'esquerda', 'direita', 'tras'];
  const SETOR_LABELS  = {
    frente: 'FRENTE', frente_esq: 'F-ESQ', frente_dir: 'F-DIR',
    esquerda: 'ESQ', direita: 'DIR', tras: 'TRÁS',
  };

  function _distStr(d) {
    if (d === null || d === undefined) return '—';
    return d < 10 ? d.toFixed(2) + 'm' : d.toFixed(1) + 'm';
  }

  function _angleName(deg) {
    if (deg === null || deg === undefined) return '';
    const abs = Math.abs(deg);
    const side = deg >= 0 ? 'esq' : 'dir';
    if (abs <= 30)  return 'frente';
    if (abs <= 90)  return `frente-${side}`;
    if (abs <= 135) return side === 'esq' ? 'esquerda' : 'direita';
    return 'trás';
  }

  socket.on('obstacle_info', (data) => {
    if (!data) return;

    // Badge de conexão
    if (lidarBadge) {
      lidarBadge.textContent = data.conectado ? 'LiDAR ON' : 'sem sinal';
      lidarBadge.className = 'lidar-badge ' + (data.conectado ? 'on' : 'off');
    }

    // Obstáculo mais próximo (destaque)
    if (obstacleCls && data.mais_proximo) {
      const mp = data.mais_proximo;
      if (mp.dist !== null) {
        const dir = _angleName(mp.angulo);
        obstacleCls.textContent = `Mais próximo: ${_distStr(mp.dist)} @ ${dir}`;
        obstacleCls.style.color = mp.cor === 'vermelho' ? '#f87171'
                                : mp.cor === 'amarelo'  ? '#facc15' : '#4ade80';
      } else {
        obstacleCls.textContent = 'Sem obstáculos detectados';
        obstacleCls.style.color = '#4ade80';
      }
    }

    // Setores
    if (data.setores) {
      for (const key of SETOR_IDS) {
        const s = data.setores[key];
        const cell  = document.getElementById('obs-' + key);
        const distEl = document.getElementById('dist-' + key);
        if (!cell || !distEl || !s) continue;
        const cor = s.cor || 'verde';
        cell.className  = 'obs-sector' + (key === 'frente' || key === 'tras' ? ' obs-center' : '') + ' ' + cor;
        distEl.className = 'obs-dist ' + cor;
        distEl.textContent = _distStr(s.dist);
      }
    }
  });
})();
