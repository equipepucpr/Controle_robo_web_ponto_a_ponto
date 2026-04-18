(() => {
  // Painel de waypoints: escuta pose/waypoints/follower_status via Socket.IO,
  // desenha canvas 2D (triângulo amarelo = robô, círculos numerados = pontos),
  // amarra botões a eventos record/clear/reset/start/stop/return/next_round.
  //
  // Suporta rounds (seções): waypoints agrupados por round, cores distintas
  // no canvas, exibição do round atual e do round sendo executado.
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
  const roundEl = document.getElementById('wp-round');
  const targetEl = document.getElementById('wp-target');
  const distEl = document.getElementById('wp-dist');
  const lioBadge = document.getElementById('wp-lio-badge');
  const followerBadge = document.getElementById('wp-follower-badge');

  const btnReset     = document.getElementById('btn-reset-origin');
  const btnRecord    = document.getElementById('btn-record-wp');
  const btnNextRound = document.getElementById('btn-next-round');
  const btnClear     = document.getElementById('btn-clear-wp');
  const btnStart     = document.getElementById('btn-start-follow');
  const btnReturn    = document.getElementById('btn-return-origin');
  const btnStop      = document.getElementById('btn-stop-follow');

  let lastPose = null;       // {x, y, yaw, ts}
  let lastPoseRecv = 0;      // timestamp local da última pose
  let waypoints = [];        // [{id, x, y, yaw, ts, round}]
  let currentRecordRound = 1;
  let followerState = 'IDLE';
  let followerInfo = {};

  // Cores por round (cíclicas)
  const ROUND_COLORS = [
    '#6366f1', // indigo
    '#f59e0b', // amber
    '#10b981', // emerald
    '#ef4444', // red
    '#8b5cf6', // violet
    '#06b6d4', // cyan
    '#f97316', // orange
    '#ec4899', // pink
  ];

  function roundColor(r) {
    return ROUND_COLORS[(r - 1) % ROUND_COLORS.length];
  }

  // ---- Estado do follower controla bloqueio de teclado ----
  function isFollowerActive() {
    return followerState === 'FORWARD' || followerState === 'REVERSE' || followerState === 'ROUND_PAUSE';
  }
  window.isFollowerActive = isFollowerActive;

  function updateFollowerBadge() {
    if (!followerBadge) return;
    let label = followerState;
    if (followerState === 'ROUND_PAUSE') label = 'RELAY';
    if (followerState === 'FORWARD' && followerInfo.total_rounds > 1) {
      label = `FWD R${followerInfo.current_round || '?'}/${followerInfo.total_rounds}`;
    }
    followerBadge.textContent = label;
    followerBadge.className = 'wp-badge';
    if (followerState === 'FORWARD') followerBadge.classList.add('fwd');
    else if (followerState === 'REVERSE') followerBadge.classList.add('rev');
    else if (followerState === 'STOPPED') followerBadge.classList.add('stop');
    else if (followerState === 'ROUND_PAUSE') followerBadge.classList.add('rev');
    else if (followerState === 'IDLE') followerBadge.classList.add('on');
  }

  function updateRoundDisplay() {
    if (roundEl) roundEl.textContent = currentRecordRound;
  }

  // ---- Socket events ----
  socket.on('pose_update', (data) => {
    lastPose = data;
    lastPoseRecv = Date.now();
    if (poseEl) {
      poseEl.textContent = `x=${data.x.toFixed(2)} y=${data.y.toFixed(2)} \u03b8=${(data.yaw * 180 / Math.PI).toFixed(1)}\u00b0`;
    }
    if (lioBadge) {
      lioBadge.textContent = 'pose ok';
      lioBadge.className = 'wp-badge on';
    }
  });

  socket.on('waypoints_update', (data) => {
    waypoints = (data && data.waypoints) || [];
    if (data && data.current_round) currentRecordRound = data.current_round;
    if (countEl) countEl.textContent = waypoints.length;
    updateRoundDisplay();
  });

  socket.on('follower_status', (data) => {
    if (!data) return;
    followerState = data.state || 'IDLE';
    followerInfo = data;
    updateFollowerBadge();
    if (targetEl) {
      targetEl.textContent = (data.target_id !== undefined && data.target_id !== null)
        ? `#${data.target_id}` : '\u2014';
    }
    if (distEl) {
      distEl.textContent = (data.dist_to_target !== undefined && data.dist_to_target !== null)
        ? `${Number(data.dist_to_target).toFixed(2)} m` : '\u2014';
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
  if (btnNextRound) btnNextRound.addEventListener('click', () => socket.emit('next_round'));
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

    // Agrupar waypoints por round para desenhar linhas e pontos
    const roundsMap = {};
    waypoints.forEach(w => {
      const r = w.round || 1;
      if (!roundsMap[r]) roundsMap[r] = [];
      roundsMap[r].push(w);
    });
    const roundKeys = Object.keys(roundsMap).map(Number).sort((a, b) => a - b);

    // Linha conectando waypoints em ordem, por round (cor do round)
    roundKeys.forEach(r => {
      const rWps = roundsMap[r];
      if (!rWps.length) return;
      ctx.strokeStyle = roundColor(r);
      ctx.globalAlpha = 0.4;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      // Primeiro round parte da origem, demais partem do último ponto do round anterior
      const prevRoundIdx = roundKeys.indexOf(r) - 1;
      let startPt;
      if (prevRoundIdx >= 0) {
        const prevWps = roundsMap[roundKeys[prevRoundIdx]];
        const lastWp = prevWps[prevWps.length - 1];
        startPt = worldToCanvas(lastWp.x, lastWp.y);
      } else {
        startPt = worldToCanvas(0, 0);
      }
      ctx.moveTo(startPt.px, startPt.py);
      rWps.forEach(w => {
        const p = worldToCanvas(w.x, w.y);
        ctx.lineTo(p.px, p.py);
      });
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1.0;
    });

    // Separadores de round (linha grossa entre último ponto de round N e primeiro de N+1)
    for (let i = 0; i < roundKeys.length - 1; i++) {
      const rWps = roundsMap[roundKeys[i]];
      const lastWp = rWps[rWps.length - 1];
      const nextWps = roundsMap[roundKeys[i + 1]];
      const firstWp = nextWps[0];
      const p1 = worldToCanvas(lastWp.x, lastWp.y);
      const p2 = worldToCanvas(firstWp.x, firstWp.y);
      // Pequeno marcador de "corte" entre rounds
      const midX = (p1.px + p2.px) / 2;
      const midY = (p1.py + p2.py) / 2;
      ctx.fillStyle = '#fbbf24';
      ctx.font = 'bold 9px system-ui';
      ctx.textAlign = 'center';
      ctx.fillText('\u26a1', midX, midY - 4);
      ctx.textAlign = 'left';
    }

    // Waypoints — cor por round, destaque se é alvo atual
    waypoints.forEach(w => {
      const p = worldToCanvas(w.x, w.y);
      const r = w.round || 1;
      const isTarget = followerInfo && followerInfo.target_id != null &&
                       followerInfo.target_id === w.id;
      ctx.fillStyle = isTarget ? '#fff' : roundColor(r);
      ctx.beginPath(); ctx.arc(p.px, p.py, 8, 0, Math.PI * 2); ctx.fill();
      if (isTarget) {
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 2.5;
        ctx.beginPath(); ctx.arc(p.px, p.py, 10, 0, Math.PI * 2); ctx.stroke();
      }
      ctx.fillStyle = isTarget ? '#000' : '#fff';
      ctx.font = 'bold 10px system-ui';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(w.id), p.px, p.py);
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
    });

    // Legenda de rounds (canto superior direito)
    if (roundKeys.length > 1) {
      const legendX = W - 10;
      let legendY = 16;
      ctx.font = 'bold 10px system-ui';
      ctx.textAlign = 'right';
      roundKeys.forEach(r => {
        ctx.fillStyle = roundColor(r);
        ctx.fillText(`R${r} (${roundsMap[r].length}pts)`, legendX, legendY);
        legendY += 14;
      });
      ctx.textAlign = 'left';
    }

    // Robô (triângulo amarelo)
    if (lastPose) {
      const p = worldToCanvas(lastPose.x, lastPose.y);
      ctx.save();
      ctx.translate(p.px, p.py);
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
  updateRoundDisplay();
})();
