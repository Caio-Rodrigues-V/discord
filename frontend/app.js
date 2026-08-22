// --- Configurações e Estado da Aplicação ---
const API_URL = window.location.origin;
const WS_URL = (window.location.protocol === "https:" ? "wss://" : "ws://") + window.location.host + "/ws";

let currentUser = null;
let servers = [];
let channels = [];
let activeServerId = null; // null significa tela "Home" (DMs)
let activeChannelId = null; // canal de texto ativo
let activeVoiceChannelId = null; // canal de voz ativo
let activeVoiceUsers = []; // lista de usuários na call atual: [{id, username, avatar_color, speaking, sharingScreen}]
let voiceStates = {}; // channelId -> [{id, username, avatar_color, speaking, sharingScreen}]
let remoteAudioStreams = {}; // peerId -> MediaStream (áudio)
let remoteVideoStreams = {}; // peerId -> MediaStream (vídeo/tela)

// WebRTC
let ws = null;
let peerConnections = {}; // peerId -> RTCPeerConnection
let localStream = null; // Stream do microfone
let screenStream = null; // Stream do compartilhamento de tela
let isMuted = false;
let isDeafened = false;
let isSharingScreen = false;
let speakingLoopActive = false;
let focusedUserId = null; // ID do usuário que está em foco na call (se houver)
let locallyMutedUsers = new Set(); // IDs dos usuários mutados localmente

let rtcConfig = {
    iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
        { urls: 'stun:stun2.l.google.com:19302' }
    ]
};

async function loadConfig() {
    try {
        const res = await fetch(`${API_URL}/api/config`);
        if (res.ok) {
            const data = await res.json();
            rtcConfig = data.rtcConfig;
            console.log("Configurações WebRTC carregadas com sucesso.");
        }
    } catch (e) {
        console.error("Erro ao carregar configurações de RTC:", e);
    }
}

// --- Sistema de Visualização (Abas) ---
function showView(viewName) {
    const chat = document.getElementById("chat-container");
    const home = document.getElementById("home-container");
    const voice = document.getElementById("voice-grid-container");
    
    chat.classList.add("hidden");
    home.classList.add("hidden");
    voice.classList.add("hidden");
    
    if (viewName === 'chat') {
        chat.classList.remove("hidden");
    } else if (viewName === 'home') {
        home.classList.remove("hidden");
    } else if (viewName === 'voice') {
        voice.classList.remove("hidden");
        renderVoiceGrid();
    }
}

// --- Inicialização ---
document.addEventListener("DOMContentLoaded", async () => {
    await loadConfig();
    checkAuth();
    setupEventListeners();
    lucide.createIcons();
});

// --- Event Listeners Globais ---
function setupEventListeners() {
    // Autenticação
    document.getElementById("auth-form").addEventListener("submit", handleAuthSubmit);
    document.getElementById("auth-toggle-btn").addEventListener("click", toggleAuthMode);
    
    // Chat
    document.getElementById("chat-form").addEventListener("submit", handleSendChatMessage);
    
    // Criação de Servidor
    document.getElementById("create-server-form").addEventListener("submit", handleCreateServer);
    
    // Entrada em Servidor
    document.getElementById("join-server-form").addEventListener("submit", handleJoinServer);
    
    // Criação de Canal
    document.getElementById("create-channel-form").addEventListener("submit", handleCreateChannel);
}

// --- Autenticação ---
function checkAuth() {
    const token = localStorage.getItem("token");
    const userStr = localStorage.getItem("user");
    
    if (token && userStr) {
        currentUser = JSON.parse(userStr);
        currentUser.token = token;
        showApp();
    } else {
        showAuth();
    }
}

function showAuth() {
    document.getElementById("auth-screen").classList.remove("hidden");
    document.getElementById("app-screen").classList.add("hidden");
}

function showApp() {
    document.getElementById("auth-screen").classList.add("hidden");
    document.getElementById("app-screen").classList.remove("hidden");
    
    // Configurar Painel do Usuário no rodapé
    const avatarCircle = document.getElementById("user-avatar-circle");
    avatarCircle.innerText = currentUser.username.slice(0, 2).toUpperCase();
    avatarCircle.style.backgroundColor = currentUser.avatar_color;
    document.getElementById("user-panel-name").innerText = currentUser.username;
    
    // Inicializar WebSocket e carregar dados
    connectWebSocket();
    loadServers();
    selectHome();
}

async function handleAuthSubmit(e) {
    e.preventDefault();
    const usernameInput = document.getElementById("auth-username");
    const passwordInput = document.getElementById("auth-password");
    const isRegister = document.getElementById("auth-btn").innerText === "Registrar-se";
    
    const url = isRegister ? `${API_URL}/api/auth/register` : `${API_URL}/api/auth/login`;
    const payload = {
        username: usernameInput.value.trim(),
        password: passwordInput.value
    };
    
    try {
        const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || "Erro ao realizar login/registro.");
        }
        
        localStorage.setItem("token", data.token);
        localStorage.setItem("user", JSON.stringify(data.user));
        
        currentUser = data.user;
        currentUser.token = data.token;
        
        // Reset formulário
        usernameInput.value = "";
        passwordInput.value = "";
        document.getElementById("auth-error").classList.add("hidden");
        
        showApp();
        
    } catch (err) {
        const errDiv = document.getElementById("auth-error");
        errDiv.innerText = err.message;
        errDiv.classList.remove("hidden");
    }
}

function toggleAuthMode() {
    const title = document.querySelector("#auth-screen h2");
    const sub = document.querySelector("#auth-screen p");
    const btn = document.getElementById("auth-btn");
    const toggleText = document.getElementById("auth-toggle-text");
    const toggleBtn = document.getElementById("auth-toggle-btn");
    
    if (btn.innerText === "Entrar") {
        title.innerText = "Criar uma conta";
        sub.innerText = "Crie seu usuário para começar a conversar com seus amigos!";
        btn.innerText = "Registrar-se";
        toggleText.innerText = "Já possui uma conta?";
        toggleBtn.innerText = "Entrar";
    } else {
        title.innerText = "Boas-vindas de volta!";
        sub.innerText = "Estamos muito animados em ver você novamente!";
        btn.innerText = "Entrar";
        toggleText.innerText = "Precisando de uma conta?";
        toggleBtn.innerText = "Registre-se";
    }
}

function logout() {
    // Desconectar qualquer call de voz ativa
    disconnectVoice();
    
    // Fechar socket
    if (ws) {
        ws.close();
        ws = null;
    }
    
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    currentUser = null;
    showAuth();
}

// --- WebSocket ---
function connectWebSocket() {
    if (!currentUser) return;
    
    ws = new WebSocket(`${WS_URL}?token=${currentUser.token}`);
    
    ws.onopen = () => {
        console.log("Conectado ao servidor de sinalização WebSocket.");
        // Ping periódico para manter a conexão ativa
        setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                sendWsMessage({ type: "ping" });
            }
        }, 30000);
    };
    
    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        handleWebSocketMessage(message);
    };
    
    ws.onclose = () => {
        console.log("Conexão WebSocket fechada. Tentando reconectar...");
        if (currentUser) {
            setTimeout(connectWebSocket, 3000);
        }
    };
    
    ws.onerror = (err) => {
        console.error("Erro WebSocket:", err);
    };
}

function sendWsMessage(message) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(message));
    }
}

function handleWebSocketMessage(msg) {
    switch (msg.type) {
        case "pong":
            // Keep alive
            break;
            
        case "chat_message":
            // Recebeu uma mensagem no canal ativo
            if (activeChannelId === msg.message.channel_id) {
                appendChatMessage(msg.message);
            }
            break;
            
        case "voice_states":
            // Snapshot inicial de todos os participantes dos canais de voz
            voiceStates = msg.states || {};
            renderChannels();
            break;
            
        case "voice_channel_state":
            // Estado inicial da call ao entrar nela
            if (msg.channel_id === activeVoiceChannelId) {
                // Mapear usuários iniciais na call
                activeVoiceUsers = msg.users.map(u => ({
                    ...u,
                    speaking: false,
                    sharingScreen: false
                }));
                
                // Sincronizar com o voiceStates do canal
                voiceStates[msg.channel_id] = activeVoiceUsers.map(u => ({ ...u }));
                
                // Conectar com todos os usuários existentes
                activeVoiceUsers.forEach(user => {
                    if (user.id !== currentUser.id) {
                        createPeerConnection(user.id, true);
                    }
                });
                
                renderVoiceGrid();
                renderChannels(); // Atualizar indicador de participantes na barra de canais
            }
            break;
            
        case "voice_user_joined":
            // Adicionar ao rastreador de canais geral
            if (!voiceStates[msg.channel_id]) voiceStates[msg.channel_id] = [];
            if (!voiceStates[msg.channel_id].find(u => u.id === msg.user.id)) {
                voiceStates[msg.channel_id].push({
                    ...msg.user,
                    speaking: false,
                    sharingScreen: false
                });
            }
            
            // Se for o nosso canal ativo, iniciar conexão WebRTC
            if (msg.channel_id === activeVoiceChannelId) {
                const newUser = {
                    ...msg.user,
                    speaking: false,
                    sharingScreen: false
                };
                
                // Evitar duplicações na lista local de call
                if (!activeVoiceUsers.find(u => u.id === newUser.id)) {
                    activeVoiceUsers.push(newUser);
                }
                
                // Criar PeerConnection passiva (esperando a oferta de quem entrou)
                createPeerConnection(newUser.id, false);
                renderVoiceGrid();
            }
            renderChannels();
            break;
            
        case "voice_user_left":
            const leftUserId = msg.user_id;
            
            // Remover do rastreador de canais geral
            if (voiceStates[msg.channel_id]) {
                voiceStates[msg.channel_id] = voiceStates[msg.channel_id].filter(u => u.id !== leftUserId);
            }
            
            // Se for do nosso canal ativo, fechar conexões
            if (msg.channel_id === activeVoiceChannelId) {
                // Fechar conexão com ele
                if (peerConnections[leftUserId]) {
                    peerConnections[leftUserId].close();
                    delete peerConnections[leftUserId];
                }
                if (remoteAudioStreams[leftUserId]) {
                    delete remoteAudioStreams[leftUserId];
                }
                if (remoteVideoStreams[leftUserId]) {
                    delete remoteVideoStreams[leftUserId];
                }
                
                const peerAudios = document.querySelectorAll(`.audio-peer-${leftUserId}`);
                peerAudios.forEach(a => a.remove());
                
                // Se o usuário focado saiu, tirar o foco
                if (focusedUserId === leftUserId) {
                    focusedUserId = null;
                }
                
                // Atualizar lista local da call
                activeVoiceUsers = activeVoiceUsers.filter(u => u.id !== leftUserId);
                renderVoiceGrid();
            }
            renderChannels();
            break;
            
        case "webrtc_signal":
            // Mensagem de sinalização WebRTC recebida de um peer
            handleWebRTCSignal(msg.sender_id, msg.signal);
            break;
            
        case "voice_speaking":
            // Outro usuário começou/parou de falar
            const speakUser = activeVoiceUsers.find(u => u.id === msg.user_id);
            if (speakUser) {
                speakUser.speaking = msg.speaking;
                updateSpeakingUI(msg.user_id, msg.speaking);
            }
            // Sincronizar com o voiceStates geral
            for (const cid in voiceStates) {
                const u = voiceStates[cid].find(u => u.id === msg.user_id);
                if (u) {
                    u.speaking = msg.speaking;
                    break;
                }
            }
            renderChannels();
            break;
            
        case "screen_share_status":
            // Outro usuário começou/parou de compartilhar tela
            const screenUser = activeVoiceUsers.find(u => u.id === msg.user_id);
            if (screenUser) {
                screenUser.sharingScreen = msg.sharing;
                if (!msg.sharing) {
                    // Limpar stream remota de vídeo
                    if (remoteVideoStreams[msg.user_id]) {
                        const tracks = remoteVideoStreams[msg.user_id].getVideoTracks();
                        tracks.forEach(t => t.stop());
                        delete remoteVideoStreams[msg.user_id];
                    }
                    if (focusedUserId === msg.user_id) {
                        focusedUserId = null;
                    }
                }
                renderVoiceGrid();
            }
            // Sincronizar com o voiceStates geral
            for (const cid in voiceStates) {
                const u = voiceStates[cid].find(u => u.id === msg.user_id);
                if (u) {
                    u.sharingScreen = msg.sharing;
                    break;
                }
            }
            renderChannels();
            break;
    }
}

// --- Carregamento e Navegação ---

async function loadServers() {
    try {
        const res = await fetch(`${API_URL}/api/servers?token=${currentUser.token}`);
        if (res.status === 401) {
            logout();
            return;
        }
        if (!res.ok) throw new Error("Erro ao buscar servidores");
        servers = await res.json();
        renderServerList();
    } catch (err) {
        console.error(err);
    }
}

function renderServerList() {
    const container = document.getElementById("server-list-container");
    container.innerHTML = "";
    
    servers.forEach(server => {
        const initials = server.name.split(" ").map(n => n[0]).join("").slice(0, 3).toUpperCase();
        
        const isSelected = activeServerId === server.id;
        
        const serverBtn = document.createElement("div");
        serverBtn.className = "relative group flex items-center justify-center w-12 h-12 rounded-[24px] bg-discord-light hover:rounded-[16px] hover:bg-discord-brand text-gray-300 hover:text-white transition-all duration-200 cursor-pointer";
        if (isSelected) {
            serverBtn.classList.remove("bg-discord-light", "rounded-[24px]");
            serverBtn.classList.add("bg-discord-brand", "rounded-[16px]", "text-white");
        }
        
        serverBtn.onclick = () => selectServer(server.id);
        
        serverBtn.innerHTML = `
            <div class="absolute left-0 w-1 bg-white rounded-r-md transition-all duration-200 ${isSelected ? 'h-10' : 'group-hover:h-5 h-0'}" id="indicator-${server.id}"></div>
            <span class="text-sm font-bold">${initials}</span>
            <span class="absolute left-[80px] bg-discord-darkest text-white text-xs font-bold px-3 py-1.5 rounded shadow-lg whitespace-nowrap hidden group-hover:inline z-50 border border-gray-800">${server.name}</span>
        `;
        
        container.appendChild(serverBtn);
    });
}

function selectHome() {
    activeServerId = null;
    activeChannelId = null;
    
    // Atualizar indicadores de servidores
    renderServerList();
    document.getElementById("home-indicator").className = "absolute left-0 w-1 bg-white rounded-r-md h-10 transition-all duration-200";
    
    // Ajustar visualização lateral
    document.getElementById("server-header-name").innerText = "Mensagens Diretas";
    document.getElementById("text-channels-container").innerHTML = "";
    document.getElementById("voice-channels-container").innerHTML = "";
    
    showView('home');
}

async function selectServer(serverId) {
    activeServerId = serverId;
    document.getElementById("home-indicator").className = "absolute left-0 w-1 bg-white rounded-r-md h-0 transition-all duration-200";
    
    const server = servers.find(s => s.id === serverId);
    if (!server) return;
    
    document.getElementById("server-header-name").innerText = server.name;
    document.getElementById("invite-share-server-name").innerText = server.name;
    document.getElementById("invite-share-code-display").innerText = server.invite_code;
    
    // Atualizar UI de servidores
    renderServerList();
    
    // Carregar canais do servidor
    await loadChannels(serverId);
    
    // Selecionar canal de texto padrão (primeiro disponível)
    const firstTextChan = channels.find(c => c.type === 'text');
    if (firstTextChan) {
        selectTextChannel(firstTextChan.id, firstTextChan.name);
    } else {
        // Sem canais de texto
        document.getElementById("chat-container").classList.add("hidden");
    }
    
    // Carregar lista de membros do servidor
    loadServerMembers(serverId);
}

async function loadChannels(serverId) {
    try {
        const res = await fetch(`${API_URL}/api/servers/${serverId}/channels?token=${currentUser.token}`);
        if (res.status === 401) {
            logout();
            return;
        }
        if (!res.ok) throw new Error();
        channels = await res.json();
        renderChannels();
    } catch (e) {
        console.error("Erro ao buscar canais:", e);
    }
}

function renderChannels() {
    const textContainer = document.getElementById("text-channels-container");
    const voiceContainer = document.getElementById("voice-channels-container");
    
    textContainer.innerHTML = "";
    voiceContainer.innerHTML = "";
    
    channels.forEach(chan => {
        const isSelectedText = activeChannelId === chan.id;
        const isSelectedVoice = activeVoiceChannelId === chan.id;
        
        const chanEl = document.createElement("div");
        
        if (chan.type === 'text') {
            chanEl.className = `flex items-center px-2 py-1.5 rounded cursor-pointer transition-colors duration-150 text-gray-400 hover:bg-discord-light hover:text-gray-200 group ${isSelectedText ? 'bg-discord-light text-white font-medium' : ''}`;
            chanEl.onclick = () => selectTextChannel(chan.id, chan.name);
            chanEl.innerHTML = `
                <i data-lucide="hash" class="w-5 h-5 mr-1.5 text-gray-400 flex-shrink-0"></i>
                <span class="truncate text-sm flex-1">${chan.name}</span>
            `;
            textContainer.appendChild(chanEl);
        } else {
            chanEl.className = `flex flex-col rounded cursor-pointer transition-colors duration-150 text-gray-400 hover:bg-discord-light hover:text-gray-200 ${isSelectedVoice ? 'bg-discord-light text-white font-medium' : ''}`;
            
            // Criar linha principal do canal de voz
            const channelHeader = document.createElement("div");
            channelHeader.className = "flex items-center px-2 py-1.5 flex-1";
            channelHeader.onclick = () => joinVoiceChannel(chan.id, chan.name);
            channelHeader.innerHTML = `
                <i data-lucide="volume-2" class="w-5 h-5 mr-1.5 text-gray-400 flex-shrink-0"></i>
                <span class="truncate text-sm flex-1">${chan.name}</span>
            `;
            chanEl.appendChild(channelHeader);
            
            // Se houver usuários neste canal de voz, exibir lista abaixo (lida de voiceStates em tempo real)
            const chanUsers = voiceStates[chan.id] || [];
            if (chanUsers.length > 0) {
                const usersList = document.createElement("div");
                usersList.className = "pl-7 pr-2 pb-1.5 flex flex-col space-y-1";
                
                chanUsers.forEach(u => {
                    const uRow = document.createElement("div");
                    uRow.className = "flex items-center space-x-2 py-0.5 text-xs text-gray-300";
                    
                    const uAvatar = document.createElement("div");
                    uAvatar.className = "w-5 h-5 rounded-full flex items-center justify-center text-[8px] font-bold text-white flex-shrink-0";
                    uAvatar.innerText = u.username.slice(0, 2).toUpperCase();
                    uAvatar.style.backgroundColor = u.avatar_color;
                    
                    const borderStyle = u.speaking ? 'outline outline-2 outline-discord-green' : '';
                    uAvatar.className += ` ${borderStyle}`;
                    
                    uRow.appendChild(uAvatar);
                    
                    const uName = document.createElement("span");
                    uName.className = "truncate flex-1";
                    uName.innerText = u.username;
                    uRow.appendChild(uName);
                    
                    // Indicadores de status
                    if (u.sharingScreen) {
                        const live = document.createElement("span");
                        live.className = "bg-discord-red text-[8px] px-1 rounded font-bold text-white uppercase tracking-wider flex-shrink-0";
                        live.innerText = "Ao vivo";
                        uRow.appendChild(live);
                    }
                    
                    if (locallyMutedUsers.has(u.id)) {
                        const muteIcon = document.createElement("i");
                        muteIcon.setAttribute("data-lucide", "volume-x");
                        muteIcon.className = "w-3 h-3 text-discord-red ml-1 flex-shrink-0";
                        uRow.appendChild(muteIcon);
                    }
                    
                    usersList.appendChild(uRow);
                });
                chanEl.appendChild(usersList);
            }
            
            voiceContainer.appendChild(chanEl);
        }
    });
    
    lucide.createIcons();
}

async function loadServerMembers(serverId) {
    try {
        const res = await fetch(`${API_URL}/api/servers/${serverId}/members?token=${currentUser.token}`);
        if (res.status === 401) {
            logout();
            return;
        }
        if (!res.ok) throw new Error();
        const members = await res.json();
        
        document.getElementById("members-count").innerText = members.length;
        const container = document.getElementById("members-list-container");
        container.innerHTML = "";
        
        members.forEach(m => {
            const row = document.createElement("div");
            row.className = "flex items-center space-x-2.5 p-1.5 rounded hover:bg-discord-light cursor-pointer text-gray-300 hover:text-white";
            
            const initials = m.username.slice(0, 2).toUpperCase();
            
            row.innerHTML = `
                <div class="w-8 h-8 rounded-full flex items-center justify-center text-white font-bold text-xs" style="background-color: ${m.avatar_color}">
                    ${initials}
                </div>
                <span class="text-sm font-medium truncate">${m.username}</span>
            `;
            container.appendChild(row);
        });
        
    } catch (e) {
        console.error("Erro ao carregar membros:", e);
    }
}

// --- Chat de Texto ---

async function selectTextChannel(channelId, channelName) {
    activeChannelId = channelId;
    showView('chat');
    
    // Atualizar cabeçalho
    document.getElementById("chat-header-name").innerText = channelName;
    document.getElementById("chat-input").placeholder = `Conversar em #${channelName}`;
    
    // Atualizar destaque de canais
    renderChannels();
    
    // Carregar histórico
    try {
        const res = await fetch(`${API_URL}/api/channels/${channelId}/messages?token=${currentUser.token}`);
        if (res.status === 401) {
            logout();
            return;
        }
        if (!res.ok) throw new Error();
        const messages = await res.json();
        
        const container = document.getElementById("messages-container");
        container.innerHTML = "";
        
        messages.forEach(msg => {
            appendChatMessage(msg);
        });
        
    } catch (e) {
        console.error("Erro ao carregar mensagens:", e);
    }
}

function appendChatMessage(msg) {
    const container = document.getElementById("messages-container");
    
    const initials = msg.username.slice(0, 2).toUpperCase();
    const time = new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    
    const msgEl = document.createElement("div");
    msgEl.className = "flex items-start space-x-4 select-text hover:bg-discord-dark hover:bg-opacity-20 px-2 py-1 rounded transition-colors";
    
    msgEl.innerHTML = `
        <div class="w-10 h-10 rounded-full flex items-center justify-center text-white font-bold flex-shrink-0" style="background-color: ${msg.avatar_color}">
            ${initials}
        </div>
        <div class="flex flex-col min-w-0">
            <div class="flex items-baseline space-x-2">
                <span class="font-bold text-white text-sm hover:underline cursor-pointer">${msg.username}</span>
                <span class="text-[10px] text-gray-400 font-medium">${time}</span>
            </div>
            <p class="text-gray-300 text-sm whitespace-pre-wrap break-all mt-0.5">${msg.content}</p>
        </div>
    `;
    
    container.appendChild(msgEl);
    
    // Rolar para o final
    container.scrollTop = container.scrollHeight;
}

async function handleSendChatMessage(e) {
    e.preventDefault();
    const input = document.getElementById("chat-input");
    const content = input.value.trim();
    if (!content || !activeChannelId) return;
    
    sendWsMessage({
        type: "chat_message",
        channel_id: activeChannelId,
        content: content
    });
    
    input.value = "";
}

// --- Chamada de Voz e WebRTC ---

async function joinVoiceChannel(channelId, channelName) {
    if (activeVoiceChannelId === channelId) {
        // Se clicar no canal de voz ativo, abrir a tela de grade
        showView('voice');
        return;
    }
    
    // Desconectar se já estiver em outra call
    if (activeVoiceChannelId) {
        disconnectVoice();
    }
    
    try {
        // Pedir autorização do microfone
        localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        
        activeVoiceChannelId = channelId;
        
        // Atualizar Painel de Status
        document.getElementById("voice-connection-panel").classList.remove("hidden");
        document.getElementById("voice-channel-connected-name").innerText = channelName;
        document.getElementById("voice-call-header-name").innerText = channelName;
        document.getElementById("btn-go-to-call").classList.remove("hidden");
        
        // Configurar botão de mutar local baseado no estado atual
        if (localStream.getAudioTracks().length > 0) {
            localStream.getAudioTracks()[0].enabled = !isMuted;
        }
        
        // Iniciar detecção de som local
        startSpeakingDetection(localStream);
        
        // Entrar no canal de voz via WebSocket
        sendWsMessage({
            type: "voice_join",
            channel_id: channelId
        });
        
        // Abrir diretamente a grade de chamada
        showView('voice');
        renderChannels();
        
    } catch (err) {
        console.error("Não foi possível conectar à chamada:", err);
        alert("Erro de mídia: Necessário acesso ao microfone para chamadas de voz.");
    }
}

function disconnectVoice() {
    if (!activeVoiceChannelId) return;
    
    // Parar compartilhamento de tela
    if (isSharingScreen) {
        stopScreenShare();
    }
    
    // Parar microfone local
    if (localStream) {
        localStream.getTracks().forEach(track => track.stop());
        localStream = null;
    }
    
    // Parar detector de voz
    speakingLoopActive = false;
    
    // Fechar todas as conexões P2P
    for (const peerId in peerConnections) {
        peerConnections[peerId].close();
    }
    peerConnections = {};
    remoteAudioStreams = {};
    remoteVideoStreams = {};
    
    // Remover elementos de áudio do DOM
    const audios = document.querySelectorAll("audio[class^='audio-peer-']");
    audios.forEach(a => a.remove());
    
    // Enviar mensagem de saída
    sendWsMessage({
        type: "voice_leave",
        channel_id: activeVoiceChannelId
    });
    
    activeVoiceChannelId = null;
    activeVoiceUsers = [];
    focusedUserId = null;
    
    // Atualizar UI
    document.getElementById("voice-connection-panel").classList.add("hidden");
    document.getElementById("btn-go-to-call").classList.add("hidden");
    
    if (activeChannelId) {
        showView('chat');
    } else {
        showView('home');
    }
    
    renderChannels();
}

function createPeerConnection(peerId, isInitiator) {
    const pc = new RTCPeerConnection(rtcConfig);
    peerConnections[peerId] = pc;
    
    // Adicionar tracks locais
    if (localStream) {
        localStream.getTracks().forEach(track => {
            pc.addTrack(track, localStream);
        });
    }
    
    if (isSharingScreen && screenStream) {
        screenStream.getTracks().forEach(track => {
            const sender = pc.addTrack(track, screenStream);
            if (!pc.screenSenders) pc.screenSenders = [];
            pc.screenSenders.push(sender);
        });
    }
    
    // Handlers WebRTC
    pc.onicecandidate = (event) => {
        if (event.candidate) {
            sendWsMessage({
                type: "webrtc_signal",
                target_id: peerId,
                signal: { candidate: event.candidate }
            });
        }
    };
    
    pc.ontrack = (event) => {
        console.log(`Recebeu track de ${peerId}:`, event.track.kind);
        
        const stream = event.streams[0] || new MediaStream([event.track]);
        
        if (event.track.kind === 'audio') {
            remoteAudioStreams[peerId] = stream;
            
            // Criar ou atualizar player de áudio usando o ID da track para suportar múltiplos canais (voz + áudio de tela)
            let audioEl = document.getElementById(`audio-track-${event.track.id}`);
            if (!audioEl) {
                audioEl = document.createElement("audio");
                audioEl.id = `audio-track-${event.track.id}`;
                audioEl.className = `audio-peer-${peerId}`; // Salva o ID do dono para limpeza e mute local
                audioEl.autoplay = true;
                document.body.appendChild(audioEl);
            }
            audioEl.srcObject = stream;
            // Configurar mutar se estiver deafened ou se o usuário estiver mutado localmente
            audioEl.muted = isDeafened || locallyMutedUsers.has(peerId);
            
            audioEl.play().catch(err => {
                console.warn("Autoplay bloqueado:", err);
            });
        } else if (event.track.kind === 'video') {
            remoteVideoStreams[peerId] = stream;
            
            // Quando a track de vídeo (tela) chegar, renderizamos a grade de voz para exibi-la
            renderVoiceGrid();
        }
    };
    
    // Sinalização Perfect Negotiation (Evita colisões)
    let makingOffer = false;
    const polite = currentUser.id < peerId; // Um será polite e outro impolite
    
    pc.onnegotiationneeded = async () => {
        try {
            makingOffer = true;
            await pc.setLocalDescription();
            sendWsMessage({
                type: "webrtc_signal",
                target_id: peerId,
                signal: { description: pc.localDescription }
            });
        } catch (err) {
            console.error("Erro em onnegotiationneeded:", err);
        } finally {
            makingOffer = false;
        }
    };
    
    pc.oniceconnectionstatechange = () => {
        if (pc.iceConnectionState === "failed") {
            pc.restartIce();
        }
    };
}

async function handleWebRTCSignal(senderId, signal) {
    const pc = peerConnections[senderId];
    if (!pc) return;
    
    const polite = currentUser.id < senderId;
    
    try {
        if (signal.description) {
            const desc = signal.description;
            const offerCollision = (desc.type === "offer") && (pc.signalingState !== "stable");
            
            const ignoreOffer = !polite && offerCollision;
            if (ignoreOffer) {
                console.log(`Conflito: Ignorando oferta do peer ${senderId}`);
                return;
            }
            
            if (offerCollision) {
                // Fazer rollback se colidir e for polite
                await Promise.all([
                    pc.setLocalDescription({ type: "rollback" }),
                    pc.setRemoteDescription(desc)
                ]);
            } else {
                await pc.setRemoteDescription(desc);
            }
            
            if (desc.type === "offer") {
                await pc.setLocalDescription();
                sendWsMessage({
                    type: "webrtc_signal",
                    target_id: senderId,
                    signal: { description: pc.localDescription }
                });
            }
        } else if (signal.candidate) {
            try {
                await pc.addIceCandidate(signal.candidate);
            } catch (err) {
                console.warn("Falha ao adicionar ICE candidate:", err);
            }
        }
    } catch (err) {
        console.error("Erro ao processar sinal WebRTC:", err);
    }
}

// --- Detecção de Voz Local ---
function startSpeakingDetection(stream) {
    if (speakingLoopActive) return;
    
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const analyser = audioCtx.createAnalyser();
        const source = audioCtx.createMediaStreamSource(stream);
        
        analyser.fftSize = 256;
        source.connect(analyser);
        
        const bufferLength = analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);
        
        let localSpeaking = false;
        speakingLoopActive = true;
        
        function checkAudio() {
            if (!speakingLoopActive) return;
            
            analyser.getByteFrequencyData(dataArray);
            let sum = 0;
            for (let i = 0; i < bufferLength; i++) {
                sum += dataArray[i];
            }
            const average = sum / bufferLength;
            
            // Limiar para detectar fala (15 é um bom valor médio)
            const currentlySpeaking = average > 15 && !isMuted;
            if (currentlySpeaking !== localSpeaking) {
                localSpeaking = currentlySpeaking;
                
                // Enviar status de fala para o servidor
                sendWsMessage({
                    type: "voice_speaking",
                    speaking: localSpeaking
                });
                
                // Atualizar nossa própria UI
                updateSpeakingUI(currentUser.id, localSpeaking);
            }
            
            requestAnimationFrame(checkAudio);
        }
        
        checkAudio();
        
    } catch (e) {
        console.warn("AudioContext não pôde ser iniciado:", e);
    }
}

// --- Compartilhamento de Tela ---

async function toggleScreenShare() {
    if (isSharingScreen) {
        stopScreenShare();
        return;
    }
    
    try {
        screenStream = await navigator.mediaDevices.getDisplayMedia({
            video: {
                width: { max: 1920 },
                height: { max: 1080 },
                frameRate: { max: 30 }
            },
            audio: true // Permitir compartilhar o som do sistema/aba
        });
        
        isSharingScreen = true;
        updateScreenControlsUI();
        
        // Listener para caso o usuário encerre o compartilhamento pelo botão nativo do navegador
        if (screenStream.getVideoTracks().length > 0) {
            screenStream.getVideoTracks()[0].onended = () => {
                stopScreenShare();
            };
        }
        
        // Adicionar todas as tracks (vídeo e áudio da tela se houver) a todas as PeerConnections
        for (const peerId in peerConnections) {
            const pc = peerConnections[peerId];
            if (!pc.screenSenders) pc.screenSenders = [];
            
            screenStream.getTracks().forEach(track => {
                const sender = pc.addTrack(track, screenStream);
                pc.screenSenders.push(sender);
            });
        }
        
        // Avisar canal WebSocket
        sendWsMessage({
            type: "screen_share_status",
            sharing: true
        });
        
        // Adicionar nossa própria tela como ativa na lista local
        const me = activeVoiceUsers.find(u => u.id === currentUser.id);
        if (me) me.sharingScreen = true;
        
        renderVoiceGrid();
        
    } catch (e) {
        console.warn("Erro ao obter compartilhamento de tela:", e);
        isSharingScreen = false;
        updateScreenControlsUI();
    }
}

function stopScreenShare() {
    if (!isSharingScreen) return;
    
    isSharingScreen = false;
    updateScreenControlsUI();
    
    if (screenStream) {
        screenStream.getTracks().forEach(t => t.stop());
        screenStream = null;
    }
    
    // Remover tracks das conexões
    for (const peerId in peerConnections) {
        const pc = peerConnections[peerId];
        if (pc.screenSenders) {
            pc.screenSenders.forEach(sender => {
                try {
                    pc.removeTrack(sender);
                } catch (e) {
                    console.warn(e);
                }
            });
            pc.screenSenders = [];
        }
    }
    
    sendWsMessage({
        type: "screen_share_status",
        sharing: false
    });
    
    const me = activeVoiceUsers.find(u => u.id === currentUser.id);
    if (me) me.sharingScreen = false;
    
    if (focusedUserId === currentUser.id) {
        focusedUserId = null;
    }
    
    renderVoiceGrid();
}

function updateScreenControlsUI() {
    const screenIcon = document.getElementById("user-screen-icon") || document.getElementById("panel-screen-icon");
    const callScreenIcon = document.getElementById("call-screen-icon");
    
    if (screenStream) {
        if (screenIcon) screenIcon.className = "w-4 h-4 text-discord-green";
        if (callScreenIcon) {
            callScreenIcon.className = "w-5 h-5 text-discord-green";
            callScreenIcon.parentElement.classList.add("bg-discord-green", "bg-opacity-20");
        }
    } else {
        if (screenIcon) screenIcon.className = "w-4 h-4";
        if (callScreenIcon) {
            callScreenIcon.className = "w-5 h-5 text-gray-300";
            callScreenIcon.parentElement.classList.remove("bg-discord-green", "bg-opacity-20");
        }
    }
}

// --- Controles de Microfone e Ouvido ---

function toggleMic() {
    isMuted = !isMuted;
    
    // Atualizar microfone local se houver
    if (localStream && localStream.getAudioTracks().length > 0) {
        localStream.getAudioTracks()[0].enabled = !isMuted;
    }
    
    // Atualizar UI
    const micIcons = [
        document.getElementById("user-mic-icon"),
        document.getElementById("panel-mic-icon"),
        document.getElementById("call-mic-icon")
    ];
    
    micIcons.forEach(icon => {
        if (!icon) return;
        if (isMuted) {
            icon.setAttribute("data-lucide", "mic-off");
            icon.classList.add("text-discord-red");
            icon.parentElement.classList.add("text-discord-red");
        } else {
            icon.setAttribute("data-lucide", "mic");
            icon.classList.remove("text-discord-red");
            icon.parentElement.classList.remove("text-discord-red");
        }
    });
    
    lucide.createIcons();
}

function toggleDeafen() {
    isDeafened = !isDeafened;
    
    // Se ensurdecer, automaticamente muta. Se desensurdecer, desmuta (ou mantém conforme o estado anterior)
    if (isDeafened) {
        if (!isMuted) toggleMic();
    } else {
        if (isMuted) toggleMic();
    }
    
    // Muta todos os áudios recebidos dos peers
    const audios = document.querySelectorAll("audio[id^='audio-peer-']");
    audios.forEach(audio => {
        audio.muted = isDeafened;
    });
    
    // Atualizar UI
    const deafenIcon = document.getElementById("user-deafen-icon");
    if (deafenIcon) {
        if (isDeafened) {
            deafenIcon.setAttribute("data-lucide", "volume-x");
            deafenIcon.classList.add("text-discord-red");
        } else {
            deafenIcon.setAttribute("data-lucide", "volume-2");
            deafenIcon.classList.remove("text-discord-red");
        }
    }
    lucide.createIcons();
}

// --- Renderização da UI de Voz ---

function toggleVoiceGridMode() {
    const voiceVisible = !document.getElementById("voice-grid-container").classList.contains("hidden");
    if (voiceVisible) {
        if (activeChannelId) {
            showView('chat');
        } else {
            showView('home');
        }
    } else {
        showView('voice');
    }
}

function focusVoiceUser(userId) {
    if (focusedUserId === userId) {
        focusedUserId = null; // Tira o foco
    } else {
        focusedUserId = userId; // Foca no usuário
    }
    renderVoiceGrid();
}

function renderVoiceGrid() {
    const container = document.getElementById("voice-grid");
    container.innerHTML = "";
    
    if (!activeVoiceChannelId) return;
    
    // Se houver alguém em foco, ajustar a disposição do grid
    if (focusedUserId && activeVoiceUsers.some(u => u.id === focusedUserId)) {
        // Layout de Foco: Card principal grande e os outros menores ao lado
        container.className = "flex flex-col lg:flex-row gap-4 w-full h-full max-h-[85vh]";
        
        const focusCard = createVoiceUserCard(focusedUserId, true);
        
        const sidebar = document.createElement("div");
        sidebar.className = "flex lg:flex-col gap-2 overflow-x-auto lg:overflow-y-auto lg:w-64 w-full flex-shrink-0";
        
        activeVoiceUsers.forEach(u => {
            if (u.id !== focusedUserId) {
                const smallCard = createVoiceUserCard(u.id, false);
                sidebar.appendChild(smallCard);
            }
        });
        
        container.appendChild(focusCard);
        container.appendChild(sidebar);
    } else {
        // Layout em Grade normal (grid equilibrado)
        container.className = "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 w-full h-full max-h-[85vh]";
        
        activeVoiceUsers.forEach(user => {
            const card = createVoiceUserCard(user.id, false);
            container.appendChild(card);
        });
    }
    
    // Anexar streams de vídeo
    activeVoiceUsers.forEach(u => {
        const videoEl = document.getElementById(`video-peer-${u.id}`);
        if (!videoEl) return;
        
        if (u.id === currentUser.id && isSharingScreen && screenStream) {
            videoEl.srcObject = screenStream;
        } else if (u.id !== currentUser.id && u.sharingScreen && remoteVideoStreams[u.id]) {
            videoEl.srcObject = remoteVideoStreams[u.id];
        } else {
            videoEl.classList.add("hidden");
        }
    });
}

function createVoiceUserCard(userId, isLarge) {
    const user = activeVoiceUsers.find(u => u.id === userId);
    if (!user) return document.createElement("div");
    
    const initials = user.username.slice(0, 2).toUpperCase();
    
    const card = document.createElement("div");
    card.className = `voice-card relative bg-discord-voiceCard rounded-lg flex flex-col items-center justify-center border border-gray-800 overflow-hidden cursor-pointer ${isLarge ? 'flex-1 h-full min-h-[300px]' : 'h-40 md:h-48'}`;
    card.ondblclick = () => focusVoiceUser(userId);
    
    // Margem de fala ativa
    const speakingClass = user.speaking ? 'speaking-active' : '';
    
    card.innerHTML = `
        <!-- Vídeo de Compartilhamento de Tela -->
        <video id="video-peer-${user.id}" autoplay playsinline class="w-full h-full object-contain bg-black ${user.sharingScreen ? '' : 'hidden'}"></video>
        
        <!-- Avatar do Usuário -->
        <div id="avatar-peer-${user.id}" class="absolute flex flex-col items-center space-y-3 ${user.sharingScreen ? 'hidden' : ''}">
            <div class="w-16 h-16 rounded-full flex items-center justify-center text-white font-bold text-xl transition-all duration-300 ${speakingClass}" style="background-color: ${user.avatar_color}">
                ${initials}
            </div>
        </div>
        
        <!-- Badge com Nome de Usuário -->
        <div class="absolute bottom-2 left-2 bg-black bg-opacity-60 px-2 py-1 rounded text-xs text-white font-medium flex items-center space-x-2 max-w-[85%]">
            <span class="truncate">${user.username}</span>
            ${user.speaking ? '<i data-lucide="mic" class="w-3.5 h-3.5 text-discord-green"></i>' : ''}
            ${user.sharingScreen ? '<span class="bg-discord-red text-[8px] px-1 rounded font-bold uppercase tracking-wider">Ao Vivo</span>' : ''}
            ${user.id !== currentUser.id ? `
                <button onclick="event.stopPropagation(); toggleLocalMute(${user.id})" class="p-0.5 rounded hover:bg-gray-700 transition-colors ml-1" title="Silenciar usuário para você">
                    <i data-lucide="${locallyMutedUsers.has(user.id) ? 'volume-x' : 'volume-2'}" class="w-3.5 h-3.5 ${locallyMutedUsers.has(user.id) ? 'text-discord-red' : 'text-gray-400 hover:text-white'}"></i>
                </button>
            ` : ''}
        </div>
    `;
    
    // Atualizar ícones internos
    setTimeout(() => {
        lucide.createIcons();
    }, 0);
    
    return card;
}

function updateSpeakingUI(userId, speaking) {
    const avatar = document.getElementById(`avatar-peer-${userId}`);
    if (avatar) {
        const circle = avatar.querySelector("div");
        if (circle) {
            if (speaking) {
                circle.classList.add("speaking-active");
            } else {
                circle.classList.remove("speaking-active");
            }
        }
    }
}

function toggleLocalMute(userId) {
    if (locallyMutedUsers.has(userId)) {
        locallyMutedUsers.delete(userId);
        // Desmutar todos os elementos de áudio deste usuário localmente
        const audios = document.querySelectorAll(`.audio-peer-${userId}`);
        audios.forEach(a => a.muted = isDeafened);
    } else {
        locallyMutedUsers.add(userId);
        // Mutar todos os elementos de áudio deste usuário localmente
        const audios = document.querySelectorAll(`.audio-peer-${userId}`);
        audios.forEach(a => a.muted = true);
    }
    renderVoiceGrid();
    renderChannels();
}

// --- Criação / Entrada em Servidor ---

async function handleCreateServer(e) {
    e.preventDefault();
    const nameInput = document.getElementById("create-server-name");
    const name = nameInput.value.trim();
    if (!name) return;
    
    try {
        const res = await fetch(`${API_URL}/api/servers?token=${currentUser.token}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name })
        });
        
        if (res.status === 401) {
            logout();
            return;
        }
        if (!res.ok) throw new Error();
        const server = await res.json();
        
        servers.push(server);
        toggleModal("create-server-modal", false);
        nameInput.value = "";
        
        // Selecionar o novo servidor
        selectServer(server.id);
        
    } catch (e) {
        console.error("Erro ao criar servidor:", e);
        alert("Erro ao criar o servidor.");
    }
}

async function handleJoinServer(e) {
    e.preventDefault();
    const codeInput = document.getElementById("join-server-code");
    const invite_code = codeInput.value.trim();
    if (!invite_code) return;
    
    try {
        const res = await fetch(`${API_URL}/api/servers/join?token=${currentUser.token}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ invite_code })
        });
        
        if (res.status === 401) {
            logout();
            return;
        }
        
        const data = await res.json();
        
        if (!res.ok) {
            throw new Error(data.detail || "Erro");
        }
        
        toggleModal("join-server-modal", false);
        codeInput.value = "";
        document.getElementById("join-server-error").classList.add("hidden");
        
        // Recarregar servidores e focar no novo
        await loadServers();
        selectServer(data.server_id);
        
    } catch (e) {
        const errDiv = document.getElementById("join-server-error");
        errDiv.innerText = e.message;
        errDiv.classList.remove("hidden");
    }
}

// --- Gerenciamento de Canais ---

function openCreateChannelModal(type) {
    const radioText = document.querySelector("input[name='chan-type'][value='text']");
    const radioVoice = document.querySelector("input[name='chan-type'][value='voice']");
    
    if (type === 'text') {
        radioText.checked = true;
    } else {
        radioVoice.checked = true;
    }
    
    updateChanModalUI();
    toggleModal("create-channel-modal", true);
}

function updateChanModalUI() {
    const selectedType = document.querySelector("input[name='chan-type']:checked").value;
    const labelText = document.getElementById("label-chan-type-text");
    const labelVoice = document.getElementById("label-chan-type-voice");
    const icon = document.getElementById("create-channel-icon");
    const input = document.getElementById("create-channel-name");
    
    if (selectedType === 'text') {
        labelText.className = "flex items-center p-3 bg-discord-light rounded cursor-pointer border border-discord-brand";
        labelVoice.className = "flex items-center p-3 bg-discord-light rounded cursor-pointer border border-transparent hover:border-discord-brand";
        icon.setAttribute("data-lucide", "hash");
        input.placeholder = "novo-canal";
    } else {
        labelVoice.className = "flex items-center p-3 bg-discord-light rounded cursor-pointer border border-discord-brand";
        labelText.className = "flex items-center p-3 bg-discord-light rounded cursor-pointer border border-transparent hover:border-discord-brand";
        icon.setAttribute("data-lucide", "volume-2");
        input.placeholder = "Novo Canal";
    }
    
    lucide.createIcons();
}

async function handleCreateChannel(e) {
    e.preventDefault();
    const nameInput = document.getElementById("create-channel-name");
    const name = nameInput.value.trim();
    const type = document.querySelector("input[name='chan-type']:checked").value;
    if (!name || !activeServerId) return;
    
    try {
        const res = await fetch(`${API_URL}/api/servers/${activeServerId}/channels?token=${currentUser.token}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, type })
        });
        
        if (res.status === 401) {
            logout();
            return;
        }
        if (!res.ok) throw new Error();
        const chan = await res.json();
        
        channels.push(chan);
        toggleModal("create-channel-modal", false);
        nameInput.value = "";
        
        renderChannels();
        
        // Se for canal de texto, selecionar ele
        if (chan.type === 'text') {
            selectTextChannel(chan.id, chan.name);
        }
        
    } catch (e) {
        console.error("Erro ao criar canal:", e);
        alert("Erro ao criar canal.");
    }
}

// --- Helpers de UI ---

function toggleModal(modalId, show) {
    const modal = document.getElementById(modalId);
    if (show) {
        modal.classList.remove("hidden");
    } else {
        modal.classList.add("hidden");
    }
}

function toggleMemberList() {
    const panel = document.getElementById("members-list-panel");
    panel.classList.toggle("hidden");
}

function copyInviteCode() {
    toggleModal("invite-share-modal", true);
}

function copyInviteCodeText() {
    const code = document.getElementById("invite-share-code-display").innerText;
    navigator.clipboard.writeText(code).then(() => {
        const btn = document.getElementById("btn-copy-invite");
        btn.innerText = "Copiado!";
        btn.className = "bg-discord-green text-white text-xs font-bold px-4 py-2 rounded transition-colors";
        
        setTimeout(() => {
            btn.innerText = "Copiar";
            btn.className = "bg-discord-brand hover:bg-discord-brandHover text-white text-xs font-bold px-4 py-2 rounded transition-colors";
        }, 2000);
    });
}
