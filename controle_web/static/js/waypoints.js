(() => {
  // Painel de waypoints: escuta pose/waypoints/follower_status via Socket.IO,
  // desenha canvas 2D (triângulo amarelo = robô, círculos numerados = pontos),
  // amarra botões a eventos record/clear/reset/start/stop/return.
  //
  // Bloqueia teclado/gamepad enquanto o follower está ativo pra evitar
  // dois publishers brigando pelo /cmd_vel.

  const socket = window.robotSocket;
  if (!socket) {
    console.warn('[waypoints] robotSocket ainda não disponível');
    return;
  }

  const canvas = document.getElementById('wp-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const poseEl = document.getElementById('wp-pose');
  const countEl = document.getElementById('wp-count');
  const targetEl = document.getElementById('wp-target');
  const distEl = document.getElementById('wp-dist');
  const lioBadge = document.getElementById('wp-lio-badge');
  const followerBadge = document.getElementById('wp-follower-badge');

  const btnReset  = document.getElementById('btn-reset-origin');
  const btnRecord = document.getElementById('btn-record-wp');
  const btnClear  = document.getElementById('btn-clear-wp');
  const btnStart  = document.getElementById('btn-start-follow');
  const btnReturn = document.getElementById('btn-return-origin');
  const btnStop   = document.getElementById('btn-stop-follow');

  let lastPose = null;       // {x, y, yaw, ts}
  let lastPoseRecv = 0;      // timestamp local da última pose
  let waypoints = [];        // [{id, x, y, yaw, ts}]
  let followerState = 'IDLE';
  let followerInfo = {};

  // ---- Estado do follower controla bloqueio de teclado ----
  function isFollowerActive() {
    return followerState === 'FORWARD' || followerState === 'REVERSE';
  }
  window.isFollowerActive = isFollowerActive;

  function updateFollowerBadge() {
    if (!followerBadge) return;
    followerBadge.textContent = followerState;
    followerBadge.className = 'wp-badge';
    if (followerState === 'FORWARD') followerBadge.classList.add('fwd');
    else if (followerState === 'REVERSE') followerBadge.classList.add('rev');
    else if (followerState === 'STOPPED') followerBadge.classList.add('stop');
    else if (followerState === 'IDLE') followerBadge.classList.add('on');
  }

  // ---- Socket events ----
  socket.on('pose_update', (data) => {
    lastPose = data;
    lastPoseRecv = Date.now();
    if (poseEl) {
      poseEl.textContent = `x=${data.x.toFixed(2)} y=${data.y.toFixed(2)} θ=${(data.yaw * 180 / Math.PI).toFixed(1)}°`;
    }
    if (lioBadge) {
      lioBadge.textContent = 'pose ok';
      lioBadge.className = 'wp-badge on';
    }
  });

  socket.on('waypoints_update', (data) => {
    waypoints = (data && data.waypoints) || [];
    if (countEl) countEl.textContent = waypoints.length;
  });

  socket.on('follower_status', (data) => {
    if (!data) return;
    followerState = data.state || 'IDLE';
    followerInfo = data;
    updateFollowerBadge();
    if (targetEl) {
      targetEl.textContent = (data.target_id !== undefined && data.target_id !== null)
        ? `#${data.target_id}` : '—';
    }
    if (distEl) {
      distEl.textContent = (data.dist_to_target !== undefined && data.dist_to_target !== null)
        ? `${Number(data.dist_to_target).toFixed(2)} m` : '—';
    }
  });

  socket.on('wp_ack', (ack) => {
    console.log('[wp_ack]', ack);
    if (!ack.ok) {
      alert(`Falha (${ack.op || '?'}): ${ack.error || ack.message || 'erro desconhecido'}`);
    }
  });

  socket.on('follow_ack', (ack) => {
    console.log('[follow_ack]', ack);
    if (!ack.ok) {
      alert(`Falha (${ack.op || '?'}): ${ack.error || ack.message || 'erro desconhecido'}`);
    }
  });

  // ---- Botões ----
  if (btnReset)  btnReset.addEventListener('click',  () => socket.emit('reset_origin'));
  if (btnRecord) btnRecord.addEventListener('click', () => socket.emit('record_waypoint'));
  if (btnClear)  btnClear.addEventListener('click',  () => {
    if (confirm('Apagar todos os waypoints gravados?')) socket.emit('clear_waypoints');
  });
  if (btnStart)  btnStart.addEventListener('click',  () => {
    if (!waypoints.length) { alert('Nenhum waypoint gravado.'); return; }
    socket.emit('start_follow');
  });
  if (btnReturn) btnReturn.addEventListener('click', () => socket.emit('return_to_origin'));
  if (btnStop)   btnStop.addEventListener('click',   () => socket.emit('stop_follow'));

  // ---- Pose timeout (1.5s sem /Odometry) ----
  setInterval(() => {
    if (!lioBadge) return;
    const age = Date.now() - lastPoseRecv;
    if (lastPoseRecv === 0 || age > 1500) {
      lioBadge.textContent = 'sem pose';
      lioBadge.className = 'wp-badge off';
    }
  }, 500);

  // ---- Canvas: autoscale pra caber origem + pose + waypoints ----
  function computeBounds() {
    const pts = [{ x: 0, y: 0 }];
    if (lastPose) pts.push({ x: lastPose.x, y: lastPose.y });
    waypoints.forEach(w => pts.push({ x: w.x, y: w.y }));
    let minX = -1, maxX = 1, minY = -1, maxY = 1;
    pts.forEach(p => {
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.y > maxY) maxY = p.y;
    });
    const padX = Math.max(0.5, (maxX - minX) * 0.15);
    const padY = Math.max(0.5, (maxY - minY) * 0.15);
    return {
      minX: minX - padX, maxX: maxX + padX,
      minY: minY - padY, maxY: maxY + padY,
    };
  }

  function draw() {
    const W = canvas.width, H = canvas.height;
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, W, H);

    const b = computeBounds();
    const rangeX = b.maxX - b.minX;
    const rangeY = b.maxY - b.minY;
    const scale = Math.min(W / rangeX, H / rangeY) * 0.9;
    const cx = W / 2 - (b.minX + rangeX / 2) * scale;
    // Y no mundo aponta pra "frente" — no canvas cresce pra baixo, então invertemos.
    const cy = H / 2 + (b.minY + rangeY / 2) * scale;

    function worldToCanvas(x, y) {
      return { px: cx + x * scale, py: cy - y * scale };
    }

    // Grade 1m
    ctx.strokeStyle = '#1a2332';
    ctx.lineWidth = 1;
    const step = rangeX > 10 ? 2 : 1;
    for (let gx = Math.ceil(b.minX); gx <= b.maxX; gx += step) {
      const p = worldToCanvas(gx, 0);
      ctx.beginPath(); ctx.moveTo(p.px, 0); ctx.lineTo(p.px, H); ctx.stroke();
    }
    for (let gy = Math.ceil(b.minY); gy <= b.maxY; gy += step) {
      const p = worldToCanvas(0, gy);
      ctx.beginPath(); ctx.moveTo(0, p.py); ctx.lineTo(W, p.py); ctx.stroke();
    }

    // Eixos através da origem
    const origin = worldToCanvas(0, 0);
    ctx.strokeStyle = '#374151';
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(0, origin.py); ctx.lineTo(W, origin.py); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(origin.px, 0); ctx.lineTo(origin.px, H); ctx.stroke();

    // Origem (0,0)
    ctx.fillStyle = '#10b981';
    ctx.beginPath(); ctx.arc(origin.px, origin.py, 7, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#0f766e';
    ctx.font = 'bold 11px system-ui';
    ctx.fillText('0', origin.px - 3, origin.py - 10);

    // Linha conectando waypoints em ordem
    if (waypoints.length > 0) {
      ctx.strokeStyle = '#64748b';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      const first = worldToCanvas(0, 0);
      ctx.moveTo(first.px, first.py);
      waypoints.forEach(w => {
        const p = worldToCanvas(w.x, w.y);
        ctx.lineTo(p.px, p.py);
      });
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Waypoints
    waypoints.forEach(w => {
      const p = worldToCanvas(w.x, w.y);
      const isTarget = followerInfo && followerInfo.target_id != null &&
                       followerInfo.target_id === w.id;
      ctx.fillStyle = isTarget ? '#f59e0b' : '#6366f1';
      ctx.beginPath(); ctx.arc(p.px, p.py, 8, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#fff';
      ctx.font = 'bold 10px system-ui';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(w.id), p.px, p.py);
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
    });

    // Robô (triângulo amarelo)
    if (lastPose) {
      const p = worldToCanvas(lastPose.x, lastPose.y);
      ctx.save();
      ctx.translate(p.px, p.py);
      // Yaw positivo = anti-horário no mundo; invertemos Y ⇒ gira no sentido contrário na tela.
      ctx.rotate(-lastPose.yaw);
      ctx.fillStyle = '#facc15';
      ctx.strokeStyle = '#a16207';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(12, 0);
      ctx.lineTo(-8, 7);
      ctx.lineTo(-8, -7);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.restore();
    }
  }

  setInterval(draw, 100);
  draw();
})();
