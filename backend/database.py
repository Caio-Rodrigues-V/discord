import sqlite3
import os
import secrets
import string

DATABASE_URL = os.getenv("DATABASE_URL")
IS_POSTGRES = DATABASE_URL is not None

if IS_POSTGRES:
    import psycopg
    import psycopg.rows
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "discord_clan.db")
    if os.path.exists("/data"):
        DB_PATH = "/data/discord_clan.db"

def get_db():
    if IS_POSTGRES:
        conn = psycopg.connect(DATABASE_URL)
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

def get_cursor(conn):
    if IS_POSTGRES:
        return conn.cursor(row_factory=psycopg.rows.dict_row)
    else:
        return conn.cursor()

def qry(sql):
    if IS_POSTGRES:
        return sql.replace("?", "%s")
    return sql

def init_db():
    """Inicializa as tabelas do banco de dados se não existirem."""
    conn = get_db()
    cursor = conn.cursor()
    
    if IS_POSTGRES:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            avatar_color VARCHAR(50) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            invite_code VARCHAR(100) UNIQUE NOT NULL,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS server_members (
            server_id INTEGER REFERENCES servers(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(server_id, user_id)
        );
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id SERIAL PRIMARY KEY,
            server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            type VARCHAR(50) NOT NULL CHECK(type IN ('text', 'voice')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        print("Banco de dados PostgreSQL inicializado.")
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            avatar_color TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
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
        print("Banco de dados SQLite inicializado.")
        
    # Migrações seguras de colunas
    try:
        if IS_POSTGRES:
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT;")
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS custom_status VARCHAR(255);")
        else:
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT;")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN custom_status TEXT;")
            except Exception:
                pass
    except Exception as e:
        print("Erro nas migrações de colunas:", e)
        
    conn.commit()
    conn.close()

def create_user(username, password_hash, avatar_color):
    conn = get_db()
    cursor = get_cursor(conn)
    try:
        if IS_POSTGRES:
            cursor.execute(
                "INSERT INTO users (username, password_hash, avatar_color) VALUES (%s, %s, %s) RETURNING id",
                (username, password_hash, avatar_color)
            )
            user_id = cursor.fetchone()["id"]
        else:
            cursor.execute(
                "INSERT INTO users (username, password_hash, avatar_color) VALUES (?, ?, ?)",
                (username, password_hash, avatar_color)
            )
            user_id = cursor.lastrowid
        conn.commit()
        return user_id
    except Exception as e:
        print(f"Erro ao cadastrar usuário: {e}")
        return None
    finally:
        conn.close()

def get_user_by_username(username):
    conn = get_db()
    cursor = get_cursor(conn)
    cursor.execute(qry("SELECT * FROM users WHERE username = ?"), (username,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_id(user_id):
    conn = get_db()
    cursor = get_cursor(conn)
    cursor.execute(qry("SELECT id, username, avatar_color, avatar_url, custom_status, created_at FROM users WHERE id = ?"), (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def generate_invite_code():
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "DC-" + "".join(secrets.choice(chars) for _ in range(6))
        # Verificar unicidade
        conn = get_db()
        cursor = get_cursor(conn)
        cursor.execute(qry("SELECT id FROM servers WHERE invite_code = ?"), (code,))
        exists = cursor.fetchone()
        conn.close()
        if not exists:
            return code

def create_server(name, owner_id):
    conn = get_db()
    cursor = get_cursor(conn)
    invite_code = generate_invite_code()
    try:
        if IS_POSTGRES:
            cursor.execute(
                "INSERT INTO servers (name, invite_code, owner_id) VALUES (%s, %s, %s) RETURNING id",
                (name, invite_code, owner_id)
            )
            server_id = cursor.fetchone()["id"]
            
            cursor.execute(
                "INSERT INTO server_members (server_id, user_id) VALUES (%s, %s) ON CONFLICT (server_id, user_id) DO NOTHING",
                (server_id, owner_id)
            )
            
            cursor.execute(
                "INSERT INTO channels (server_id, name, type) VALUES (%s, %s, 'text')",
                (server_id, "geral")
            )
            cursor.execute(
                "INSERT INTO channels (server_id, name, type) VALUES (%s, %s, 'voice')",
                (server_id, "Geral")
            )
        else:
            cursor.execute(
                "INSERT INTO servers (name, invite_code, owner_id) VALUES (?, ?, ?)",
                (name, invite_code, owner_id)
            )
            server_id = cursor.lastrowid
            
            cursor.execute(
                "INSERT INTO server_members (server_id, user_id) VALUES (?, ?)",
                (server_id, owner_id)
            )
            
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
    cursor = get_cursor(conn)
    try:
        cursor.execute(qry("SELECT id FROM servers WHERE invite_code = ?"), (invite_code,))
        server = cursor.fetchone()
        if not server:
            return None
        
        server_id = server["id"]
        
        if IS_POSTGRES:
            cursor.execute(
                "INSERT INTO server_members (server_id, user_id) VALUES (%s, %s) ON CONFLICT (server_id, user_id) DO NOTHING",
                (server_id, user_id)
            )
        else:
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
    cursor = get_cursor(conn)
    cursor.execute(qry("""
        SELECT s.id, s.name, s.invite_code, s.owner_id
        FROM servers s
        JOIN server_members sm ON s.id = sm.server_id
        WHERE sm.user_id = ?
        ORDER BY s.created_at ASC
    """), (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_server_members(server_id):
    conn = get_db()
    cursor = get_cursor(conn)
    cursor.execute(qry("""
        SELECT u.id, u.username, u.avatar_color, u.avatar_url, u.custom_status
        FROM users u
        JOIN server_members sm ON u.id = sm.user_id
        WHERE sm.server_id = ?
        ORDER BY u.username ASC
    """), (server_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_channel(server_id, name, channel_type):
    conn = get_db()
    cursor = get_cursor(conn)
    try:
        if IS_POSTGRES:
            cursor.execute(
                "INSERT INTO channels (server_id, name, type) VALUES (%s, %s, %s) RETURNING id",
                (server_id, name, channel_type)
            )
            channel_id = cursor.fetchone()["id"]
        else:
            cursor.execute(
                "INSERT INTO channels (server_id, name, type) VALUES (?, ?, ?)",
                (server_id, name, channel_type)
            )
            channel_id = cursor.lastrowid
        conn.commit()
        return {"id": channel_id, "server_id": server_id, "name": name, "type": channel_type}
    except Exception as e:
        conn.rollback()
        print(f"Erro ao criar canal: {e}")
        return None
    finally:
        conn.close()

def get_server_channels(server_id):
    conn = get_db()
    cursor = get_cursor(conn)
    cursor.execute(qry("SELECT id, server_id, name, type FROM channels WHERE server_id = ? ORDER BY id ASC"), (server_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_message(channel_id, user_id, content):
    conn = get_db()
    cursor = get_cursor(conn)
    try:
        if IS_POSTGRES:
            cursor.execute(
                "INSERT INTO messages (channel_id, user_id, content) VALUES (%s, %s, %s) RETURNING id, created_at",
                (channel_id, user_id, content)
            )
            row = cursor.fetchone()
            msg_id = row["id"]
            created_at = row["created_at"]
        else:
            cursor.execute(
                "INSERT INTO messages (channel_id, user_id, content) VALUES (?, ?, ?)",
                (channel_id, user_id, content)
            )
            msg_id = cursor.lastrowid
            conn.commit()
            
            cursor.execute("SELECT created_at FROM messages WHERE id = ?", (msg_id,))
            created_at = cursor.fetchone()["created_at"]
            
        # Obter dados do autor da mensagem
        cursor.execute(qry("SELECT username, avatar_color FROM users WHERE id = ?"), (user_id,))
        user = cursor.fetchone()
        
        conn.commit()
        return {
            "id": msg_id,
            "channel_id": channel_id,
            "user_id": user_id,
            "content": content,
            "created_at": str(created_at),
            "username": user["username"],
            "avatar_color": user["avatar_color"]
        }
    except Exception as e:
        conn.rollback()
        print(f"Erro ao salvar mensagem: {e}")
        return None
    finally:
        conn.close()

def get_channel_messages(channel_id, limit=100):
    conn = get_db()
    cursor = get_cursor(conn)
    cursor.execute(qry("""
        SELECT m.id, m.channel_id, m.user_id, m.content, m.created_at, u.username, u.avatar_color
        FROM messages m
        JOIN users u ON m.user_id = u.id
        WHERE m.channel_id = ?
        ORDER BY m.created_at ASC
        LIMIT ?
    """), (channel_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_user_to_default_server(user_id):
    """Verifica se existe algum servidor no banco. Se sim, adiciona o usuário a ele. Se não, cria um servidor padrão."""
    conn = get_db()
    cursor = get_cursor(conn)
    try:
        cursor.execute(qry("SELECT id FROM servers ORDER BY id ASC LIMIT 1"))
        row = cursor.fetchone()
        if row:
            server_id = row["id"]
            if IS_POSTGRES:
                cursor.execute(
                    "INSERT INTO server_members (server_id, user_id) VALUES (%s, %s) ON CONFLICT (server_id, user_id) DO NOTHING",
                    (server_id, user_id)
                )
            else:
                cursor.execute(
                    "INSERT OR IGNORE INTO server_members (server_id, user_id) VALUES (?, ?)",
                    (server_id, user_id)
                )
            conn.commit()
            conn.close()
        else:
            conn.close()
            create_server("Comunidade Principal", user_id)
    except Exception as e:
        print(f"Erro ao adicionar usuário ao servidor padrão: {e}")
        try:
            conn.close()
        except Exception:
            pass
