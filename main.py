from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker
from pydantic import BaseModel

# --- БАЗА ДАННЫХ ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./messenger.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String, unique=True, index=True)
    nickname = Column(String, unique=True, index=True)
    name = Column(String)
    code = Column(String, nullable=True)

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    sender_nick = Column(String)
    receiver_nick = Column(String)
    text = Column(String)

Base.metadata.create_all(bind=engine)

app = FastAPI()
active_connections = {}

class AuthRequest(BaseModel):
    phone: str
    code: str = None
    nickname: str = None
    name: str = None

@app.post("/auth/request_code")
def request_code(data: AuthRequest):
    db = SessionLocal()
    user = db.query(User).filter(User.phone == data.phone).first()
    if not user:
        user = User(phone=data.phone, code="1234")
        db.add(user)
    else:
        user.code = "1234"
    db.commit()
    db.close()
    return {"message": "Код отправлен (для теста используйте 1234)"}

@app.post("/auth/verify_code")
def verify_code(data: AuthRequest):
    db = SessionLocal()
    user = db.query(User).filter(User.phone == data.phone, User.code == data.code).first()
    if not user:
        db.close()
        raise HTTPException(status_code=400, detail="Неверный код")
    if not user.nickname:
        db.close()
        return {"status": "need_nickname", "message": "Введите ваш @ник и имя", "phone": data.phone}
    db.close()
    return {"status": "success", "nickname": user.nickname, "name": user.name}

@app.post("/auth/setup_profile")
def setup_profile(data: AuthRequest):
    db = SessionLocal()
    user = db.query(User).filter(User.phone == data.phone).first()
    existing = db.query(User).filter(User.nickname == data.nickname).first()
    if existing:
        db.close()
        raise HTTPException(status_code=400, detail="Этот @ник уже занят")
    user.nickname = data.nickname
    user.name = data.name
    user.code = None
    db.commit()
    db.close()
    return {"message": "Профиль создан"}

@app.get("/search/{query}")
def search_users(query: str):
    db = SessionLocal()
    results = db.query(User).filter(
        (User.nickname.contains(query)) | (User.name.contains(query))
    ).limit(10).all()
    db.close()
    return [{"nickname": u.nickname, "name": u.name} for u in results]

@app.get("/history/{user1}/{user2}")
def get_history(user1: str, user2: str):
    db = SessionLocal()
    msgs = db.query(Message).filter(
        ((Message.sender_nick == user1) & (Message.receiver_nick == user2)) |
        ((Message.sender_nick == user2) & (Message.receiver_nick == user1))
    ).order_by(Message.id).all()
    db.close()
    return [{"sender": m.sender_nick, "text": m.text} for m in msgs]

@app.websocket("/ws/{nickname}")
async def websocket_endpoint(websocket: WebSocket, nickname: str):
    await websocket.accept()
    active_connections[nickname] = websocket
    try:
        while True:
            data = await websocket.receive_json()
            receiver = data.get("receiver")
            text = data.get("text")
            db = SessionLocal()
            new_msg = Message(sender_nick=nickname, receiver_nick=receiver, text=text)
            db.add(new_msg)
            db.commit()
            db.close()
            if receiver in active_connections:
                await active_connections[receiver].send_json({"sender": nickname, "text": text})
    except WebSocketDisconnect:
        del active_connections[nickname]

# --- ИНТЕРФЕЙС ---
@app.get("/")
async def get():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Мой Мессенджер</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 0; display: flex; height: 100vh; background: #e5e5e5; }
            .auth-container { width: 100%; height: 100%; display: flex; justify-content: center; align-items: center; background: #2b5278; }
            .auth-box { background: white; padding: 30px; border-radius: 10px; width: 300px; text-align: center; }
            .auth-box input { width: 90%; padding: 10px; margin: 10px 0; border: 1px solid #ccc; border-radius: 5px; }
            .auth-box button { width: 100%; padding: 10px; background: #2b5278; color: white; border: none; border-radius: 5px; cursor: pointer; }
            .app-container { display: none; width: 100%; height: 100%; }
            .sidebar { width: 300px; background: #fff; border-right: 1px solid #ccc; display: flex; flex-direction: column; }
            .main-chat { flex: 1; display: flex; flex-direction: column; background: #f0f0f0; }
            .header { padding: 15px; background: #2b5278; color: white; font-weight: bold; display: flex; justify-content: space-between; }
            .search { padding: 10px; border-bottom: 1px solid #ccc; }
            .search input { width: 95%; padding: 8px; border-radius: 15px; border: 1px solid #ccc; outline: none; }
            .chat-list { flex: 1; overflow-y: auto; }
            .chat-item { padding: 15px; border-bottom: 1px solid #eee; cursor: pointer; }
            .chat-item:hover { background: #f5f5f5; }
            .messages { flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; }
            .message { max-width: 60%; padding: 10px; border-radius: 10px; margin-bottom: 10px; background: #fff; align-self: flex-start; }
            .message.own { background: #d1e7dd; align-self: flex-end; }
            .input-area { padding: 10px; background: #fff; display: flex; border-top: 1px solid #ccc; }
            .input-area input { flex: 1; padding: 10px; border-radius: 20px; border: 1px solid #ccc; outline: none; }
            .input-area button { margin-left: 10px; padding: 10px 20px; border-radius: 20px; background: #2b5278; color: white; border: none; cursor: pointer; }
        </style>
    </head>
    <body>
        <!-- ЭКРАН АВТОРИЗАЦИИ -->
        <div class="auth-container" id="authScreen">
            <div class="auth-box" id="step1">
                <h2>Вход</h2>
                <input type="text" id="phoneInput" placeholder="Номер телефона (79991234567)">
                <button onclick="requestCode()">Получить код</button>
            </div>
            <div class="auth-box" id="step2" style="display:none;">
                <h2>Введите код</h2>
                <p>(тестовый код: 1234)</p>
                <input type="text" id="codeInput" placeholder="Код из SMS">
                <button onclick="verifyCode()">Войти</button>
            </div>
            <div class="auth-box" id="step3" style="display:none;">
                <h2>Создайте профиль</h2>
                <input type="text" id="nickInput" placeholder="@ник (без @)">
                <input type="text" id="nameInput" placeholder="Ваше имя">
                <button onclick="setupProfile()">Готово</button>
            </div>
        </div>

        <!-- ОСНОВНОЙ ИНТЕРФЕЙС -->
        <div class="app-container" id="appScreen">
            <div class="sidebar">
                <div class="header">
                    <span id="myNameDisplay">Мой профиль</span>
                    <button onclick="logout()" style="background:none; border:none; color:white; cursor:pointer;">Выйти</button>
                </div>
                <div class="search">
                    <input type="text" id="searchInput" placeholder="Поиск по @нику..." oninput="searchUsers()">
                </div>
                <div class="chat-list" id="chatList"></div>
            </div>
            <div class="main-chat">
                <div class="header" id="chatName">Выберите чат</div>
                <div class="messages" id="messages"></div>
                <div class="input-area">
                    <input type="text" id="msgInput" placeholder="Написать сообщение..." onkeypress="if(event.key === 'Enter') sendMessage()">
                    <button onclick="sendMessage()">➤</button>
                </div>
            </div>
        </div>

        <script>
            let myNickname = null;
            let currentChat = null;
            let ws = null;
            let currentPhone = null;

            function requestCode() {
                let phone = document.getElementById('phoneInput').value;
                currentPhone = phone;
                fetch('/auth/request_code', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({phone: phone})
                }).then(() => {
                    document.getElementById('step1').style.display = 'none';
                    document.getElementById('step2').style.display = 'block';
                });
            }

            function verifyCode() {
                let code = document.getElementById('codeInput').value;
                fetch('/auth/verify_code', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({phone: currentPhone, code: code})
                }).then(r => r.json()).then(data => {
                    if (data.status === 'success') {
                        loginSuccess(data.nickname, data.name);
                    } else if (data.status === 'need_nickname') {
                        document.getElementById('step2').style.display = 'none';
                        document.getElementById('step3').style.display = 'block';
                    } else {
                        alert("Неверный код!");
                    }
                });
            }

            function setupProfile() {
                let nick = document.getElementById('nickInput').value;
                let name = document.getElementById('nameInput').value;
                fetch('/auth/setup_profile', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({phone: currentPhone, nickname: nick, name: name, code: "1234"})
                }).then(r => {
                    if (r.ok) loginSuccess(nick, name);
                    else alert("Этот ник уже занят!");
                });
            }

            function loginSuccess(nick, name) {
                myNickname = nick;
                document.getElementById('myNameDisplay').innerText = name + " (@" + nick + ")";
                document.getElementById('authScreen').style.display = 'none';
                document.getElementById('appScreen').style.display = 'flex';
                
                ws = new WebSocket("ws://" + window.location.host + "/ws/" + myNickname);
                ws.onmessage = function(event) {
                    let data = JSON.parse(event.data);
                    if (currentChat === data.sender) {
                        let msgDiv = document.createElement('div');
                        msgDiv.className = 'message';
                        msgDiv.innerText = data.text;
                        document.getElementById('messages').appendChild(msgDiv);
                    }
                };
            }

            function logout() {
                location.reload();
            }

            function searchUsers() {
                let query = document.getElementById('searchInput').value;
                if (query.length < 1) {
                    document.getElementById('chatList').innerHTML = '';
                    return;
                }
                fetch('/search/' + query).then(r => r.json()).then(data => {
                    let list = document.getElementById('chatList');
                    list.innerHTML = '';
                    data.forEach(user => {
                        if(user.nickname && user.nickname !== myNickname) {
                            let div = document.createElement('div');
                            div.className = 'chat-item';
                            div.innerText = (user.name || "Без имени") + " (@" + user.nickname + ")";
                            div.onclick = () => openChat(user.nickname);
                            list.appendChild(div);
                        }
                    });
                });
            }
            
            function openChat(nickname) {
                currentChat = nickname;
                document.getElementById('chatName').innerText = "@" + nickname;
                document.getElementById('messages').innerHTML = '';
                
                fetch('/history/' + myNickname + '/' + nickname).then(r => r.json()).then(data => {
                    data.forEach(msg => {
                        let msgDiv = document.createElement('div');
                        msgDiv.className = 'message ' + (msg.sender === myNickname ? 'own' : '');
                        msgDiv.innerText = msg.text;
                        document.getElementById('messages').appendChild(msgDiv);
                    });
                });
            }
            
            function sendMessage() {
                if (!currentChat) return alert("Сначала найдите и выберите чат!");
                let input = document.getElementById('msgInput');
                if (input.value.trim() === "") return;
                
                ws.send(JSON.stringify({ receiver: currentChat, text: input.value }));
                
                let msgDiv = document.createElement('div');
                msgDiv.className = 'message own';
                msgDiv.innerText = input.value;
                document.getElementById('messages').appendChild(msgDiv);
                
                input.value = '';
            }
        </script>
    </body>
    </html>
    """)
