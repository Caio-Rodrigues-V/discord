import sqlite3
import os
import secrets
import string

DB_PATH = os.path.join(os.path.dirname(__file__), "discord_clan.db")
# Suporte a volumes persistentes no Railway
if os.path.exists("/data"):
    DB_PATH = "/data/discord_clan.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Inicializa as tabelas do banco de dados se não existirem."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Tabela de Usuários
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        avatar_color TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    # Tabela de Servidores (Guilds)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS servers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        invite_code TEXT UNIQUE NOT NULL,
        owner_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    
    # Tabela de Membros dos Servidores (Relação muitos-para-muitos)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS server_members (
        server_id INTEGER,
        user_id INTEGER,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(server_id, user_id),
        FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    
    # Tabela de Canais (Texto ou Voz)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('text', 'voice')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
    );
    """)
    
    # Tabela de Mensagens de Chat
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    
    conn.commit()
    conn.close()
    print("Banco de dados SQLite inicializado.")

# --- Operações de Usuário ---

def create_user(username, password_hash, avatar_color):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash, avatar_color) VALUES (?, ?, ?)",
            (username, password_hash, avatar_color)
        )
        conn.commit()
        user_id = cursor.lastrowid
        return user_id
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def get_user_by_username(username):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_id(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, avatar_color, created_at FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# --- Operações de Servidor ---

def generate_invite_code():
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "DC-" + "".join(secrets.choice(chars) for _ in range(6))
        # Verificar unicidade
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM servers WHERE invite_code = ?", (code,))
        exists = cursor.fetchone()
        conn.close()
        if not exists:
            return code

def create_server(name, owner_id):
    conn = get_db()
    cursor = conn.cursor()
    invite_code = generate_invite_code()
    try:
        cursor.execute(
            "INSERT INTO servers (name, invite_code, owner_id) VALUES (?, ?, ?)",
            (name, invite_code, owner_id)
        )
        server_id = cursor.lastrowid
        
        # Adicionar o dono como membro automaticamente
        cursor.execute(
            "INSERT INTO server_members (server_id, user_id) VALUES (?, ?)",
            (server_id, owner_id)
        )
        
        # Criar canais padrão
        cursor.execute(
            "INSERT INTO channels (server_id, name, type) VALUES (?, ?, 'text')",
            (server_id, "geral")
        )
        cursor.execute(
            "INSERT INTO channels (server_id, name, type) VALUES (?, ?, 'voice')",
            (server_id, "Geral")
        )
        
        conn.commit()
        return {"id": server_id, "name": name, "invite_code": invite_code}
    except Exception as e:
        conn.rollback()
        print(f"Erro ao criar servidor: {e}")
        return None
    finally:
        conn.close()

def join_server_by_invite(invite_code, user_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Encontrar servidor pelo código
        cursor.execute("SELECT id FROM servers WHERE invite_code = ?", (invite_code,))
        server = cursor.fetchone()
        if not server:
            return None
        
        server_id = server["id"]
        
        # Adicionar membro (se não for membro)
        cursor.execute(
            "INSERT OR IGNORE INTO server_members (server_id, user_id) VALUES (?, ?)",
            (server_id, user_id)
        )
        conn.commit()
        return server_id
    except Exception as e:
        conn.rollback()
        print(f"Erro ao entrar no servidor: {e}")
        return None
    finally:
        conn.close()

def get_user_servers(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.id, s.name, s.invite_code, s.owner_id 
        FROM servers s
        JOIN server_members sm ON s.id = sm.server_id
        WHERE sm.user_id = ?
        ORDER BY sm.joined_at ASC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_server_members(server_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.username, u.avatar_color
        FROM users u
        JOIN server_members sm ON u.id = sm.user_id
        WHERE sm.server_id = ?
        ORDER BY u.username ASC
    """, (server_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Operações de Canal ---

def create_channel(server_id, name, channel_type):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO channels (server_id, name, type) VALUES (?, ?, ?)",
            (server_id, name.lower().replace(" ", "-"), channel_type)
        )
        conn.commit()
        channel_id = cursor.lastrowid
        return {"id": channel_id, "server_id": server_id, "name": name, "type": channel_type}
    except Exception as e:
        conn.rollback()
        print(f"Erro ao criar canal: {e}")
        return None
    finally:
        conn.close()

def get_server_channels(server_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM channels WHERE server_id = ? ORDER BY type DESC, name ASC", (server_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Operações de Mensagem ---

def save_message(channel_id, user_id, content):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO messages (channel_id, user_id, content) VALUES (?, ?, ?)",
            (channel_id, user_id, content)
        )
        conn.commit()
        msg_id = cursor.lastrowid
        
        # Buscar mensagem com info do usuário
        cursor.execute("""
            SELECT m.id, m.channel_id, m.user_id, m.content, m.created_at, u.username, u.avatar_color
            FROM messages m
            JOIN users u ON m.user_id = u.id
            WHERE m.id = ?
        """, (msg_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        conn.rollback()
        print(f"Erro ao salvar mensagem: {e}")
        return None
    finally:
        conn.close()

def get_channel_messages(channel_id, limit=100):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.channel_id, m.user_id, m.content, m.created_at, u.username, u.avatar_color
        FROM messages m
        JOIN users u ON m.user_id = u.id
        WHERE m.channel_id = ?
        ORDER BY m.created_at ASC
        LIMIT ?
    """, (channel_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_user_to_default_server(user_id):
    """Verifica se existe algum servidor no banco. Se sim, adiciona o usuário a ele. Se não, cria um servidor padrão."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM servers ORDER BY id ASC LIMIT 1")
        row = cursor.fetchone()
        if row:
            server_id = row["id"]
            # Adicionar membro ao primeiro servidor (comunidade principal)
            cursor.execute(
                "INSERT OR IGNORE INTO server_members (server_id, user_id) VALUES (?, ?)",
                (server_id, user_id)
            )
            conn.commit()
            conn.close()
        else:
            # Se não existe nenhum servidor, fechar conexão e criar o primeiro
            conn.close()
            create_server("Comunidade Principal", user_id)
    except Exception as e:
        print(f"Erro ao adicionar usuário ao servidor padrão: {e}")
        try:
            conn.close()
        except Exception:
            pass
