import os
import json
import jwt
import datetime
import hashlib
import secrets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Dict, List, Set, Any

from backend.database import (
    init_db, create_user, get_user_by_username, get_user_by_id,
    create_server, join_server_by_invite, get_user_servers,
    get_server_members, create_channel, get_server_channels,
    save_message, get_channel_messages, add_user_to_default_server
)

SECRET_KEY = "discord-clan-secret-key-super-secure-12345"
ALGORITHM = "HS256"



app = FastAPI(title="Discord Clan API")

# Habilitar CORS para desenvolvimento local
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializar banco de dados na inicialização
@app.on_event("startup")
def startup_event():
    init_db()

# --- Modelos Pydantic ---
class RegisterModel(BaseModel):
    username: str
    password: str

class LoginModel(BaseModel):
    username: str
    password: str

class ServerCreateModel(BaseModel):
    name: str

class ServerJoinModel(BaseModel):
    invite_code: str

class ChannelCreateModel(BaseModel):
    name: str
    type: str  # 'text' ou 'voice'


# --- Funções de Segurança ---
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    db_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"{salt.hex()}:{db_hash.hex()}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        salt_hex, hash_hex = hashed_password.split(":")
        salt = bytes.fromhex(salt_hex)
        db_hash = bytes.fromhex(hash_hex)
        new_hash = hashlib.pbkdf2_hmac('sha256', plain_password.encode('utf-8'), salt, 100000)
        return secrets.compare_digest(db_hash, new_hash)
    except Exception:
        return False

def create_access_token(user_id: int, username: str) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"user_id": int(payload["sub"]), "username": payload["username"]}
    except Exception:
        return None

def get_current_user_from_header(token: str):
    user_data = decode_token(token)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado"
        )
    # Verificar se o usuário ainda existe no banco de dados (caso o DB tenha sido resetado)
    user = get_user_by_id(user_data["user_id"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário não existe ou banco foi reiniciado. Faça login novamente."
        )
    return user_data


# --- Rotas de Autenticação ---

@app.post("/api/auth/register")
def register(data: RegisterModel):
    # Cores aleatórias bonitas para avatares (Paleta Discord)
    colors = ["#5865F2", "#57F287", "#FEE75C", "#EB459E", "#ED4245"]
    import random
    avatar_color = random.choice(colors)
    
    hashed = hash_password(data.password)
    user_id = create_user(data.username, hashed, avatar_color)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome de usuário já cadastrado."
        )
    
    # Adicionar o usuário ao servidor padrão automaticamente (ou cria o servidor se for o primeiro)
    add_user_to_default_server(user_id)
    
    token = create_access_token(user_id, data.username)
    return {
        "token": token,
        "user": {"id": user_id, "username": data.username, "avatar_color": avatar_color}
    }

@app.post("/api/auth/login")
def login(data: LoginModel):
    user = get_user_by_username(data.username)
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nome de usuário ou senha incorretos."
        )
    
    token = create_access_token(user["id"], user["username"])
    return {
        "token": token,
        "user": {"id": user["id"], "username": user["username"], "avatar_color": user["avatar_color"]}
    }


# --- Rotas de Servidores ---

@app.get("/api/servers")
def list_servers(token: str = Query(...)):
    user = get_current_user_from_header(token)
    return get_user_servers(user["user_id"])

@app.post("/api/servers")
def create_new_server(data: ServerCreateModel, token: str = Query(...)):
    user = get_current_user_from_header(token)
    server = create_server(data.name, user["user_id"])
    if not server:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao criar o servidor."
        )
    return server

@app.post("/api/servers/join")
def join_server(data: ServerJoinModel, token: str = Query(...)):
    user = get_current_user_from_header(token)
    server_id = join_server_by_invite(data.invite_code, user["user_id"])
    if not server_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Código de convite inválido ou servidor inexistente."
        )
    return {"status": "success", "server_id": server_id}

@app.get("/api/servers/{server_id}/channels")
def list_channels(server_id: int, token: str = Query(...)):
    get_current_user_from_header(token)
    return get_server_channels(server_id)

@app.post("/api/servers/{server_id}/channels")
def create_new_channel(server_id: int, data: ChannelCreateModel, token: str = Query(...)):
    get_current_user_from_header(token)
    if data.type not in ["text", "voice"]:
        raise HTTPException(status_code=400, detail="Tipo de canal inválido")
    channel = create_channel(server_id, data.name, data.type)
    if not channel:
         raise HTTPException(status_code=500, detail="Erro ao criar canal")
    return channel

@app.get("/api/servers/{server_id}/members")
def list_members(server_id: int, token: str = Query(...)):
    get_current_user_from_header(token)
    return get_server_members(server_id)


# --- Rotas de Mensagens ---

@app.get("/api/channels/{channel_id}/messages")
def list_messages(channel_id: int, token: str = Query(...)):
    get_current_user_from_header(token)
    return get_channel_messages(channel_id)


# --- Roteamento de Arquivos Estáticos do Frontend ---

@app.get("/")
def read_root():
    return FileResponse("frontend/index.html")

@app.get("/app.js")
def read_app_js():
    return FileResponse("frontend/app.js")

@app.get("/style.css")
def read_style_css():
    return FileResponse("frontend/style.css")


# --- WebSocket & Sinalização WebRTC ---

class ConnectionManager:
    def __init__(self):
        # Mapeamento: user_id -> WebSocket
        self.active_connections: Dict[int, WebSocket] = {}
        # Mapeamento: user_id -> dict com info do usuário (username, avatar_color)
        self.user_info: Dict[int, dict] = {}
        
        # Mapeamento: channel_id (voz) -> lista de user_ids conectados na call
        self.voice_channels: Dict[int, List[int]] = {}
        # Mapeamento: user_id -> channel_id (voz ativo)
        self.user_voice_channels: Dict[int, int] = {}

    async def connect(self, websocket: WebSocket, user_id: int, username: str, avatar_color: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.user_info[user_id] = {
            "id": user_id,
            "username": username,
            "avatar_color": avatar_color
        }
        print(f"WebSocket conectado: {username} (ID: {user_id})")
        
        # Enviar estados de canais de voz iniciais
        await self.send_personal_message({
            "type": "voice_states",
            "states": self.get_all_voice_states()
        }, user_id)

    def get_all_voice_states(self) -> dict:
        states = {}
        for cid, uids in self.voice_channels.items():
            states[cid] = [self.user_info[uid] for uid in uids if uid in self.user_info]
        return states

    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_info:
            del self.user_info[user_id]
        
        # Se estava em uma call, remover dela
        self.leave_voice_channel_if_any(user_id)
        print(f"WebSocket desconectado: ID {user_id}")

    def leave_voice_channel_if_any(self, user_id: int) -> tuple[int, list[int]]:
        """Remove o usuário de qualquer canal de voz ativo e retorna o ID do canal e os membros restantes."""
        if user_id in self.user_voice_channels:
            channel_id = self.user_voice_channels[user_id]
            del self.user_voice_channels[user_id]
            
            if channel_id in self.voice_channels:
                if user_id in self.voice_channels[channel_id]:
                    self.voice_channels[channel_id].remove(user_id)
                
                remaining = list(self.voice_channels[channel_id])
                if not self.voice_channels[channel_id]:
                    del self.voice_channels[channel_id]
                return channel_id, remaining
        return None, []

    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_text(json.dumps(message))
            except Exception:
                # Conexão quebrada, desconectar
                self.disconnect(user_id)

    async def broadcast_to_users(self, message: dict, user_ids: List[int]):
        for uid in user_ids:
            await self.send_personal_message(message, uid)


manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    user_data = decode_token(token)
    if not user_data:
        # Rejeitar conexão caso token seja inválido
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    user_id = user_data["user_id"]
    username = user_data["username"]
    
    # Obter detalhes completos do usuário do DB
    user_details = get_user_by_id(user_id)
    avatar_color = user_details["avatar_color"] if user_details else "#5865F2"
    
    await manager.connect(websocket, user_id, username, avatar_color)
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type")
            
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                
            elif msg_type == "chat_message":
                channel_id = int(message.get("channel_id"))
                content = message.get("content")
                
                # Salvar mensagem no SQLite
                saved_msg = save_message(channel_id, user_id, content)
                if saved_msg:
                    # Encontrar todos os membros do servidor deste canal para transmitir
                    # (Para simplicidade, transmitimos a todos os membros do servidor conectados)
                    import sqlite3
                    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "discord_clan.db"))
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    # Achar o server_id deste canal
                    cursor.execute("SELECT server_id FROM channels WHERE id = ?", (channel_id,))
                    chan = cursor.fetchone()
                    if chan:
                        server_id = chan["server_id"]
                        # Buscar membros do servidor
                        cursor.execute("SELECT user_id FROM server_members WHERE server_id = ?", (server_id,))
                        members = cursor.fetchall()
                        member_ids = [m["user_id"] for m in members]
                        
                        # Transmitir a mensagem
                        await manager.broadcast_to_users({
                            "type": "chat_message",
                            "message": saved_msg
                        }, member_ids)
                    conn.close()
                    
            elif msg_type == "voice_join":
                channel_id = int(message.get("channel_id"))
                
                # Sair de qualquer canal anterior
                old_channel_id, old_remaining = manager.leave_voice_channel_if_any(user_id)
                if old_channel_id:
                    # Notificar todos no servidor que o usuário saiu do canal antigo
                    all_connected = list(manager.active_connections.keys())
                    await manager.broadcast_to_users({
                        "type": "voice_user_left",
                        "channel_id": old_channel_id,
                        "user_id": user_id
                    }, all_connected)
                
                # Ingressar no novo canal de voz
                if channel_id not in manager.voice_channels:
                    manager.voice_channels[channel_id] = []
                manager.voice_channels[channel_id].append(user_id)
                manager.user_voice_channels[user_id] = channel_id
                
                # Mandar estado atual do canal para quem acabou de entrar (quem já está lá)
                current_members = []
                for uid in manager.voice_channels[channel_id]:
                    if uid in manager.user_info:
                        current_members.append(manager.user_info[uid])
                
                # Responder ao novo usuário
                await manager.send_personal_message({
                    "type": "voice_channel_state",
                    "channel_id": channel_id,
                    "users": current_members
                }, user_id)
                
                # Notificar TODO MUNDO no servidor que este usuário entrou
                all_connected = list(manager.active_connections.keys())
                await manager.broadcast_to_users({
                    "type": "voice_user_joined",
                    "channel_id": channel_id,
                    "user": manager.user_info[user_id]
                }, all_connected)
                
            elif msg_type == "voice_leave":
                channel_id, remaining = manager.leave_voice_channel_if_any(user_id)
                if channel_id:
                    all_connected = list(manager.active_connections.keys())
                    await manager.broadcast_to_users({
                        "type": "voice_user_left",
                        "channel_id": channel_id,
                        "user_id": user_id
                    }, all_connected)
                    
            elif msg_type == "webrtc_signal":
                target_id = int(message.get("target_id"))
                signal_data = message.get("signal")
                
                # Roteia o sinal WebRTC (SDP / ICE candidate) para o destinatário correto
                if target_id in manager.active_connections:
                    await manager.send_personal_message({
                        "type": "webrtc_signal",
                        "sender_id": user_id,
                        "signal": signal_data
                    }, target_id)
                    
            elif msg_type == "voice_speaking":
                # Indica se o usuário está falando para mostrar o círculo verde na UI de todos
                channel_id = manager.user_voice_channels.get(user_id)
                if channel_id and channel_id in manager.voice_channels:
                    speaking = bool(message.get("speaking"))
                    all_connected = list(manager.active_connections.keys())
                    await manager.broadcast_to_users({
                        "type": "voice_speaking",
                        "user_id": user_id,
                        "speaking": speaking
                    }, all_connected)
                    
            elif msg_type == "screen_share_status":
                # Avisa a todos que começou/parou de compartilhar tela para atualizar o ao vivo
                channel_id = manager.user_voice_channels.get(user_id)
                if channel_id and channel_id in manager.voice_channels:
                    sharing = bool(message.get("sharing"))
                    all_connected = list(manager.active_connections.keys())
                    await manager.broadcast_to_users({
                        "type": "screen_share_status",
                        "channel_id": channel_id,
                        "user_id": user_id,
                        "sharing": sharing
                    }, all_connected)

    except WebSocketDisconnect:
        channel_id, remaining = manager.leave_voice_channel_if_any(user_id)
        manager.disconnect(user_id)
        if channel_id:
            all_connected = list(manager.active_connections.keys())
            await manager.broadcast_to_users({
                "type": "voice_user_left",
                "channel_id": channel_id,
                "user_id": user_id
            }, all_connected)
    except Exception as e:
        print(f"Erro na conexão WebSocket do usuário {user_id}: {e}")
        channel_id, remaining = manager.leave_voice_channel_if_any(user_id)
        manager.disconnect(user_id)
        if channel_id:
            try:
                all_connected = list(manager.active_connections.keys())
                await manager.broadcast_to_users({
                    "type": "voice_user_left",
                    "channel_id": channel_id,
                    "user_id": user_id
                }, all_connected)
            except Exception:
                pass
