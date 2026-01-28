/**
 * Minimal test server for debugging container networking
 */

import http from 'node:http';

const port = parseInt(process.env.PORT || '8080', 10);
const hostname = '0.0.0.0';

console.log(`Starting minimal server on ${hostname}:${port}...`);

const server = http.createServer((req, res) => {
  console.log(`Request: ${req.method} ${req.url}`);

  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', timestamp: new Date().toISOString() }));
  } else if (req.url === '/chat' && req.method === 'POST') {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      console.log('Chat request body:', body);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        response: 'Hello from container!',
        sessionId: 'test-session',
        usage: { inputTokens: 0, outputTokens: 0 }
      }));
    });
  } else {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not Found' }));
  }
});

server.listen(port, hostname, () => {
  console.log(`Minimal server listening on http://${hostname}:${port}`);
});

server.on('error', (err) => {
  console.error('Server error:', err);
  process.exit(1);
});
