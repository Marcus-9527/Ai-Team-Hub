// Test DNS resolution
export default {
  async fetch(request, env) {
    try {
      const res = await fetch('https://www.google.com', { method: 'HEAD' });
      return new Response('OK: ' + res.status);
    } catch (e) {
      return new Response('Error: ' + e.message);
    }
  }
}
