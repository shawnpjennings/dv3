import asyncio
import json
import pytest
import aiohttp
from core.visualizer_ws import VisualizerWSServer


@pytest.mark.asyncio
async def test_server_starts_and_accepts_connection():
    server = VisualizerWSServer(host='127.0.0.1', port=8770)
    await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect('ws://127.0.0.1:8770/ws') as ws:
                assert not ws.closed
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_broadcast_emotion_event():
    server = VisualizerWSServer(host='127.0.0.1', port=8771)
    await server.start()
    received = []

    async def receive():
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect('ws://127.0.0.1:8771/ws') as ws:
                msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                received.append(json.loads(msg.data))

    task = asyncio.create_task(receive())
    await asyncio.sleep(0.1)
    await server.emit_emotion('happy', theme='dark')
    await asyncio.wait_for(task, timeout=3.0)
    await server.stop()
    assert received[0] == {'type': 'emotion', 'emotion': 'happy', 'theme': 'dark'}
