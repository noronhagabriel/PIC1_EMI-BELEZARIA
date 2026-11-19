"""Servidor local da Emi Belezaria. Execute: python servidor.py"""

import argparse
from contextlib import closing
import hashlib
import hmac
from http import HTTPStatus
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import parse_qsl, urlsplit

from agenda import Erro, catalogo, disponiveis, salvar_reserva, serializar


RAIZ = Path(__file__).resolve().parent
BANCO_PADRAO = RAIZ / "dados" / "agenda.sqlite3"
SESSAO_SEGUNDOS = 8 * 60 * 60
PAGINAS = {"index.html", "login.html", "servicos.html", "agendar.html", "agendamentos.html"}
COOKIE = "emi_sessao"


def conectar(banco):
    db = sqlite3.connect(banco, timeout=8)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def criar_banco(banco):
    Path(banco).parent.mkdir(parents=True, exist_ok=True)
    with closing(conectar(banco)) as db, db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY, nome TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                sal BLOB NOT NULL, senha_hash BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessoes (
                token_hash TEXT PRIMARY KEY, usuario INTEGER NOT NULL REFERENCES usuarios(id),
                expira INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agendamentos (
                id INTEGER PRIMARY KEY, usuario INTEGER NOT NULL REFERENCES usuarios(id),
                servico TEXT NOT NULL, profissional TEXT NOT NULL, data TEXT NOT NULL,
                inicio INTEGER NOT NULL, fim INTEGER NOT NULL CHECK(fim > inicio),
                cancelado INTEGER NOT NULL DEFAULT 0 CHECK(cancelado IN (0,1))
            );
            CREATE INDEX IF NOT EXISTS agenda_data ON agendamentos(data, cancelado);
            CREATE INDEX IF NOT EXISTS agenda_usuario ON agendamentos(usuario, data);
        """)


def senha_hash(senha, sal):
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, 600_000)


def token_hash(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def email_senha(dados):
    email = dados.get("email")
    senha = dados.get("senha")
    if not isinstance(email, str) or not isinstance(senha, str):
        raise Erro(400, "Informe um e-mail e uma senha.")
    email = email.strip().casefold()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise Erro(400, "Informe um e-mail válido.")
    if not 8 <= len(senha) <= 128:
        raise Erro(400, "Use uma senha com 8 a 128 caracteres.")
    return email, senha


class Atendimento(BaseHTTPRequestHandler):
    server_version = "EmiBelezaria/1"
    sys_version = ""

    def enviar(self, status, conteudo, tipo, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(conteudo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        if cookie is not None:
            valor, validade = cookie
            self.send_header("Set-Cookie", f"{COOKIE}={valor}; Path=/; HttpOnly; SameSite=Strict; Max-Age={validade}")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(conteudo)

    def responder_json(self, status, dados, cookie=None):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.enviar(status, corpo, "application/json; charset=utf-8", cookie)

    def origem_local(self):
        hosts = {f"{nome}:{self.server.server_port}" for nome in ("localhost", "127.0.0.1")}
        if self.server.server_port == 80:
            hosts.update(("localhost", "127.0.0.1"))
        host = self.headers.get("Host", "").lower()
        if host not in hosts:
            raise Erro(403, "Endereço do servidor inválido.")
        origem = self.headers.get("Origin")
        if origem and origem != f"http://{host}":
            raise Erro(403, "Origem da solicitação inválida.")

    def dados_json(self):
        if self.headers.get_content_type() != "application/json":
            raise Erro(415, "Envie os dados em formato JSON.")
        tamanho = self.headers.get("Content-Length", "")
        if not re.fullmatch(r"[0-9]{1,9}", tamanho):
            raise Erro(400, "Tamanho da solicitação inválido.")
        if int(tamanho) > 16_384:
            raise Erro(413, "Solicitação muito extensa.")
        try:
            dados = json.loads(self.rfile.read(int(tamanho)).decode("utf-8"))
            # Surrogates sem par são aceitos pelo decodificador JSON, mas não
            # constituem texto UTF-8 válido para armazenar no SQLite.
            json.dumps(dados, ensure_ascii=False).encode("utf-8")
        except (ValueError, UnicodeError, RecursionError):
            raise Erro(400, "O corpo da solicitação deve conter JSON válido.") from None
        if not isinstance(dados, dict):
            raise Erro(400, "Informe um objeto JSON.")
        return dados

    def token(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        cookie = cookies.get(COOKIE)
        if cookie and re.fullmatch(r"[0-9a-f]{64}", cookie.value):
            return token_hash(cookie.value)
        return None

    def usuario(self, db):
        linha = db.execute("""
            SELECT u.id, u.nome, u.email FROM sessoes s JOIN usuarios u ON u.id=s.usuario
            WHERE s.token_hash=? AND s.expira>?
        """, (self.token(), int(time.time()))).fetchone()
        return dict(linha) if linha else None

    def entrar(self, db, dados, cadastro):
        email, senha = email_senha(dados)
        if cadastro:
            nome = dados.get("nome")
            if not isinstance(nome, str) or not 2 <= len(nome.strip()) <= 80:
                raise Erro(400, "Informe um nome com 2 a 80 caracteres.")
            nome = nome.strip()
            sal = secrets.token_bytes(16)
            try:
                db.execute("INSERT INTO usuarios(nome,email,sal,senha_hash) VALUES(?,?,?,?)",
                           (nome, email, sal, senha_hash(senha, sal)))
            except sqlite3.IntegrityError:
                raise Erro(409, "Este e-mail já está cadastrado.") from None
        linha = db.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()
        if not cadastro:
            calculada = senha_hash(senha, linha["sal"] if linha else bytes(16))
            if not linha or not hmac.compare_digest(calculada, linha["senha_hash"]):
                raise Erro(401, "E-mail ou senha incorretos.")
        agora = int(time.time())
        token = secrets.token_hex(32)
        db.execute("DELETE FROM sessoes WHERE expira<=? OR token_hash=?", (agora, self.token()))
        db.execute("INSERT INTO sessoes(token_hash,usuario,expira) VALUES(?,?,?)",
                   (token_hash(token), linha["id"], agora + SESSAO_SEGUNDOS))
        usuario = {campo: linha[campo] for campo in ("id", "nome", "email")}
        return (201 if cadastro else 200), {"usuario": usuario}, (token, SESSAO_SEGUNDOS)

    def api(self, db, caminho, parametros):
        escrita = self.command == "POST"
        dados = self.dados_json() if escrita else {}
        if not escrita and caminho == "/api/catalogo":
            return 200, catalogo(), None
        if escrita and caminho in ("/api/cadastro", "/api/login"):
            return self.entrar(db, dados, caminho == "/api/cadastro")
        if escrita and caminho == "/api/logout":
            db.execute("DELETE FROM sessoes WHERE token_hash=?", (self.token(),))
            return 200, {"ok": True}, ("", 0)
        usuario = self.usuario(db)
        if not escrita and caminho == "/api/sessao":
            return 200, {"usuario": usuario}, None
        if not usuario:
            raise Erro(401, "Entre na sua conta para continuar.")
        identificador = usuario["id"]
        if not escrita and caminho == "/api/horarios":
            return 200, {"horarios": disponiveis(db, identificador, parametros)}, None
        if caminho == "/api/agendamentos":
            if escrita:
                reserva = salvar_reserva(db, identificador, dados)
                return 201, {"agendamento": reserva}, None
            linhas = db.execute("""
                SELECT * FROM agendamentos WHERE usuario=? ORDER BY data, inicio, id
            """, (identificador,))
            return 200, {"agendamentos": [serializar(r) for r in linhas]}, None
        acao = re.fullmatch(r"/api/agendamentos/([0-9]+)/(reagendar|cancelar)", caminho)
        if escrita and acao:
            reserva = salvar_reserva(db, identificador, dados, acao[1], acao[2] == "cancelar")
            return 200, {"agendamento": reserva}, None
        raise Erro(404, "Recurso não encontrado.")

    def estatico(self, caminho):
        nome = caminho.removeprefix("/") or "index.html"
        permitido = (nome in PAGINAS or nome == "style.css" or
                     re.fullmatch(r"[a-zA-Z0-9_-]+\.js", nome) or
                     re.fullmatch(r"assets/[a-zA-Z0-9_.-]+\.(?:png|jpe?g|webp|svg)", nome))
        if not permitido or not (RAIZ / nome).is_file():
            raise Erro(404, "Arquivo não encontrado.")
        tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
        if nome.endswith(".js"):
            tipo = "text/javascript"
        if tipo.startswith("text/"):
            tipo += "; charset=utf-8"
        self.enviar(200, (RAIZ / nome).read_bytes(), tipo)

    def atender(self):
        try:
            self.origem_local()
            try:
                url = urlsplit(self.path)
                parametros = dict(parse_qsl(url.query, keep_blank_values=True, max_num_fields=12))
            except ValueError:
                raise Erro(400, "Endereço inválido.") from None
            if url.path.startswith("/api/"):
                with closing(conectar(self.server.banco)) as db, db:
                    resposta = self.api(db, url.path, parametros)
                self.responder_json(*resposta)
            elif self.command in ("GET", "HEAD"):
                self.estatico(url.path)
            else:
                raise Erro(404, "Recurso não encontrado.")
        except Erro as erro:
            self.responder_json(erro.status, {"erro": str(erro)})
        except sqlite3.Error:
            self.log_error("Falha ao acessar o banco de dados")
            self.responder_json(HTTPStatus.SERVICE_UNAVAILABLE, {"erro": "Banco indisponível. Tente novamente."})

    do_GET = atender
    do_HEAD = atender
    do_POST = atender


def criar_servidor(porta=8000, banco=BANCO_PADRAO):
    criar_banco(banco)
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Atendimento)
    servidor.banco = banco
    return servidor


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agenda local da Emi Belezaria")
    parser.add_argument("--porta", type=int, default=8000)
    parser.add_argument("--banco", type=Path, default=BANCO_PADRAO)
    opcoes = parser.parse_args()
    try:
        with criar_servidor(opcoes.porta, opcoes.banco) as servidor:
            print(f"Emi Belezaria em http://127.0.0.1:{servidor.server_port}/", flush=True)
            servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    except (OSError, sqlite3.Error, OverflowError) as erro:
        parser.exit(1, f"Não foi possível iniciar o servidor: {erro}\n")
