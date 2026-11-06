"""Use Windows Schannel for the tracking site's TLS renegotiation."""
import asyncio
import subprocess
import tempfile
from pathlib import Path


async def fulfill(route):
    request = route.request
    headers = await request.all_headers()

    def send():
        with tempfile.TemporaryDirectory() as directory:
            header_path = Path(directory) / 'headers'
            body_path = Path(directory) / 'body'
            command = ['curl.exe', '--silent', '--show-error', '--max-time', '45',
                       '--proto', '=https', '--request', request.method,
                       '--dump-header', str(header_path), '--output', str(body_path)]
            for name, value in headers.items():
                if name.lower() not in {'host', 'content-length', 'accept-encoding', 'connection'}:
                    command += ['--header', f'{name}: {value}']
            body = request.post_data_buffer
            if body is not None:
                command += ['--data-binary', '@-']
            command += ['--url', request.url]
            result = subprocess.run(command, input=body, capture_output=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=50)
            if result.returncode:
                raise RuntimeError('长荣官网 HTTPS 连接失败，请稍后重试')
            raw = header_path.read_bytes().decode('iso-8859-1').strip().split('\r\n\r\n')[-1]
            lines = raw.splitlines()
            status = int(lines[0].split()[1])
            response_headers = {}
            for line in lines[1:]:
                if ':' in line:
                    name, value = line.split(':', 1)
                    if name.lower() not in {'transfer-encoding', 'content-length', 'connection'}:
                        response_headers[name] = value.strip()
            return status, response_headers, body_path.read_bytes()

    status, response_headers, body = await asyncio.to_thread(send)
    await route.fulfill(status=status, headers=response_headers, body=body)
