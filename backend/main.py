import os
import json
import jwt
import datetime
import hashlib
import secrets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from typing import Dict, List, Set, Any, Optional

from backend.database import (
    init_db, create_user, get_user_by_username, get_user_by_id,
    create_server, join_server_by_invite, get_user_servers,
    get_server_members, create_channel, get_server_channels,
    save_message, get_channel_messages, add_user_to_default_server,
    get_db, get_cursor, qry
)

import logging
from collections import deque

# Buffer de logs em memória (últimos 1000 logs)
log_buffer = deque(maxlen=1000)

class DequeHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            log_buffer.append(f"[{record.levelname}] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {msg}")
        except Exception:
            self.handleError(record)

deque_handler = DequeHandler()
deque_handler.setFormatter(logging.Formatter('%(name)s: %(message)s'))
# Adicionar ao root logger
logging.getLogger().addHandler(deque_handler)
logging.getLogger().setLevel(logging.INFO)


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
    username = data.username.strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="Nome de usuário não pode estar vazio.")
        
    if len(username) < 3 or len(username) > 20:
        raise HTTPException(status_code=400, detail="O nome de usuário para login deve ter entre 3 e 20 caracteres.")
        
    # Verificar caracteres válidos (apenas letras, números ou sublinhados)
    import re
    if not re.match("^[a-zA-Z0-9_]+$", username):
        raise HTTPException(status_code=400, detail="O nome de usuário de login deve conter apenas letras, números ou sublinhados (_).")
        
    if len(data.password) < 4:
        raise HTTPException(status_code=400, detail="A senha deve ter no mínimo 4 caracteres.")

    colors = ["#5865F2", "#57F287", "#FEE75C", "#EB459E", "#ED4245"]
    import random
    avatar_color = random.choice(colors)
    
    hashed = hash_password(data.password)
    user_id = create_user(username, hashed, avatar_color)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome de usuário de login já cadastrado."
        )
    
    add_user_to_default_server(user_id)
    
    token = create_access_token(user_id, username)
    return {
        "token": token,
        "user": {"id": user_id, "username": username, "display_name": None, "avatar_color": avatar_color, "avatar_url": None, "custom_status": None}
    }

@app.post("/api/auth/login")
def login(data: LoginModel):
    username = data.username.strip().lower()
    user = get_user_by_username(username)
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nome de usuário ou senha incorretos."
        )
    
    token = create_access_token(user["id"], user["username"])
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name"),
            "avatar_color": user["avatar_color"],
            "avatar_url": user.get("avatar_url"),
            "custom_status": user.get("custom_status")
        }
    }


@app.get("/api/users/me")
def get_me(token: str = Query(...)):
    user = get_current_user_from_header(token)
    return get_user_by_id(user["user_id"])


class UpdateProfileModel(BaseModel):
    display_name: Optional[str] = None
    avatar_color: Optional[str] = None
    avatar_url: Optional[str] = None
    custom_status: Optional[str] = None

@app.put("/api/users/me")
async def update_profile(data: UpdateProfileModel, token: str = Query(...)):
    user = get_current_user_from_header(token)
    
    conn = get_db()
    cursor = get_cursor(conn)
    
    try:
        if data.display_name is not None:
            val = data.display_name.strip() if data.display_name.strip() else None
            cursor.execute(qry("UPDATE users SET display_name = ? WHERE id = ?"), (val, user["user_id"]))
            
        if data.avatar_color:
            cursor.execute(qry("UPDATE users SET avatar_color = ? WHERE id = ?"), (data.avatar_color, user["user_id"]))
            
        if data.avatar_url is not None:
            val = data.avatar_url.strip() if data.avatar_url.strip() else None
            cursor.execute(qry("UPDATE users SET avatar_url = ? WHERE id = ?"), (val, user["user_id"]))
            
        if data.custom_status is not None:
            val = data.custom_status.strip() if data.custom_status.strip() else None
            cursor.execute(qry("UPDATE users SET custom_status = ? WHERE id = ?"), (val, user["user_id"]))
            
        conn.commit()
    except HTTPException as he:
        raise he
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar perfil: {e}")
    finally:
        conn.close()
        
    updated = get_user_by_id(user["user_id"])
    
    # Atualizar em tempo real na memória do ConnectionManager para chamadas ativas
    u_id = user["user_id"]
    if u_id in manager.user_info:
        manager.user_info[u_id]["username"] = updated["username"]
        manager.user_info[u_id]["display_name"] = updated.get("display_name")
        manager.user_info[u_id]["avatar_color"] = updated["avatar_color"]
        manager.user_info[u_id]["avatar_url"] = updated.get("avatar_url")
        
    # Transmitir a alteração para todos os usuários conectados
    all_connected = list(manager.active_connections.keys())
    await manager.broadcast_to_users({
        "type": "user_profile_updated",
        "user": updated
    }, all_connected)
    
    return {
        "user": updated,
        "token": None
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
    members = get_server_members(server_id)
    for m in members:
        m["online"] = m["id"] in manager.active_connections
    return members


# --- Rotas de Mensagens ---

@app.get("/api/channels/{channel_id}/messages")
def list_messages(channel_id: int, token: str = Query(...)):
    get_current_user_from_header(token)
    return get_channel_messages(channel_id)


@app.get("/api/config")
def get_config():
    return {
        "rtcConfig": {
            "iceServers": [
                { "urls": "stun:stun.l.google.com:19302" },
                { "urls": "stun:stun1.l.google.com:19302" },
                { "urls": "stun:stun2.l.google.com:19302" },
                { 
                    "urls": "turn:" + os.getenv("TURN_URL", "openrelay.metered.ca:443"),
                    "username": os.getenv("TURN_USERNAME", "openrelayproject"),
                    "credential": os.getenv("TURN_CREDENTIAL", "openrelayproject")
                },
                { 
                    "urls": "turn:" + os.getenv("TURN_URL", "openrelay.metered.ca:443") + "?transport=tcp",
                    "username": os.getenv("TURN_USERNAME", "openrelayproject"),
                    "credential": os.getenv("TURN_CREDENTIAL", "openrelayproject")
                }
            ]
        }
    }


@app.get("/api/logs")
def get_logs(token: str = Query(...)):
    user_data = decode_token(token)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado"
        )
    # Retornar como texto plano para fácil leitura no navegador
    log_text = "\n".join(log_buffer)
    return PlainTextResponse(log_text)


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
        # Mapeamento: user_id -> dict com configurações de voz (muted, deafened)
        self.user_voice_settings: Dict[int, Dict[str, bool]] = {}
        
        # Mapeamento: channel_id (voz) -> lista de user_ids conectados na call
        self.voice_channels: Dict[int, List[int]] = {}
        # Mapeamento: user_id -> channel_id (voz ativo)
        self.user_voice_channels: Dict[int, int] = {}

    async def connect(self, websocket: WebSocket, user_id: int, username: str, avatar_color: str, avatar_url: Optional[str] = None):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.user_info[user_id] = {
            "id": user_id,
            "username": username,
            "avatar_color": avatar_color,
            "avatar_url": avatar_url
        }
        self.user_voice_settings[user_id] = {
            "muted": False,
            "deafened": False,
            "server_muted": False,
            "server_deafened": False
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
            states[cid] = []
            for uid in uids:
                if uid in self.user_info:
                    info = dict(self.user_info[uid])
                    settings = self.user_voice_settings.get(uid, {"muted": False, "deafened": False, "server_muted": False, "server_deafened": False})
                    info["muted"] = settings.get("muted", False)
                    info["deafened"] = settings.get("deafened", False)
                    info["serverMuted"] = settings.get("server_muted", False)
                    info["serverDeafened"] = settings.get("server_deafened", False)
                    states[cid].append(info)
        return states

    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_info:
            del self.user_info[user_id]
        if user_id in self.user_voice_settings:
            del self.user_voice_settings[user_id]
        
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
    avatar_url = user_details.get("avatar_url") if user_details else None
    
    await manager.connect(websocket, user_id, username, avatar_color, avatar_url)
    await manager.broadcast_to_users({
        "type": "user_status_changed",
        "user_id": user_id,
        "online": True
    }, list(manager.active_connections.keys()))
    
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
                    conn = get_db()
                    cursor = get_cursor(conn)
                    # Achar o server_id deste canal
                    cursor.execute(qry("SELECT server_id FROM channels WHERE id = ?"), (channel_id,))
                    chan = cursor.fetchone()
                    if chan:
                        server_id = chan["server_id"]
                        # Buscar membros do servidor
                        cursor.execute(qry("SELECT user_id FROM server_members WHERE server_id = ?"), (server_id,))
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
                        info = dict(manager.user_info[uid])
                        settings = manager.user_voice_settings.get(uid, {"muted": False, "deafened": False, "server_muted": False, "server_deafened": False})
                        info["muted"] = settings.get("muted", False)
                        info["deafened"] = settings.get("deafened", False)
                        info["serverMuted"] = settings.get("server_muted", False)
                        info["serverDeafened"] = settings.get("server_deafened", False)
                        current_members.append(info)
                
                # Responder ao novo usuário
                await manager.send_personal_message({
                    "type": "voice_channel_state",
                    "channel_id": channel_id,
                    "users": current_members
                }, user_id)
                
                # Notificar TODO MUNDO no servidor que este usuário entrou
                user_joined_info = dict(manager.user_info[user_id])
                settings = manager.user_voice_settings.get(user_id, {"muted": False, "deafened": False, "server_muted": False, "server_deafened": False})
                user_joined_info["muted"] = settings.get("muted", False)
                user_joined_info["deafened"] = settings.get("deafened", False)
                user_joined_info["serverMuted"] = settings.get("server_muted", False)
                user_joined_info["serverDeafened"] = settings.get("server_deafened", False)
                
                all_connected = list(manager.active_connections.keys())
                await manager.broadcast_to_users({
                    "type": "voice_user_joined",
                    "channel_id": channel_id,
                    "user": user_joined_info
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
                    
            elif msg_type == "voice_state_update":
                muted = bool(message.get("muted"))
                deafened = bool(message.get("deafened"))
                if user_id in manager.user_voice_settings:
                    manager.user_voice_settings[user_id]["muted"] = muted
                    manager.user_voice_settings[user_id]["deafened"] = deafened
                else:
                    manager.user_voice_settings[user_id] = {
                        "muted": muted,
                        "deafened": deafened,
                        "server_muted": False,
                        "server_deafened": False
                    }
                all_connected = list(manager.active_connections.keys())
                await manager.broadcast_to_users({
                    "type": "voice_state_update",
                    "user_id": user_id,
                    "muted": muted,
                    "deafened": deafened
                }, all_connected)

            elif msg_type == "server_voice_moderation":
                target_id = int(message.get("target_id"))
                action = message.get("action")  # "mute", "deafen", "disconnect"
                
                if action == "disconnect":
                    if target_id in manager.active_connections:
                        await manager.send_personal_message({
                            "type": "server_voice_force_disconnect"
                        }, target_id)
                elif action in ["mute", "deafen"]:
                    val = bool(message.get("value"))
                    if target_id in manager.user_voice_settings:
                        if action == "mute":
                            manager.user_voice_settings[target_id]["server_muted"] = val
                        elif action == "deafen":
                            manager.user_voice_settings[target_id]["server_deafened"] = val
                    all_connected = list(manager.active_connections.keys())
                    await manager.broadcast_to_users({
                        "type": "server_voice_moderation",
                        "user_id": target_id,
                        "action": action,
                        "value": val
                    }, all_connected)

    except WebSocketDisconnect:
        channel_id, remaining = manager.leave_voice_channel_if_any(user_id)
        manager.disconnect(user_id)
        all_connected = list(manager.active_connections.keys())
        await manager.broadcast_to_users({
            "type": "user_status_changed",
            "user_id": user_id,
            "online": False
        }, all_connected)
        if channel_id:
            await manager.broadcast_to_users({
                "type": "voice_user_left",
                "channel_id": channel_id,
                "user_id": user_id
            }, all_connected)
    except Exception as e:
        print(f"Erro na conexão WebSocket do usuário {user_id}: {e}")
        channel_id, remaining = manager.leave_voice_channel_if_any(user_id)
        manager.disconnect(user_id)
        try:
            all_connected = list(manager.active_connections.keys())
            await manager.broadcast_to_users({
                "type": "user_status_changed",
                "user_id": user_id,
                "online": False
            }, all_connected)
            if channel_id:
                await manager.broadcast_to_users({
                    "type": "voice_user_left",
                    "channel_id": channel_id,
                    "user_id": user_id
                }, all_connected)
        except Exception:
            pass
