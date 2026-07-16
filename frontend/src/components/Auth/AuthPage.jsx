import { useState } from 'react';
import { login, register } from '../../services/api';
import { setSession } from '../../services/auth';
import { toast } from '../../services/toast';

export default function AuthPage({ onAuth }) {
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res =
        mode === 'login'
          ? await login(email, password)
          : await register(email, password, name);
      setSession(res.access_token, res.user, res.workspace_id);
      onAuth(res);
    } catch (err) {
      toast(err.message || '认证失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        background: '#4a154b',
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
      }}
    >
      <form
        onSubmit={submit}
        style={{
          width: 360,
          background: '#ffffff',
          borderRadius: 16,
          padding: 32,
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
          boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
        }}
      >
        <h1 style={{ fontFamily: "'Inter', sans-serif", margin: 0, fontSize: 24, fontWeight: 800, color: '#1d1d1d', letterSpacing: '-0.02em' }}>
          AI Team Hub
        </h1>
        <p style={{ margin: 0, color: '#9ca3af', fontSize: 13 }}>
          {mode === 'login' ? '登录到你的工作区' : '注册新账号'}
        </p>

        {mode === 'register' && (
          <input
            placeholder="显示名称"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={inputStyle}
          />
        )}
        <input
          type="email"
          placeholder="邮箱"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={inputStyle}
        />
        <input
          type="password"
          placeholder="密码 (至少6位)"
          required
          minLength={6}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={inputStyle}
        />

        <button
          type="submit"
          disabled={busy}
          style={{
            background: '#4a154b',
            color: '#fff',
            border: 'none',
            borderRadius: 999,
            padding: '10px 0',
            cursor: 'pointer',
            fontWeight: 600,
            fontSize: 14,
          }}
        >
          {busy ? '处理中…' : mode === 'login' ? '登录' : '注册'}
        </button>

        <button
          type="button"
          onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
          style={{ background: 'none', border: 'none', color: '#9ca3af', cursor: 'pointer', fontSize: 13, padding: '4px 0' }}
        >
          {mode === 'login' ? '没有账号?去注册' : '已有账号?去登录'}
        </button>
      </form>
    </div>
  );
}

const inputStyle = {
  background: '#faf8f5',
  border: '1px solid #e8e4df',
  borderRadius: 10,
  padding: '10px 12px',
  color: '#1d1d1d',
  fontSize: 14,
  outline: 'none',
};
