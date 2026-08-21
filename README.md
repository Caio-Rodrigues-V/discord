# Discord Clan 🎮🔊

Um aplicativo web completo e auto-hospedado inspirado no Discord, construído com **FastAPI (Python)** no backend e **HTML5/Tailwind CSS/JavaScript** no frontend. 

A plataforma permite que você e seus amigos conversem por texto em canais persistentes, entrem em chamadas de voz com baixa latência (WebRTC) e compartilhem a tela!

---

## 🚀 Como Executar o Aplicativo

Para rodar o projeto, você só precisa ter o **Python** instalado. O script de execução se encarregará de criar o ambiente virtual, instalar as dependências e iniciar o servidor.

1. Abra o terminal (PowerShell ou Prompt de Comando) na pasta do projeto.
2. Execute o seguinte comando:
   ```bash
   python run.py
   ```
3. O servidor será iniciado em: **`http://localhost:8000`**
4. Para testar localmente em seu computador, abra duas janelas de navegador (uma normal e uma anônima) no link acima, crie duas contas de teste e teste as chamadas e mensagens!

---

## 👥 Como Jogar/Conversar com Amigos (Internet ou Rede)

Por motivos de segurança, os navegadores modernos **bloqueiam o acesso ao microfone e compartilhamento de tela** em conexões HTTP que não sejam no `localhost`. 

Para que seus amigos possam acessar de outras redes/computadores e usar a voz/vídeo, você deve disponibilizar o aplicativo sob uma conexão **HTTPS**.

A forma mais simples e gratuita de fazer isso é usando o **Ngrok**:

1. Faça o download gratuito do [Ngrok](https://ngrok.com/).
2. Com o seu servidor rodando (`python run.py`), abra um novo terminal e digite:
   ```bash
   ngrok http 8000
   ```
3. O Ngrok gerará um link seguro que começa com **`https://...`**.
4. Copie esse link HTTPS e envie para os seus amigos. Eles conseguirão entrar, criar suas contas, enviar mensagens e entrar em call de voz e tela sem qualquer bloqueio!

---

## 🛠️ Tecnologias Utilizadas

* **Backend**: FastAPI (Python), Uvicorn (ASGI Server), SQLite (Banco de dados embutido e persistente).
* **Frontend**: HTML5, Tailwind CSS (Estilização baseada em classes do Discord), Lucide Icons (Ícones modernos).
* **Comunicação em Tempo Real**:
  * **WebSockets**: Sincronização instantânea de chat de texto e sinalização WebRTC.
  * **WebRTC**: Conexão Peer-to-Peer de áudio e vídeo (compartilhamento de tela) de alta qualidade e baixa latência entre os navegadores.
