"""Testes de integração HTTP. Execute na raiz com python -m unittest discover -s testes -v."""

import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

from servidor import criar_servidor


class Cliente:
    def __init__(self, endereco):
        self.endereco = endereco
        self.http = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))

    def chamar(self, caminho, dados=None):
        corpo = None if dados is None else json.dumps(dados).encode("utf-8")
        pedido = Request(self.endereco + caminho, data=corpo)
        if corpo is not None:
            pedido.add_header("Content-Type", "application/json")
        try:
            resposta = self.http.open(pedido, timeout=10)
        except HTTPError as falha:
            resposta = falha
        with resposta:
            return resposta.status, json.load(resposta)


class TestAgenda(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.banco = Path(temp.name) / "teste.sqlite3"
        self.iniciar()
        self.addCleanup(self.encerrar)
        self.visitante = Cliente(self.endereco)
        hoje = date.fromisoformat(self.obter(self.visitante, "/api/catalogo")["hoje"])
        dias_ate_segunda = (7 - hoje.weekday()) % 7 or 7
        self.dia = (hoje + timedelta(days=dias_ate_segunda)).isoformat()

    def iniciar(self):
        self.servidor = criar_servidor(porta=0, banco=self.banco)
        porta = self.servidor.server_address[1]
        self.endereco = f"http://127.0.0.1:{porta}"
        self.thread = threading.Thread(
            target=self.servidor.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self.thread.start()

    def encerrar(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.thread.join(timeout=5)

    def obter(self, cliente, caminho, dados=None, esperado=200):
        status, resposta = cliente.chamar(caminho, dados)
        self.assertEqual(status, esperado, (caminho, resposta))
        return resposta

    def cadastrar(self, apelido="ana"):
        cliente = Cliente(self.endereco)
        self.obter(cliente, "/api/cadastro", {
            "nome": apelido.title(), "email": f"{apelido}@example.org", "senha": "teste-2026",
        }, 201)
        return cliente

    def marcacao(self, hora="09:00", servico="corte", profissional="mariana"):
        return {"servico": servico, "profissional": profissional, "data": self.dia, "horario": hora}

    def reservar(self, cliente, **opcoes):
        return self.obter(cliente, "/api/agendamentos", self.marcacao(**opcoes), 201)["agendamento"]

    def horarios(self, cliente, **opcoes):
        params = {"servico": "corte", "profissional": "mariana", "data": self.dia, **opcoes}
        return self.obter(cliente, "/api/horarios?" + urlencode(params))["horarios"]

    def agenda(self, cliente):
        return self.obter(cliente, "/api/agendamentos")["agendamentos"]

    def test_catalogo_do_prototipo(self):
        servicos = self.obter(self.visitante, "/api/catalogo")["servicos"]
        self.assertEqual(
            {s["id"]: (s["duracao"], s["preco"], s["profissional"]) for s in servicos},
            {"corte": (60, 70, "mariana"), "escova": (45, 50, "mariana"),
             "manicure": (50, 35, "beatriz"), "pedicure": (50, 40, "beatriz"),
             "hidratacao": (60, 60, "mariana"), "coloracao": (120, 150, "mariana"),
             "sobrancelhas": (30, 30, "camila")},
        )

    def test_cadastro_login_e_saida(self):
        self.assertIsNone(self.obter(self.visitante, "/api/sessao")["usuario"])
        self.obter(self.visitante, "/api/agendamentos", esperado=401)
        self.obter(self.visitante, "/api/agendamentos", self.marcacao(), 401)
        ana = self.cadastrar()
        self.assertEqual(self.obter(ana, "/api/sessao")["usuario"]["email"], "ana@example.org")
        self.obter(ana, "/api/logout", {})
        self.obter(ana, "/api/agendamentos", esperado=401)
        self.obter(ana, "/api/login", {"email": "ana@example.org", "senha": "senha-errada"}, 401)
        self.obter(ana, "/api/login", {"email": "ana@example.org", "senha": "teste-2026"})
        self.assertEqual(self.agenda(ana), [])

    def test_reagendamento_e_cancelamento_liberam_horarios(self):
        ana = self.cadastrar()
        reserva = self.reservar(ana)
        recurso = f"/api/agendamentos/{reserva['id']}"
        self.assertNotIn("09:00", self.horarios(ana))
        self.assertIn("09:00", self.horarios(ana, ignorar=reserva["id"]))
        alterada = self.obter(ana, recurso + "/reagendar", {"data": self.dia, "horario": "11:00"})
        self.assertEqual(alterada["agendamento"]["id"], reserva["id"])
        self.assertEqual([item["horario"] for item in self.agenda(ana)], ["11:00"])
        self.assertIn("09:00", self.horarios(ana))
        self.assertNotIn("11:00", self.horarios(ana))
        cancelada = self.obter(ana, recurso + "/cancelar", {})
        self.assertEqual(cancelada["agendamento"]["status"], "cancelado")
        self.assertEqual(self.agenda(ana)[0]["status"], "cancelado")
        self.assertIn("11:00", self.horarios(ana))
        self.assertEqual(self.reservar(ana, hora="11:00")["status"], "confirmado")

    def test_profissional_e_cliente_nao_podem_sobrepor_atendimentos(self):
        ana, bia = self.cadastrar(), self.cadastrar("bia")
        self.reservar(ana, servico="coloracao")
        self.obter(bia, "/api/agendamentos", self.marcacao("10:30"), 409)
        manicure = self.marcacao("10:30", "manicure", "beatriz")
        self.obter(ana, "/api/agendamentos", manicure, 409)
        self.obter(bia, "/api/agendamentos", manicure, 201)
        self.assertIn("11:00", self.horarios(ana))

    def test_conflito_ao_reagendar_preserva_reserva_original(self):
        ana, bia = self.cadastrar(), self.cadastrar("bia")
        reserva = self.reservar(ana)
        self.reservar(bia, hora="11:00")
        self.obter(ana, f"/api/agendamentos/{reserva['id']}/reagendar",
                   {"data": self.dia, "horario": "11:00"}, 409)
        original = self.agenda(ana)
        self.assertEqual([(r["horario"], r["status"]) for r in original], [("09:00", "confirmado")])

    def test_agendas_individuais(self):
        ana, bia = self.cadastrar(), self.cadastrar("bia")
        reserva = self.reservar(ana)
        self.assertEqual(self.agenda(bia), [])
        recurso = f"/api/agendamentos/{reserva['id']}"
        self.obter(bia, recurso + "/cancelar", {}, 404)
        self.obter(bia, recurso + "/reagendar", {"data": self.dia, "horario": "10:00"}, 404)
        self.assertEqual(self.agenda(ana)[0]["status"], "confirmado")

    def test_disputa_simultanea_pelo_mesmo_horario(self):
        clientes = [self.cadastrar("ana"), self.cadastrar("bia")]
        largada = threading.Barrier(2)

        def tentar(cliente):
            largada.wait(timeout=5)
            return cliente.chamar("/api/agendamentos", self.marcacao())[0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(executor.map(tentar, clientes), [201, 409])
        self.assertEqual(sum(len(self.agenda(c)) for c in clientes), 1)

    def test_recusa_dados_invalidos(self):
        ana = self.cadastrar()
        for alteracoes in ({"data": "2026-02-30"}, {"profissional": "camila"},
                           {"horario": "09h05"}, {"servico": "inexistente"}):
            with self.subTest(alteracoes=alteracoes):
                self.obter(ana, "/api/agendamentos", {**self.marcacao(), **alteracoes}, 400)
        self.assertEqual(self.agenda(ana), [])

    def test_persistencia_apos_reinicio(self):
        ana = self.cadastrar()
        id_anterior = self.reservar(ana)["id"]
        self.encerrar()
        self.iniciar()
        nova_sessao = Cliente(self.endereco)
        self.obter(nova_sessao, "/api/login", {"email": "ana@example.org", "senha": "teste-2026"})
        self.assertEqual([(r["id"], r["status"]) for r in self.agenda(nova_sessao)],
                         [(id_anterior, "confirmado")])


if __name__ == "__main__":
    unittest.main()
