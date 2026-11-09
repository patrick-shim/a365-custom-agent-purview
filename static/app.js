let csrf = '';
const el = id => document.getElementById(id);
async function loadSession() {
  try {
    const response = await fetch('/api/session');
    const session = await response.json();
    csrf = session.csrf || '';
    el('signin').hidden = session.authenticated || session.missing_settings.length > 0;
    el('signout').hidden = !session.authenticated;
    el('send').disabled = !session.authenticated;
    el('account').textContent = session.authenticated ? session.name : 'Your work account';
    el('account-hint').textContent = session.authenticated ? session.username : 'Sign in to read your own OneDrive.';
    el('setup').hidden = session.missing_settings.length === 0;
    el('setup-text').textContent = 'Set these values in .env: ' + session.missing_settings.join(', ');
    el('status').textContent = session.authenticated ? 'Ready. File content is inspected before use.' : 'Sign in to start.';
    if (!el('file-path').value) el('file-path').value = session.test_file_path || '';
  } catch { el('status').textContent = 'Cannot connect to the local application.'; }
}
function addTurn(role, text, detail='') {
  document.querySelector('.welcome')?.remove();
  const div = document.createElement('div');
  div.className = 'turn ' + role;
  const label = document.createElement('small');
  label.textContent = role === 'user' ? 'You' : role === 'error' ? 'Request stopped' : 'Agent';
  div.append(label, document.createTextNode(text));
  if (detail) { const d = document.createElement('span'); d.className='detail'; d.textContent=detail; div.append(d); }
  el('conversation').append(div);
  div.scrollIntoView({block:'nearest'});
}
el('chat-form').addEventListener('submit', async event => {
  event.preventDefault();
  const message = el('message').value.trim();
  if (!message || !csrf) return;
  const file_path = el('file-path').value.trim();
  addTurn('user', message + (file_path ? '\nDocument: '+file_path : ''));
  el('send').disabled = true;
  el('status').textContent = 'Checking policy and processing your request…';
  try {
    const response = await fetch('/api/chat', {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({message,file_path})});
    const data = await response.json();
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : 'Check your message and file path.';
      addTurn('error', detail);
      if (response.status === 401) { await loadSession(); return; }
    } else {
      addTurn('assistant', data.text, (data.output_inline_evaluated ? 'Response evaluated inline.' : 'Response audit submitted; output filtering is not guaranteed.') + ' Reference: '+data.correlation_id);
      el('message').value = '';
    }
    el('status').textContent = 'Ready for your next message.';
  } catch { addTurn('error', 'The local application could not complete the request.'); el('status').textContent='Request failed.'; }
  finally { el('send').disabled = !csrf; }
});
el('signout').addEventListener('click', async () => {
  await fetch('/auth/logout', {method:'POST',headers:{'X-CSRF-Token':csrf}});
  location.reload();
});
loadSession();
