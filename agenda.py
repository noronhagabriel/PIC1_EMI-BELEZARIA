"""Catálogo e regras de disponibilidade da Emi Belezaria."""

import re
from datetime import date, datetime, timedelta


class Erro(Exception):
    def __init__(self, status, mensagem):
        super().__init__(mensagem)
        self.status = status


PROFISSIONAIS = [
    {"id": "mariana", "nome": "Mariana", "especialidade": "Cabelo e coloração"},
    {"id": "beatriz", "nome": "Beatriz", "especialidade": "Manicure e pedicure"},
    {"id": "camila", "nome": "Camila", "especialidade": "Sobrancelhas e estética"},
]

SERVICOS = {
    chave: dict(id=chave, nome=nome, duracao=minutos, preco=preco, profissional=prof)
    for chave, nome, minutos, preco, prof in [
        ("corte", "Corte Feminino", 60, 70, "mariana"),
        ("escova", "Escova", 45, 50, "mariana"),
        ("manicure", "Manicure", 50, 35, "beatriz"),
        ("pedicure", "Pedicure", 50, 40, "beatriz"),
        ("hidratacao", "Hidratação Capilar", 60, 60, "mariana"),
        ("coloracao", "Coloração", 120, 150, "mariana"),
        ("sobrancelhas", "Design de Sobrancelhas", 30, 30, "camila"),
    ]
}


def catalogo():
    hoje = date.today()
    return dict(servicos=list(SERVICOS.values()), profissionais=PROFISSIONAIS,
                hoje=hoje.isoformat(), limite=(hoje + timedelta(days=90)).isoformat())


def obter_servico(dados):
    chave = dados.get("servico")
    servico = SERVICOS.get(chave) if isinstance(chave, str) else None
    if not servico or servico["profissional"] != dados.get("profissional"):
        raise Erro(400, "Escolha um serviço e uma profissional que realize esse atendimento.")
    return servico


def data_valida(valor, hoje):
    if not isinstance(valor, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", valor):
        raise Erro(400, "Informe uma data válida.")
    try:
        dia = date.fromisoformat(valor)
    except ValueError:
        raise Erro(400, "Informe uma data válida.") from None
    if not hoje <= dia <= hoje + timedelta(days=90):
        raise Erro(400, "Escolha uma data entre hoje e os próximos 90 dias.")
    return dia


def formatar_hora(minutos):
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def horarios_livres(db, usuario, servico, data, ignorar=0):
    agora = datetime.now()
    dia = data_valida(data, agora.date())
    if dia.weekday() == 6:
        return []
    ocupados = db.execute("""
        SELECT inicio, fim FROM agendamentos
        WHERE data = ? AND cancelado = 0 AND id != ?
          AND (profissional = ? OR usuario = ?)
    """, (data, ignorar, servico["profissional"], usuario)).fetchall()
    livres = []
    duracao = servico["duracao"]
    for inicio in range(9 * 60, 18 * 60 - duracao + 1, 30):
        if dia == agora.date() and inicio <= agora.hour * 60 + agora.minute:
            continue
        if any(inicio < fim_ocupado and inicio_ocupado < inicio + duracao
               for inicio_ocupado, fim_ocupado in ocupados):
            continue
        livres.append(formatar_hora(inicio))
    return livres


def serializar(reserva):
    horario = formatar_hora(reserva["inicio"])
    agora = datetime.now()
    instante = (agora.date().isoformat(), agora.hour * 60 + agora.minute)
    if reserva["cancelado"]:
        status = "cancelado"
    elif instante < (reserva["data"], reserva["inicio"]):
        status = "confirmado"
    elif instante < (reserva["data"], reserva["fim"]):
        status = "em_atendimento"
    else:
        status = "encerrado"
    return dict(id=reserva["id"], servico=reserva["servico"], profissional=reserva["profissional"],
                data=reserva["data"], horario=horario, status=status)


def reserva_do_usuario(db, usuario, chave):
    if not isinstance(chave, str) or not re.fullmatch(r"[1-9][0-9]{0,17}", chave):
        raise Erro(404, "Agendamento não encontrado.")
    reserva = db.execute("SELECT * FROM agendamentos WHERE id=? AND usuario=?",
                         (int(chave), usuario)).fetchone()
    if reserva is None:
        raise Erro(404, "Agendamento não encontrado.")
    return reserva


def disponiveis(db, usuario, dados):
    servico = obter_servico(dados)
    ignorar = 0
    if "ignorar" in dados:
        atual = reserva_do_usuario(db, usuario, dados["ignorar"])
        if serializar(atual)["status"] != "confirmado" or atual["servico"] != servico["id"]:
            raise Erro(409, "Este agendamento não está disponível para reagendamento.")
        ignorar = atual["id"]
    return horarios_livres(db, usuario, servico, dados.get("data"), ignorar)


def salvar_reserva(db, usuario, dados, chave=None, cancelar=False):
    # O bloqueio começa antes da consulta de disponibilidade. Assim, clientes
    # que confirmam ao mesmo tempo não conseguem reservar o mesmo intervalo.
    db.execute("BEGIN IMMEDIATE")
    atual = reserva_do_usuario(db, usuario, chave) if chave else None
    if atual and serializar(atual)["status"] != "confirmado":
        raise Erro(409, "Somente agendamentos futuros e confirmados podem ser alterados.")
    if cancelar:
        db.execute("UPDATE agendamentos SET cancelado=1 WHERE id=?", (atual["id"],))
    else:
        servico = SERVICOS[atual["servico"]] if atual else obter_servico(dados)
        data, horario = dados.get("data"), dados.get("horario")
        if not isinstance(horario, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", horario):
            raise Erro(400, "Informe um horário válido.")
        livres = horarios_livres(db, usuario, servico, data, atual["id"] if atual else 0)
        if horario not in livres:
            raise Erro(409, "Este horário está indisponível. Escolha outro horário.")
        hora, minuto = map(int, horario.split(":"))
        inicio = hora * 60 + minuto
        fim = inicio + servico["duracao"]
        if atual:
            db.execute("UPDATE agendamentos SET data=?, inicio=?, fim=? WHERE id=?",
                       (data, inicio, fim, atual["id"]))
        else:
            cursor = db.execute("""
                INSERT INTO agendamentos (usuario, servico, profissional, data, inicio, fim)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (usuario, servico["id"], servico["profissional"], data, inicio, fim))
            chave = str(cursor.lastrowid)
    return serializar(reserva_do_usuario(db, usuario, chave))
