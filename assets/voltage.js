let voltageRequestBusy = false;
function showSupplyVoltage(value) {
  const valid = value?.available && Number.isFinite(value.volts);
  const button = document.getElementById('read-voltage');
  document.getElementById('supply-voltage').textContent = valid ? value.volts.toFixed(1)+' V' : '—';
  const age = Math.max(0, Math.floor((value?.age_ms || 0)/1000));
  document.getElementById('supply-voltage-detail').textContent = value?.pending
    ? `正在读取 ${value.servo_id} 号舵机…`
    : value?.error || (valid ? `ID ${value.servo_id} · 上次测量 · ${age} 秒前${value.connected ? '' : ' · 已断连'}`
      : value?.connected ? '尚未读取 · 点击获取' : '机器人未连接');
  button.disabled = voltageRequestBusy || !value?.connected || value.pending || value.retry_after_ms > 0;
  button.textContent = voltageRequestBusy || value?.pending ? '读取中…' : '读取电压';
}
document.getElementById('read-voltage').addEventListener('click', async () => {
  if (voltageRequestBusy) return;
  const input = document.getElementById('voltage-servo-id');
  const servoId = Number(input.value);
  if (!input.value.trim() || !Number.isInteger(servoId) || servoId < 0 || servoId > 253) {
    document.getElementById('supply-voltage-detail').textContent = '舵机 ID 必须是 0–253 的整数';
    return;
  }
  voltageRequestBusy = true;
  const button = document.getElementById('read-voltage');
  button.disabled = true;
  button.textContent = '读取中…';
  try {
    const response = await fetch('/api/voltage/read', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({servo_id:servoId}),
      signal:AbortSignal.timeout(2500)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '读取请求失败');
  } catch (error) {
    document.getElementById('supply-voltage-detail').textContent = error.message;
  } finally {
    voltageRequestBusy = false;
    // The regular status refresh owns the pending/result display and re-enables the button.
  }
});
