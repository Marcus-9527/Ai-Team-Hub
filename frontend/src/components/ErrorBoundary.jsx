import { Component } from 'react';

/**
 * Error Boundary — contains render crashes so one broken view never blanks
 * the whole app. Shows the real error + stack so failures are visible, not silent.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info?.componentStack);
  }

  handleReset = () => {
    this.setState({ error: null });
    if (this.props.onReset) this.props.onReset();
  };

  render() {
    if (this.state.error) {
      const { error } = this.state;
      return (
        <div
          style={{
            minHeight: '100vh',
            background: '#0B0B10',
            color: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 24,
            fontFamily: 'Inter, system-ui, sans-serif',
          }}
        >
          <div style={{ maxWidth: 640, width: '100%' }}>
            <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>
              页面渲染出错
            </h1>
            <p style={{ color: '#fc1c46', fontSize: 13, marginBottom: 12 }}>
              {error?.message || String(error)}
            </p>
            <pre
              style={{
                background: '#16161d',
                border: '1px solid #2a2a33',
                borderRadius: 8,
                padding: 12,
                fontSize: 12,
                overflow: 'auto',
                maxHeight: 280,
                color: '#c9c9d4',
                whiteSpace: 'pre-wrap',
              }}
            >
              {error?.stack || ''}
            </pre>
            <button
              onClick={this.handleReset}
              style={{
                marginTop: 16,
                padding: '8px 16px',
                borderRadius: 8,
                border: '1px solid #fc1c46',
                background: 'transparent',
                color: '#fc1c46',
                cursor: 'pointer',
                fontSize: 13,
              }}
            >
              重试
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
