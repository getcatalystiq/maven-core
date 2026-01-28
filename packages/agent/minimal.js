import { createServer } from 'node:http';

const port = parseInt(process.env.PORT || '8080', 10);
const hostname = '0.0.0.0';

console.log(`Starting minimal server on ${hostname}:${port}...`);
console.log(`NODE_ENV: ${process.env.NODE_ENV}`);
console.log(`Process ID: ${process.pid}`);

const server = createServer((req, res) => {
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
    res.end(JSON.stringify({ error: 'Not Found', path: req.url }));
  }
});

server.listen(port, hostname, () => {
  console.log(`Minimal server listening on http://${hostname}:${port}`);
});

server.on('error', (err) => {
  console.error('Server error:', err);
  process.exit(1);
});

// Keep process alive
process.on('SIGTERM', () => {
  console.log('Received SIGTERM, shutting down...');
  server.close(() => process.exit(0));
});
