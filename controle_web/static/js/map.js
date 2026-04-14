(() => {
  // Cliente do painel de mapa — renderiza OccupancyGrid (PNG recebido via
  // socket.io), pose do robô (TF map→base_link) e trajetória planejada do Nav2.
  // Click no canvas envia /goal_pose (só no modo NAV2).
  //
  // O `socket` aqui é o mesmo criado por client.js — acessamos via window.
  const panel       = document.getElementById('map-panel');
  const canvas      = document.getElementById('map-canvas');
  const ctx         = canvas.getContext('2d');
  const statusEl    = document.getElementById('map-status');
  const sizeEl      = document.getElementById('map-info-size');
  const resEl       = document.getElementById('map-info-res');
  const poseEl      = document.getElementById('map-robot-pose');
  const clickHint   = document.getElementById('map-click-hint');
  const btnSave     = document.getElementById('btn-save-map');
  const modeBadge   = document.getElementById('robot-mode-badge');

  // Estado local — atualizado por eventos socket.io
  let currentMode = 'teleop';
  let mapInfo = null;      // { width, height, resolution, origin_x, origin_y, ... }
  let mapImage = null;     // Image carregada do PNG base64
  let robotPose = null;    // { x, y, yaw }
  let plan = [];           // [{ x, y }]
  let lastGoal = null;     // { x, y }

  // Espera o socket de client.js existir. client.js cria `window.robotSocket`.
  function waitForSocket(cb) {
    if (window.robotSocket) return cb(window.robotSocket);
    setTimeout(() => waitForSocket(cb), 50);
  }

  waitForSocket((socket) => {
    socket.on('mode_info', (data) => {
      currentMode = (data && data.mode) || 'teleop';
      modeBadge.textContent = currentMode.toUpperCase();
      modeBadge.className = 'mode-badge mode-' + currentMode;

      if (currentMode === 'slam' || currentMode === 'nav2') {
        panel.style.display = '';
        btnSave.disabled = false;
        clickHint.textContent = currentMode === 'nav2'
          ? '(clique no mapa para enviar o robô até o ponto)'
          : '(mapeando em tempo real)';
      } else {
        panel.style.display = 'none';
      }
    });

    socket.on('map_update', (data) => {
      if (!data || !data.info || !data.png_b64) return;
      mapInfo = data.info;
      const img = new Image();
      img.onload = () => {
        mapImage = img;
        sizeEl.textContent = `${mapInfo.width} × ${mapInfo.height} px`;
        resEl.textContent  = `${mapInfo.resolution.toFixed(3)} m/px`;
        statusEl.textContent = 'recebido';
        statusEl.className = 'map-status ok';
        render();
      };
      img.src = 'data:image/png;base64,' + data.png_b64;
    });

    socket.on('robot_pose', (data) => {
      robotPose = data;
      poseEl.textContent = `robô: x=${data.x.toFixed(2)} y=${data.y.toFixed(2)} yaw=${(data.yaw * 180 / Math.PI).toFixed(0)}°`;
      render();
    });

    socket.on('plan_update', (data) => {
      plan = (data && data.points) || [];
      render();
    });

    socket.on('nav_goal_ack', (data) => {
      if (!data.ok) {
        statusEl.textContent = 'erro: ' + (data.error || '?');
        statusEl.className = 'map-status err';
      } else {
        statusEl.textContent = `indo para (${data.x.toFixed(2)}, ${data.y.toFixed(2)})`;
        statusEl.className = 'map-status ok';
      }
    });

    socket.on('save_map_ack', (data) => {
      if (data.ok) {
        alert(`Mapa salvo!\n${data.yaml}`);
        statusEl.textContent = `salvo: ${data.name}`;
        statusEl.className = 'map-status ok';
      } else {
        alert('Falha ao salvar mapa:\n' + (data.error || '?'));
      }
    });

    // --- Salvar mapa ---
    btnSave.addEventListener('click', () => {
      const name = prompt('Nome do mapa:', 'sala');
      if (!name) return;
      socket.emit('save_map', { name });
      statusEl.textContent = 'salvando...';
    });

    // --- Click → goal_pose (só em NAV2) ---
    canvas.addEventListener('click', (ev) => {
      if (!mapInfo || !mapImage) return;
      if (currentMode !== 'nav2') return;
      const rect = canvas.getBoundingClientRect();
      const cx = ev.clientX - rect.left;
      const cy = ev.clientY - rect.top;
      const world = canvasToWorld(cx, cy);
      if (!world) return;
      lastGoal = world;
      socket.emit('nav_goal', { x: world.x, y: world.y, yaw: 0.0 });
      statusEl.textContent = `alvo: (${world.x.toFixed(2)}, ${world.y.toFixed(2)})`;
      render();
    });
  });

  // --- Helpers de transformação canvas ↔ mundo ---
  // O mapa é desenhado ajustado ao canvas (preserva aspect ratio).
  function getDrawRect() {
    if (!mapImage) return null;
    const cw = canvas.width, ch = canvas.height;
    const iw = mapImage.width, ih = mapImage.height;
    const scale = Math.min(cw / iw, ch / ih);
    const dw = iw * scale, dh = ih * scale;
    const dx = (cw - dw) / 2, dy = (ch - dh) / 2;
    return { dx, dy, dw, dh, scale };
  }

  // Converte pixel do canvas para coordenada do mundo (frame 'map').
  // Considera que o PNG já foi virado verticalmente pelo backend, então a
  // linha 0 do PNG corresponde ao topo do mapa (y_max no mundo).
  function canvasToWorld(cx, cy) {
    const r = getDrawRect();
    if (!r) return null;
    const px_in_img = (cx - r.dx) / r.scale;     // coluna do PNG
    const py_in_img = (cy - r.dy) / r.scale;     // linha do PNG (top = 0)
    if (px_in_img < 0 || px_in_img >= mapInfo.width) return null;
    if (py_in_img < 0 || py_in_img >= mapInfo.height) return null;
    // Linha do PNG → linha do grid original (origem no canto inferior)
    const grid_row = (mapInfo.height - 1) - py_in_img;
    const world_x = mapInfo.origin_x + px_in_img * mapInfo.resolution;
    const world_y = mapInfo.origin_y + grid_row  * mapInfo.resolution;
    return { x: world_x, y: world_y };
  }

  function worldToCanvas(wx, wy) {
    const r = getDrawRect();
    if (!r) return null;
    const px_in_img = (wx - mapInfo.origin_x) / mapInfo.resolution;
    const grid_row  = (wy - mapInfo.origin_y) / mapInfo.resolution;
    const py_in_img = (mapInfo.height - 1) - grid_row;
    return {
      x: r.dx + px_in_img * r.scale,
      y: r.dy + py_in_img * r.scale,
    };
  }

  // --- Render loop (chamado sob demanda) ---
  function render() {
    ctx.fillStyle = '#222';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (!mapImage) {
      ctx.fillStyle = '#888';
      ctx.font = '14px sans-serif';
      ctx.fillText('Aguardando /map...', 20, 30);
      return;
    }
    const r = getDrawRect();
    ctx.drawImage(mapImage, r.dx, r.dy, r.dw, r.dh);

    // Borda do mapa
    ctx.strokeStyle = '#555';
    ctx.lineWidth = 1;
    ctx.strokeRect(r.dx, r.dy, r.dw, r.dh);

    // Trajetória planejada (Nav2)
    if (plan && plan.length > 1) {
      ctx.strokeStyle = '#4af';
      ctx.lineWidth = 2;
      ctx.beginPath();
      plan.forEach((p, i) => {
        const c = worldToCanvas(p.x, p.y);
        if (!c) return;
        if (i === 0) ctx.moveTo(c.x, c.y);
        else         ctx.lineTo(c.x, c.y);
      });
      ctx.stroke();
    }

    // Último alvo (bolinha vermelha)
    if (lastGoal) {
      const c = worldToCanvas(lastGoal.x, lastGoal.y);
      if (c) {
        ctx.fillStyle = '#e33';
        ctx.beginPath();
        ctx.arc(c.x, c.y, 6, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // Robô (seta laranja apontando para o yaw)
    if (robotPose) {
      const c = worldToCanvas(robotPose.x, robotPose.y);
      if (c) {
        const size = 10;
        ctx.save();
        ctx.translate(c.x, c.y);
        // No PNG y cresce pra baixo, então yaw (CCW positivo) é negativo visualmente.
        ctx.rotate(-robotPose.yaw);
        ctx.fillStyle = '#f90';
        ctx.beginPath();
        ctx.moveTo(size, 0);
        ctx.lineTo(-size * 0.6, size * 0.6);
        ctx.lineTo(-size * 0.3, 0);
        ctx.lineTo(-size * 0.6, -size * 0.6);
        ctx.closePath();
        ctx.fill();
        ctx.strokeStyle = '#000';
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.restore();
      }
    }
  }

  // Redesenha ~15 Hz para cobrir updates de pose sem precisar chamar render manualmente
  setInterval(render, 66);
})();
