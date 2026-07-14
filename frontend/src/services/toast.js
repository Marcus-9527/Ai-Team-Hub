// 极简全局 toast:发布订阅,无第三方依赖。
const listeners = new Set();

export function onToast(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function toast(message, type = 'error') {
  const item = { id: Date.now() + Math.random(), message, type };
  listeners.forEach((fn) => fn(item));
}
