export async function onRequest(context) {
  const { request, env, next } = context
  const url = new URL(request.url)

  if (url.pathname.startsWith('/api/')) {
    // Proxy to Worker
    const workerUrl = 'https://ai-team-hub.wt5371.workers.dev'
    const proxyUrl = workerUrl + url.pathname + url.search
    
    const modifiedRequest = new Request(proxyUrl, {
      method: request.method,
      headers: request.headers,
      body: request.method !== 'GET' && request.method !== 'HEAD' ? request.body : undefined,
    })
    
    const response = await fetch(modifiedRequest)
    const modifiedResponse = new Response(response.body, response)
    modifiedResponse.headers.set('Access-Control-Allow-Origin', '*')
    return modifiedResponse
  }

  // Serve static files
  return next()
}
